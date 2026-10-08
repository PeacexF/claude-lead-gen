# Sources

A source adapter turns one place (an API, a directory, a file) into rows. Rows from `businesses` sources merge
into `leads.jsonl`. Rows from `demand` sources (orders, tenders, channel posts) are for niche research and stay in
`raw/`. `leadgen sources` lists every adapter with its coverage and whether it's ready (key set, tool installed).

How to choose sources for a market is in the `lead-sourcing` skill. This page is the reference.

## Adapters

### Businesses

| Type | Coverage | Needs | Gives |
|---|---|---|---|
| `osm` | Global; strongest in Europe | — | OpenStreetMap POIs via Nominatim + Overpass: name, website, phone, email, address, socials, VAT. Contacts are present on a minority of POIs, so pair with the site crawl. |
| `google_places` | Global | `GOOGLE_PLACES_API_KEY` | Places API (New) text search: website, phone, rating, review count, Maps URL. Up to 60 per query. Billed past Google's free usage. |
| `companies_house` | UK | `COMPANIES_HOUSE_API_KEY` (free) | Active companies by SIC code, location and incorporation date ("new company" timing signal). No websites or phones. |
| `hn_hiring` | Global, tech | — | Companies posting in Hacker News "Who is hiring?" threads, filtered by keywords and location. Hiring signal. |
| `file` | Any | — | Your own CSV/JSONL: CRM exports, trade-show lists, Apify output. Columns are matched by alias. Unknown columns are kept under `extra`. |
| `yandex_maps` | RU/CIS | — | Website, phones, Telegram/WhatsApp/VK, rating, reviews. Stops at a captcha (re-run later). |
| `twogis` | RU/CIS and other 2GIS countries | `leadgen setup 2gis`, Chrome | Phones, emails, websites, TG/WA/VK, rating, reviews. The best contact coverage in RU/CIS. |
| `kwork_gigs` | RU | — | Kwork sellers for a service query: gigs, prices, reviews. For partners, suppliers or competitors, not buyers. |

### Demand (niche research)

| Type | Coverage | Gives |
|---|---|---|
| `kwork` | RU | Buyer orders: budget, category, number of offers. |
| `flru` | RU | FL.ru projects: budget, type, offers. |
| `pchel` | RU/CIS | pchel.net projects: budget, categories, offers. |
| `workspace_ru` | RU | workspace.ru tenders: budget, service, participants, customer city. Customers are businesses, so these double as warm leads. |
| `telegram` | Global | Public channel posts via `t.me/s/<channel>` (no account). Order channels, news, competitors. |

Demand sources are snapshots: they re-collect at most once a day.

## Spec keys

```toml
[[sources]]
type = "osm"
queries = ["dentist", "office=lawyer", "pilates"]   # preset, tag filter, or a word matched in the name
locations = ["Lisbon, Portugal"]                   # free text, geocoded by Nominatim
limit = 500

[[sources]]
type = "google_places"
queries = ["dentist"]
locations = ["Lisbon, Portugal"]
limit = 60
language = "en"

[[sources]]
type = "companies_house"
sic_codes = ["62012", "70229"]
locations = ["Manchester"]
incorporated_from = "2026-07-01"
incorporated_to = ""
limit = 500

[[sources]]
type = "hn_hiring"
months = 1
keywords = ["python", "fintech"]   # every listed group must match; any word within a group
locations = ["remote", "berlin"]

[[sources]]
type = "file"
paths = ["imports/expo-2026.csv"]  # relative to the campaign directory, else to the workspace
segment = "expo"

[[sources]]
type = "yandex_maps"
queries = ["стоматология"]
locations = ["kazan"]              # a city key, or "<region id>/<slug>" from a yandex.ru/maps URL
pages = 4                          # 25 results per page

[[sources]]
type = "twogis"
queries = ["стоматология"]
locations = ["kazan"]              # 2GIS city codes as in 2gis.ru/<code>
limit = 50
domain = "2gis.ru"
headless = false                   # Chrome runs off-screen by default; headless loses results on some queries

[[sources]]
type = "kwork_gigs"
queries = ["152-фз"]
category = "63"                    # optional Kwork category id

[[sources]]
type = "telegram"
channels = ["some_orders_channel"]
pages = 30

[[sources]]
type = "kwork"                     # likewise flru (max_pages), pchel (max_pages), workspace_ru (newest = 500)
max_pages = 50
```

