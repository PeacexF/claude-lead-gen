# Plan: `parser-builder` skill (a guidebook for building a parser for one source)

Status: plan, written 2026-10-08. When it's built, the SPEC §5.1 row and CURRENT_STATE are updated. This is not
the niche-research skill, which is separate: niche research decides *what* to look for, and this skill builds the
code that collects it from *one* place.

## 1. Problem

The bundled adapters cover generic places: OSM, Google Places, 2GIS, Yandex Maps, HN, freelance boards. Most good
lead lists come from somewhere narrower: a professional chamber's member directory, a regional business
registry, a marketplace's seller list, an industry trade-show exhibitor list, a niche job or tender board. Each
of those is a one-off. Every time, someone has to find where the data actually lives, decide whether it's fair to
take it, write a parser, test it, and keep it from silently returning nothing when the site changes.

The bundled adapters already show the patterns, but they live only in code:

| Pattern | Example in this repo |
|---|---|
| Official JSON API with key | `google_places.py` (key in a header so it never enters the cache key), `companies_house.py` |
| Public JSON API, no key | `hn_hiring.py` (Algolia), `enrich/jobs.py` (Greenhouse/Lever/Ashby) |
| State JSON embedded in HTML | `yandex_maps.py` (`<script class="state-view">`), `kwork.py` (`"pagination":` + `raw_decode`) |
| Server-rendered HTML blocks | `flru.py` (split on a per-item marker, regex fields), `telegram.py` (cursor `?before=`) |
| Query API over open data | `osm.py` (Nominatim geocode → Overpass QL) |
| External browser tool | `twogis.py` (patched parser-2gis, `ready()` + `leadgen setup 2gis`) |
| User's own file | `file.py` (column aliases) |

The skill is the written method, so Claude can build the next adapter the same way every time: ready for the
runner, cached, throttled, tested on fixtures, and loud when it breaks.

## 2. What gets built

One **source adapter** per source, following the contract in `leadgen/sources/__init__.py`:

```python
NAME, KIND ("businesses" | "demand"), REGIONS, ENV, ABOUT, [SNAPSHOT]
units(spec) -> list[dict]          # one unit = one cached raw file
unit_key(unit) -> str
fetcher(camp) -> Fetcher           # per-source delay, UA, language
collect_unit(ctx, unit) -> rows    # fetch + paginate; calls parse()
parse(payload, ...) -> rows        # pure, no I/O: the part the fixtures test
ready() -> str | None              # optional external setup check
```

Rows use the partial-lead field names that `core/merge.normalize` reads (`name, sites, phones, emails, city,
country, address, lat, lon, categories, segment, rating, reviews, source_id, url, legal, signals`, social keys).
Demand rows use the order fields (`title, description, budget, budget_max, currency, category, offers, created,
type`).

Two homes for an adapter:
- **Built in** (`leadgen/sources/<name>.py`): broadly useful sources, added by PR with **synthetic** fixtures.
- **Workspace** (`<workspace>/sources/<name>.py`): one-off or personal sources. They load when `campaign.toml`
  names them (`[[sources]] type = "<name>"`) and the file exists. Built-in names take precedence, and the CLI
  prints the path of every workspace adapter it loads.

## 3. The guidebook workflow (`skills/parser-builder/SKILL.md`)

1. **Qualify the source.** What does it give per record, and how many records? Is it reachable logged out? What
   do robots.txt and the ToS say about automated access? Is there a captcha or rate limit? Is there an official
   API or a bulk download? Write a short source card with a go/no-go. **Stop** if the data needs a login, a
   captcha bypass, or breaks the ToS. Suggest the browser-assisted route or an official export instead.
2. **Find the data path, cheapest first:** official API or bulk file → public JSON endpoint the page itself calls
   (watch the network in the Playwright MCP) → state JSON embedded in the HTML → server-rendered HTML → an external
   browser tool. Prefer stable identifiers and structured fields over visible text.
3. **Design units and pagination.** Decide what one unit is (query × location, one category, one listing page
   range). It is cached as one raw file and never refetched. Pick the pagination type (page number, cursor,
   offset, `next` token) and the stop rule (no new ids, total reached, max pages). Set `SNAPSHOT = True` for live
   feeds.
4. **Capture fixtures.** Save 2–3 real payloads (first page, a later page, the empty/last page) to the scratchpad
   for development. For the repo, reduce them to **synthetic** fixtures in `tests/fixtures/<name>/` with the
   same structure and invented businesses. Real pages hold personal data.
5. **Write the adapter** from `templates/source.py`. Keep `parse()` pure. Raise `LayoutChanged` when the expected
   structure is missing, so the run doesn't return 0 rows quietly. Raise `Blocked` on captcha/429 walls. Set the
   delay in `fetcher()` to the most conservative rate the source tolerates. Keys go in headers, never in URLs.
6. **Test offline.** `parse()` on each fixture gives the expected rows. `collect_unit` with `tests/fakes.FakeFetcher`
   walks pagination and stops. `units`/`unit_key` are stable. Rows survive `merge.normalize` (ids, phones, sites).
7. **Run live, small.** Run one unit with `leadgen collect <slug> --source <name>`, then `leadgen inspect <slug>
   --source <name>` for fill rate per field and sample rows. Compare a few rows against the live page by hand.
8. **Register.** Built-in: add to `MODULES`, add a commented block in `templates/campaign.toml`, a row in
   `docs/sources.md`, and the live-check date in CURRENT_STATE. Workspace: note it in the campaign's `brief.md`.

## 4. Core changes

| # | Change | Where |
|---|---|---|
| 1 | Workspace adapters: `load(name)` falls back to `<workspace>/sources/<name>.py` (by path, only when named in config) | `leadgen/sources/__init__.py` |
| 2 | `LayoutChanged` error; the runner reports it per unit as "layout changed, fix the parser" and keeps going | `core/http.py`, `sources/__init__.py` |
| 3 | `leadgen inspect <slug> [--source]`: rows, fill rate per field, 3 sample rows | `leadgen/cli.py` |
| 4 | Adapter template | `templates/source.py` |
| 5 | Tests for the loader, `LayoutChanged`, and inspect | `tests/` |

## 5. Deliverables and acceptance

| Deliverable | Done when |
|---|---|
| `skills/parser-builder/SKILL.md` + `references/patterns.md` | Covers §3; each pattern links the bundled adapter that shows it |
| Core changes §4 | Unit tests pass; a workspace adapter in a temp workspace collects through the CLI |
| `templates/source.py` | A copy with the TODOs filled passes the test checklist in §3.6 |
| `docs/sources.md` | Lists every bundled adapter (spec keys, coverage, keys/setup) and links this skill for new ones |
