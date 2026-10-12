# Plan: data sources beyond RU/CIS

Status: **plan, 2026-10-12.** Every source below was probed once that day with a plain request (browser
User-Agent, no cookies, no key unless noted). Nothing here is built yet except where marked. Each adapter gets built
with the `parser-builder` skill: qualify → data path → units → synthetic fixtures → offline tests → small live run.

## 1. Why

Niche research only works where there is demand data, and today only `telegram` is market-agnostic: `kwork`,
`flru`, `pchel` and `workspace_ru` are RU/CIS. Lead campaigns outside RU/CIS have `osm`, `google_places` (key),
`companies_house` (UK), `hn_hiring` (tech), and now `sec_edgar` (US) and `opencorporates` (paid). Two gaps:
1. **Demand** (what businesses pay for) in English-speaking and EU markets.
2. **Free company registries** per country, as sources (new registrations, industry codes) and as `registry`
   lookups that turn a crawled legal id into an official name, status and officers.

## 2. Demand sources (KIND = "demand")

| Source | Probe | What it gives | Verdict |
|---|---|---|---|
| **Freelancer.com** `api/projects/0.1/projects/active/` | 200 JSON, no auth | Per project: title, description, budget min/max with currency and exchange rate, `bid_stats` (count, average bid), skills (`jobs` with categories), `time_submitted`, type (fixed/hourly), language. Owner hidden. robots.txt doesn't disallow `/api`. | **Build first.** The closest global match to `kwork`: priced orders with competition counts. Query by words and skill ids, paginate with `offset`. |
| **HN "Freelancer? Seeking freelancer?"** (monthly, Algolia) | 200 | Posts from people and companies seeking freelancers, mostly tech. | **Cheap add-on:** a `thread` option on `hn_hiring` (same API, same parser) emitting demand rows. Low volume. |
| **UK Contracts Finder** OCDS search | 200 JSON, no key | Public tenders over £10–25k: title, description, value, buyer, CPV, dates, stage. | **Build as one OCDS adapter** with Find a Tender (below). Agency-scale budgets, like `workspace_ru`. |
| **UK Find a Tender** `api/1.0/ocdsReleasePackages` | 200 JSON, no key | High-value UK notices (OCDS 1.1.5). | Same OCDS adapter. |
| **EU TED** v3 `notices/search` (POST) | 200 JSON, no key | EU tenders: CPV filter in the query language, buyer, country, multilingual titles, links. | **Build second wave.** Public-sector demand for 27 countries. Query language needs its own spec keys. |
| **Prozorro** (UA) public API | 200 JSON, no key | Tender feed (ids), one request per tender for the content. | Later; one OCDS-style detail fetch per tender. |
| **RemoteOK** `api` | 200 JSON, attribution required | Remote job ads (vacancies). | Low value: vacancy salaries don't count as budgets in `leadgen market`. Skip unless hiring demand is the point. |
| **freelancermap.de** `/projekte` | 301 → `/projekte`, not read further | DE/AT/CH IT freelance projects. | Probe the list page next; possibly server-rendered HTML. |
| **SAM.gov** opportunities | 404 without a key | US federal opportunities. | Later, keyed (free key from api.data.gov). |
| Reddit r/forhire etc. | 403 (OAuth required) | — | Out: needs an app account. |
| Guru, Malt, Workana, PeoplePerHour | 403 / Cloudflare challenge / 202 empty | — | Out: bot walls. No captcha bypassing (SPEC §10). |
| Upwork | not probed | — | Out: its terms forbid scraping, and it retired its job RSS feeds in 2024 (from memory, not re-checked). |

Order fields stay as in `market.py` (`title, description, budget, budget_max, currency, category, offers,
created, type`). Freelancer's `bid_stats.bid_count` maps to `offers`. Its `currency.exchange_rate` lets the market
scan convert without `[market] rates`; keep the rate on the row.

## 3. Company registries (KIND = "businesses", plus registry lookups)

| Registry | Probe | What it gives | Verdict |
|---|---|---|---|
| **France**: recherche-entreprises.api.gouv.fr | 200 JSON, no key | SIREN, name, NAF code, address, establishments, directors, creation date. Filters: postcode, NAF activity, words. | **Build first** (source + `registry` lookup by SIREN). The crawl should also extract SIREN/SIRET. |
| **Norway**: data.brreg.no enhetsregisteret | 200 JSON, no key | Org number, NACE code, municipality, address, registration date, employees, sometimes a website (`hjemmeside`). | **Build first.** Filters by NACE + municipality fit the existing spec shape. |
| **Finland**: PRH YTJ v3 | 200 JSON, no key | Business id, names, registration date, main business line, addresses, sometimes a website. | Build with Norway (same shape). |
| **Czechia**: ARES (POST search) | 200 JSON, no key | IČO, name, address, NACE. | Second wave. |
| **GLEIF** LEI records | 400 on a city filter (wrong parameter name) | Legal entities with an LEI worldwide (mostly larger firms). | Low value for SMB leads; fix the filter only if needed. |
| Denmark CVR, Poland CEIDG, Australia ABN | not probed | — | Need an account or a free key; check terms first. |

Registries have no phones and rarely websites. Each registry-based campaign therefore relies on the website-finding
steps in `contact-discovery`, and new registrations are the main signal.

## 4. Built (#5 of the 2026-10-12 review)

- `sec_edgar` (US, no key, `SEC_EDGAR_UA`): Form D by default, so private companies that just raised money, with
  phone, executives and amounts. Live check pending (needs your contact User-Agent).
- `opencorporates` source + `registry` lookup (paid token): built from the API reference, tested on synthetic
  responses, not run live.
- `hunter` enrichment step (`HUNTER_API_KEY`): built from the API reference, tested on synthetic responses, not run
  live. Runs only on scored leads in `hunter_tiers`.

## 5. Order of work

1. `freelancer` demand adapter, then the `hn_hiring` freelancer thread. That gives niche research a global market.
2. `fr_entreprises` and `brreg` (NO) sources + registry lookups; the crawl extracts SIREN and Norwegian org numbers.
3. One `ocds` adapter for UK Contracts Finder and Find a Tender; then `ted`.
4. `ytj` (FI) and `ares` (CZ) if a campaign targets them.
5. Keyed later: SAM.gov.

Each one needs a small live run recorded in CURRENT_STATE.md, like the existing sources.
