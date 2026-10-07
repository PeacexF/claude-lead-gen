# Data-path patterns, with the bundled adapter that shows each

All snippets run inside `collect_unit(ctx, unit)` or a pure `parse()`. `ctx.fetcher` is the campaign `Fetcher`
(`text`, `json`, `post_json`, `post_form`, `request`).

## Official / public JSON API

`google_places.py`, `companies_house.py`, `hn_hiring.py`

```python
headers = {"X-Api-Key": os.environ["FOO_API_KEY"]}          # header, never the URL: the URL is the cache key
data = ctx.fetcher.post_json(URL, {"q": unit["query"], "pageToken": token}, headers=headers)
token = data.get("nextPageToken")                          # stop when absent
```

- Request only the fields you need (field masks, `fields=`). Some APIs bill per field.
- Paid beyond a free tier? Say so in `ABOUT` and keep default limits small.
- APIs that ask for a contact User-Agent (SEC EDGAR, Nominatim): `camp.fetcher(ua=UA_BOT)`.

## JSON the page calls (XHR)

Found with `browser_network_requests` in the Playwright MCP. Copy the request without cookies and check that it
still answers with a plain fetch. If it needs a session cookie or a signed token, it isn't usable. Fall back to
the next pattern.

```python
data = ctx.fetcher.json(f"{BASE}/api/search?{urllib.parse.urlencode({'q': q, 'page': p})}")
items = data["results"]                                    # KeyError here → raise LayoutChanged instead
```

## State JSON embedded in HTML

`yandex_maps.py` (`<script class="state-view">`), `kwork.py` (`"pagination":` + `JSONDecoder.raw_decode`)

```python
m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
if not m:
    raise LayoutChanged("no __NEXT_DATA__")
state = json.loads(m.group(1))

# a JSON object inside a larger script, without a full JS parser:
i = html.find('"pagination":')
obj, _ = json.JSONDecoder().raw_decode(html[i + len('"pagination":'):])
```

When a missing state block means a captcha page (Yandex), raise `Blocked`, not `LayoutChanged`. Tell the two
apart by a marker only the captcha page has.

## Server-rendered HTML

`flru.py` (split on `qa-project-name="project-item`), `telegram.py` (split on `tgme_widget_message_wrap`, cursor
`?before=<min id>`)

```python
for block in html.split('class="result-item')[1:]:       # one block per record
    name = re.search(r"<h2[^>]*>(.*?)</h2>", block, re.S)
    phone = re.search(r'href="tel:([^"]+)"', block)
```

- Anchor on attributes that carry meaning (`href="tel:"`, `mailto:`, `itemprop=`, `data-id=`), not on generated
  class names (`css-1x2y3z`).
- `html.unescape` every extracted text, and strip tags with `re.sub(r"<[^>]+>", " ", s)`.
- Check page 1 for the marker. If it's missing and there's no "no results" text, raise `LayoutChanged`
  (`flru.py` does this).

## Query API over open data

`osm.py`: geocode the location (Nominatim), then one Overpass QL query per unit, with mirrors and a long timeout.
Use this pattern for any open-data endpoint that takes a query language or filters (CKAN, Socrata, ArcGIS
FeatureServer: `?where=...&outFields=*&f=json&resultOffset=N`).

## External browser tool

`twogis.py`: a separate tool (patched parser-2gis) runs Chrome, writes CSV, and the adapter parses the CSV. Needs
`ready()` returning why it isn't usable, plus a `leadgen setup <tool>` step that installs outside the plugin dir.
Use it only when every pattern above fails and the source permits automated access.

## Detail pages

When the list page lacks the contacts, fetch each record's detail page **inside the same unit** (cached, throttled)
and parse it with a second pure function. Cap detail fetches per unit with a `max_details` spec key and say so in
the docstring. Many sources show contacts only on detail pages, so this costs one request per record.

## Stop rules seen in the bundled adapters

| Adapter | Stop when |
|---|---|
| `kwork.py` | `page > pagination.last_page` or `max_pages` |
| `yandex_maps.py` | page brings no new ids, or `seen >= totalResultCount` |
| `flru.py` | 404, or page brings no new ids |
| `telegram.py` | page brings no new posts; cursor = smallest id seen |
| `google_places.py` | no `nextPageToken`, or `limit` reached |