OSM presets: accountant, architect, bakery, bar, barber, beauty salon, bicycle, brewery, builder, cafe, camping,
car dealer, car repair, car wash, carpenter, clinic, clothes, construction, consulting, coworking, dance school,
dentist, doctor, driving school, electrician, electronics, employment agency, florist, funeral, furniture, gym,
hair salon, hardware, hotel, hvac, insurance, it company, jewelry, kindergarten, kitchen, language school,
laundry, lawyer, marina, marketing agency, massage, museum, notary, optician, pet grooming, pet shop, pharmacy,
photographer, physiotherapist, plumber, printing, psychologist, real estate, restaurant, roofer, school, shoes,
storage, tattoo, travel agency, tyres, veterinary, wedding, winery, yoga.

Each adapter's module docstring in `leadgen/sources/<type>.py` is the authoritative list of its keys.

## How collection behaves

- **One unit, one file.** A unit (e.g. one query × one location) is fetched once and written to
  `raw/<source>/<date>/<unit>.jsonl`. Later runs skip it unless `--refresh`.
- **Polite.** Each source has a per-host delay, and responses are cached in `.leadgen-cache/`.
- **`BLOCKED`.** A 429 or captcha stops that source for the run. Finished units are kept. Re-run later. Never
  lower the delays to push through.
- **`LAYOUT CHANGED`.** The adapter's parser didn't find the structure it expects. The unit fails loudly
  instead of returning zero rows, and two in a row stop the source. Fix the adapter with the `parser-builder`
  skill.
- `leadgen inspect <slug>` shows fill rates per field and sample rows per source, so you can check that a source
  delivered what you expected before widening it.

## Enrichment steps

Run by `leadgen enrich` (and `run`), in this order per lead. Each is skipped for leads that already have it,
unless `--refresh` is given.

| Step | Config | Adds |
|---|---|---|
| `site` | `[enrich] site` | Static crawl of the homepage plus up to `max_inner_pages` contact/about/team/legal pages, plain GETs only: emails, phones, socials, legal ids (ИНН with checksum, ОГРН, UK company number, EU VAT, DE Handelsregister), people (heuristic: verify before use), ~90 tech fingerprints, HTTPS, certificate, mobile viewport, forms, privacy link, cookie notice, copyright year, ATS job-board links. Signals: `no_website`, `outdated_site`, `no_https`, `broken_ssl`, `not_mobile_friendly`, `form_without_privacy_link`. |
| `dns` | `[enrich] dns` | MX, SPF and DMARC via Cloudflare DNS-over-HTTPS: mail provider, sending tools in SPF, `emails[].verified = "mx"` (the domain accepts mail, not that the mailbox exists), `no_mx`. |
| `jobs` | `[enrich] jobs` | Greenhouse, Lever and Ashby boards linked from the site, or guessed from the domain. A guessed board must prove it belongs to the company. Adds `jobs.open_roles` and a `hiring` signal. |
| `registry` | `[enrich] registry` | `rkn`: the RU personal-data operator registry by ИНН (`not_in_pd_registry` signal). `companies_house`: UK company profile and officers (needs the key), with `new_registration` and `company_inactive` signals. |

## Browser-assisted sources (no adapter)

Google Maps without a key, Google search, LinkedIn public pages, review sites and app stores have no adapter.
Their terms forbid automated collection, or they need a login. Use them by hand, at human pace, through the
Playwright MCP or Claude in Chrome, to verify and enrich specific leads. Never to build lists. Never log in to
scrape, and never solve captchas. For bulk Maps data, use `google_places` or the `leadgen-apify` plugin, and import
the result with the `file` adapter.

## Adding a source

Use the `parser-builder` skill. It qualifies the source first (terms, login, captcha, a better official route),
then finds the data path, writes `parse()` against synthetic fixtures, tests offline, runs a small live check,
and registers the adapter.

- **Workspace adapter** (default): `<workspace>/leadgen_sources/<name>.py`, for one-off or personal sources. It is
  code from the workspace, so it loads only when a campaign's `[[sources]]` names it, and every load is logged with
  its path. Built-in names win.
- **Built in**: `leadgen/sources/<name>.py` plus an entry in `MODULES`, only for sources useful to most users, via a
  PR with synthetic fixtures and tests.

[`templates/source.py`](../templates/source.py) is a working starting point. The contract is in the docstring
of `leadgen/sources/__init__.py`.
