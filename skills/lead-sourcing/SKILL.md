---
name: lead-sourcing
description: Chooses and configures lead sources by geography and business type - OSM, Google Places, Companies House, HN hiring, 2GIS, Yandex Maps, file imports, Kwork sellers - writes [[sources]] blocks in campaign.toml, and covers browser-assisted sources (Google Maps, LinkedIn public pages, review sites) that have no adapter. Use when planning where leads come from, when a source returns too little, or when the user asks which sources cover a market.
---

# Choosing and running sources

`leadgen sources` lists every adapter with coverage and readiness (missing key, missing setup).

## Pick by geography

| Market | First choice (free) | Add when available | Notes |
|---|---|---|---|
| Anywhere | `osm` | `google_places` (key) | OSM coverage is uneven: good for EU cities, thin in places. Check `leadgen inspect` fill rates. |
| UK | `osm`, `companies_house` (free key) | `google_places` | Companies House gives new registrations (timing signal) and officers. |
| RU / CIS | `twogis` (`leadgen setup 2gis` + Chrome), `yandex_maps` | | 2GIS has the best contact coverage (TG/WA/VK). Yandex stops at captcha; re-run later. |
| Tech companies, any | `hn_hiring`, `file` (exports) | | Hiring signal included. Add `jobs = true` in `[enrich]` for ATS boards. |
| Your own list | `file` (CSV/JSONL) | | CRM exports, trade-show lists, Apify output. Column names are matched by alias. |
| Freelancers / suppliers (RU) | `kwork_gigs` | | Partners and competitors rather than buyers. |

Demand sources (`kwork`, `flru`, `pchel`, `workspace_ru`, `telegram`) collect orders, not leads. They belong
to niche research (the `niche-research` skill, `leadgen market`) and don't merge into `leads.jsonl`.

## Write `[[sources]]`

Examples are commented in `templates/campaign.toml`; each adapter's docstring lists its spec keys.

```toml
[[sources]]
type = "osm"
queries = ["dentist", "orthodontist"]     # presets, tag filters ("office=lawyer"), or name words
locations = ["Porto, Portugal"]
limit = 200
```

- One unit = one query × one location = one cached raw file, fetched once. Adding a query only fetches the new
  units. `--refresh` re-fetches.
- Start with one location and low limits, run `leadgen collect` + `leadgen inspect`, check fill rates
  (website, phone, email), then widen.
- Several sources for the same market are good: `merge` collapses the same business across sources by
  domain → phone → name + city, and the record gets richer.

## When a source is thin or blocked

- `BLOCKED`: the source answered with a captcha or 429. Stop. Re-run later (finished units are kept). Never
  lower delays or retry in a loop.
- Low fill rate for websites/emails: add a second source for the same market, or rely on the `site` crawl.
- `LAYOUT CHANGED`: the site changed. Fix the adapter with the `parser-builder` skill.
- The market's best directory has no adapter: use the `parser-builder` skill (qualify it first: ToS, login,
  captcha).

## Browser-assisted sources (no adapter)

Google Maps without a key, Google search, LinkedIn public company pages, review sites (Trustpilot, Yelp,
TripAdvisor) and app stores have no adapter, either because their terms forbid automated collection or because
they need a logged-in session. Use them **by hand, at human pace**, through the Playwright MCP or Claude in
Chrome, for **verification and enrichment of specific leads**, not bulk listing:

- Look up one company, read what's public, and record what you used: a note on the lead
  (`leadgen mark <slug> <id> <status> --note "..."`) or a dossier with URLs and dates.
- Never log in to scrape, never solve captchas, never page through results to build lists.
- For bulk Google Maps data, use `google_places` (official API) or the optional `leadgen-apify` plugin.

For a list a user already has from such a source, use the `file` adapter.
