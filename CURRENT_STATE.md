# Current state — 2026-10-12

Milestones 1–8 of [SPEC.md](SPEC.md) §11 are done, plus niche research. Milestone 9 (live smoke tests) is done for every free and free-key source; what's left needs paid keys or a real SMTP account. This file says what
exists, what was verified, and the exact next steps, so the next session can pick up without re-deriving anything.

## Done

| Milestone | State |
|---|---|
| 1. Spec + plugin scaffold | **Done.** `SPEC.md`; `.claude-plugin/plugin.json` (plugin `leadgen`) and `marketplace.json` (marketplace `claude-lead-gen`), both passing `claude plugin validate`. `.mcp.json` bundles Playwright MCP. `providers/{firecrawl,exa,brave,tavily,apify}` are opt-in plugins that ask for their key via `userConfig` (sensitive). Every npx package is pinned to an exact version. |
| 2. Core package | **Done.** `leadgen/core/`: `http.py` (per-host throttle, disk cache, `Blocked` on 429/captcha; TLS fallback is opt-in and used only by the crawler, never for keyed APIs), `schema.py` (domain/phone/email normalization, own-site test, social patterns, lead skeleton), `campaign.py` (workspace + campaign layout, TOML config with defaults, `Campaign.create` also gitignores campaign data), `store.py` (atomic JSONL, flat CSV export), `merge.py` (union-find dedup on domain → phone → name+city; keeps enrichment/score/status across re-merges). |
| 3. Sources | **Done; every free and free-key adapter run live.** `leadgen/sources/__init__.py` is the runner (one cached raw file per unit; skips collected units; `SNAPSHOT` sources refresh daily; `Blocked` stops a source). Adapters: `osm`, `google_places`*, `companies_house`*, `opencorporates`*, `sec_edgar`†, `hn_hiring`, `file`, `yandex_maps`, `twogis`, `telegram`, `kwork`, `kwork_gigs`, `flru`, `pchel`, `workspace_ru` (* = needs API key, † = needs `SEC_EDGAR_UA`, a name + contact email). The RU adapters are ports of claude-kit collectors. **2026-10-12:** `twogis` reads 2GIS's server-rendered state over plain HTTP (ported from pdn-lead): search pages (12 per page) + one firm page per organisation. parser-2gis, its patch and `leadgen setup 2gis` are gone (Chrome took over the screen). `sec_edgar`: EDGAR full-text search; Form D by default (just raised money: phone, executives, amounts, `funding` signal), funds skipped. `opencorporates`: company search by jurisdiction/industry/incorporation date. Data-source plan for other markets: [docs/plans/data-sources.md](docs/plans/data-sources.md). |
| 4. Enrichment | **Done.** `enrich/site.py` (crawl: contacts, socials, legal ids, people, tech, site health, ATS job-board links), `enrich/tech.py` (~90 fingerprints), `enrich/dns.py` (MX/SPF/DMARC via DoH → mail provider, sending tools, `emails[].verified="mx"`, `no_mx`), `enrich/jobs.py` (Greenhouse/Lever/Ashby; guessed board tokens must prove ownership), `enrich/registry.py` (RKN by ИНН; Companies House profile + officers, keyed; OpenCorporates profile + officers, keyed; a lookup runs only for leads with its identifier), `enrich/hunter.py` (2026-10-12: Hunter.io domain search → emails, people, pattern; credits, so only on leads scored into `hunter_tiers`; `run` does it after scoring and re-scores), `enrich/__init__.py` (thread-pool runner, per-step resume, checkpoints every 25 leads, `Blocked` turns a step off, `no_website` signal). Lead gets extra blocks `dns`, `jobs`, `registry`, `hunter` beyond §4.2. Site crawl: a broken certificate is `cert_ok = false` + `broken_ssl` (fixed 2026-10-12; before, such sites were recorded as unreachable). |
| 5. Scoring | **`leadgen/score.py` done** (ops over dotted paths, signal/tech/category, negative points, `disqualify`, tiers, formula). `export`/`run`/`status` wait for the CLI. |
| 6. Outreach | **Done.** `outreach/drafts.py` (store, validation: evidence `[{fact, source}]` required, deep links), `outreach/suppression.py`, `outreach/compliance.py` (profiles can-spam/gdpr/uk-pecr/casl/ru → required fields, footer; `ru` needs `ru_consent = true`), `outreach/send.py` (off/confirm/auto, batches with content hashes + 24 h expiry, caps, idempotent `sent.jsonl`, follow-ups after `followup_days`, threading headers, SMTP from env). |
| CLI | **Done (2026-10-08); `market` added 2026-10-09** (see Niche research). `leadgen lead <slug> <id>` prints one lead; `leadgen inspect` checks raw data. `leadgen/cli.py` + `bin/leadgen` (bash wrapper, resolves symlinks, needs Python ≥ 3.11, runs `python -P` so files in the workspace can't shadow modules) + `python -m leadgen`. Commands: `init, sources, collect, merge, enrich, score, export, run, status, mark, drafts add/list/show, send, suppress, doctor, market`; `--json` on every command (result on stdout, progress on stderr). Exit codes: 1 error, 2 usage, 3 send refused. `drafts add` moves leads new → drafted; `mark … suppressed` also adds the lead's domain (else its emails/phones) to `suppression.txt`. |
| parser-builder | **Done (2026-10-08).** `skills/parser-builder/SKILL.md` + `references/patterns.md`: guidebook for building a parser (source adapter) for one specific source. Core: workspace adapters (`<workspace>/leadgen_sources/<name>.py`; loaded only when the campaign's `[[sources]]` names them, never to list them; path logged on load), `sources.LayoutChanged` (unit fails loudly; two in a row stop the source; kwork/flru raise it), `leadgen inspect` (fill rate per field, samples, duplicate ids), `templates/source.py` (tested as a working adapter). Plan: `docs/plans/parser-builder-skill.md`. |
| Hooks | **Done (2026-10-08).** `hooks/hooks.json` → `hooks/guard.py` (PreToolUse/Bash). Send gate: **ask** on `leadgen send --approve` and when the campaign/send_mode can't be read; dry runs, confirm previews, `auto` and `off` pass through. PII guard: **deny** `git add` of `campaigns/`, `suppression.txt`, `*.leads.*`, `leadgen_sources/*_fixtures/`, and `git add -f` on broad paths. Never answers allow (a chained command could ride on it). Follows `cd` and `LEADGEN_HOME=` in the command. Hardened after review (2026-10-08): argparse abbreviations (`--appr`; the CLI now sets `allow_abbrev=False`), sends chained with other commands, `$(…)`/`sh -c`/`python -c` indirection (raw-text fallback), Bash writes to `campaign.toml`, case-insensitive paths, pathspec magic/globs and `--pathspec-from-file` with `-f`, ignore-rule edits in the same command; Edit/Write that set `send_mode = "auto"` or drop ignore entries ask. **Limit:** a guardrail, not a sandbox: Bash can always reach SMTP or git another way. |
| CI | **Done (2026-10-08).** `.github/workflows/ci.yml`: unittest + CLI smoke on Python 3.11–3.14; `claude plugin validate` (Claude Code pinned 2.1.293, no auth needed) on the marketplace, plugin, and providers. |
| Skills | **Done (2026-10-08).** `skills/`: lead-gen (orchestrator), icp-builder, lead-sourcing, lead-scoring, company-research, contact-discovery, outreach, compliance, parser-builder. They call the agents below by name. |
| Agents | **Done (2026-10-09).** `agents/`: company-researcher (one dossier → `dossiers/<id>.md`; Playwright tools listed by their plugin names `mcp__plugin_leadgen_playwright__*`), lead-qualifier (verdict table + `leadgen mark` commands), outreach-writer (JSONL batch file for `drafts add`), fact-checker (per-claim verdicts, read only). Model `claude-haiku-5-5` at effort `high` (2026-10-10), tools restricted per agent. They load as `leadgen:<name>` (checked with `claude -p --plugin-dir .`). **Shared-file rule:** agents never run CLI commands that rewrite `leads.jsonl`/`drafts.jsonl`/`suppression.txt` They return the commands and the main session reviews and runs them (also stated in the lead-gen and outreach skills). |
| Campaign lock | **Done (2026-10-09).** `campaign.lock(dir)`: `fcntl.flock` on `campaigns/<slug>/.lock`, held by every command that rewrites campaign files (`collect, merge, enrich, score, run, mark, send, drafts add`; `cli.WRITERS`). A second writer prints "waiting for another leadgen command…" and blocks; readers (`status, lead, export, inspect, drafts list/show`) don't lock (writes are atomic renames). No-op on Windows (no `fcntl`). Test: `tests/test_cli.py` (fails with locking off). |
| Commands | **Done (2026-10-09).** `commands/`: `/leadgen:new` (init + ICP + source plan, stops for a yes before collecting), `run`, `research` (dossier; parallel `company-researcher` agents for several), `drafts` (writers → fact-checker → `drafts add`), `send` (`disable-model-invocation: true`: only the user starts it; compliance checklist → dry run → by `send_mode`, approval per batch), `status` and `setup` (pre-allow only `leadgen status/doctor/sources`). Thin entry points into the skills. Checked live: `claude -p --plugin-dir . "/leadgen:status demo"` in a temp workspace ran the plugin's `leadgen` from PATH. `/leadgen:niches` added with niche research. |
| Docs | **Done (2026-10-09).** `README.md` (install, quickstart, CLI, development), `docs/architecture.md` (data flow, workspace layout, lead record, idempotency and the lock, Claude components), `docs/configuration.md` (every `campaign.toml` key with defaults, env vars), `docs/sources.md` (every adapter with spec keys, enrichment steps, browser-assisted sources, adding a source), `docs/compliance.md` (profiles, guards, send modes, the hook's threat model and the hard-guarantee setup). Checked against the code while writing; fixed the `lead-scoring` skill's `jobs.open` path to `jobs.open_roles` (the field `enrich/jobs.py` writes). |
| Niche research | **Done (2026-10-09).** Ported from claude-kit (`normalize_orders`, `label_orders`, `clusters`, `segments`, `score`) and generalized. `leadgen/market.py` + `leadgen market <slug> scan\|orders\|terms`: demand rows from every `KIND = "demand"` source across all snapshot dates, once per id (latest wins, `first_seen` kept), `max_age_days` / `exclude_types` filters; product types by keyword rules (16 built in, RU + EN, `[[market.products]]` tried first); budgets in one currency with `[market] rates` (others left out and counted), vacancy salaries never count; `[[market.clusters]]` with every URL; supply per lead segment and city (no own site, social only, TG/WA/MAX, email, site issues of crawled sites, `gap_pct`, rating, reviews, top tech); `[[market.segments]]` scored as weighted, max-normalized demand × gap × reach (− competition), control rows unranked, formula printed. Output `campaigns/<slug>/market/`. `leadgen init --niches` uses `templates/niches.toml` + `templates/niches-brief.md`. Skill `niche-research` (study → sources → demand scan → clusters → supply → score → hypothesis rounds → deep dive → cards in `reports/niches/` → fact-checker → hand-off to `/leadgen:new`), agent `market-scanner` (1–3 hypotheses: matched vs real orders, budgets, offers, supply, existing products, keep/drop; read only except `reports/scans/`), command `/leadgen:niches`. `telegram` now records the currency of a stated budget. After the first live study (2026-10-09): `kwork` rows carry `buyer`/`buyer_wants`; stats count `distinct` (different text, so reposts count once) and `buyers` (distinct posters); segment scores use distinct orders; a client-acquisition intent rule comes before the product keywords. Tests: `tests/test_market.py`. |
| Templates | `templates/campaign.toml` (sources, enrich, scoring rules, tiers, outreach send modes) and `templates/brief.md`; `templates/niches.toml` and `templates/niches-brief.md` for niche studies. |

### Verified so far
- `claude plugin validate` passes on the marketplace, the plugin, and all 5 provider plugins.
- All 13 adapters import; `ready()` reports missing keys or setup correctly.
- Live endpoints respond: Nominatim, Overpass (dentists in Lisbon came back), HN Algolia, Greenhouse, Ashby,
  Cloudflare DoH, Kwork, FL.ru, RKN registry, Yandex Maps (no captcha at the time), t.me/s.
- Smoke tests: merge collapses the same domain across sources; INN checksum; tech detection; a live crawl of
  a real site found WordPress/WooCommerce/GTM/CF7/CookieYes.
- Live (2026-10-07): MX/provider for real domains, Greenhouse/Ashby boards (and a common-token guess correctly rejected), RKN lookup, crawl through the SSRF-guarded opener.
- `python3 -m unittest`: 97 offline tests (72 until 2026-10-09) (CI runs them on Python 3.11–3.14) (http guard, store/CSV, crawl/dns/jobs/registry with fixtures, scoring, outreach send gating,
  merge, CLI end to end on the `file` source, workspace adapters, LayoutChanged, the source template, hook decisions, market tables).
- **Live end to end (2026-10-08):** `bin/leadgen run` on OSM dentists in Coimbra (limit 10): 10 leads, 5 sites crawled, MX checked,
  tiers A3/C4/D3, CSV exported; re-run fully cached (0.1 s, 0 leads re-enriched). Drafts/send not run live (no SMTP).
- **Live `jobs` step (2026-10-09):** `hn_hiring` (python, remote, last thread: 32 posts) → site + jobs on all 32: 9 leads with open roles
  from Greenhouse/Lever/Ashby, 0 errors. The run exposed and fixed: `hn_hiring` took any linked URL as the company site (a
  mercurynews.com article became a lead's domain, which is the merge key); now only a headline link or a host that looks like
  the company counts, ATS hosts never do, `careers.`/`jobs.` subdomains give the company domain, and ATS links in the post
  become `job_boards` (found_via `source`). Leads without a domain no longer get name-guessed boards (the name check was
  circular). Leads with a domain went from 7 to 21 of 32.
- **Live RU + registry (2026-10-09):** `yandex_maps` (стоматология, kazan, 1 page): 25 rows → 22 leads, no captcha; site 21/22,
  MX on 16, ИНН on 9, RKN lookups 9 (8 registered, 1 `not_in_pd_registry`). Fixed: the crawl took the first legal name on
  the page, which was the bank in the requisites ("АО РАЙФФАЙЗЕНБАНК"); bank names are now skipped, and the registry's
  name for the ИНН / company number replaces a crawled one (RKN and Companies House).
- **Live send path (2026-10-09), local SMTP sink, nothing left the machine:** `file` source → drafts → `send --dry-run` →
  confirm preview → `--approve` over STARTTLS with certificate verification + AUTH (sink on 127.0.0.1 with a throwaway
  cert via `SSL_CERT_FILE`). Messages carry the can-spam footer and `List-Unsubscribe`; re-approving the batch is refused;
  lead/draft status → sent; `per_domain_cap` held back a same-day follow-up; with the cap raised, step 2 went out with
  `In-Reply-To`/`References` = step 1's `Message-ID`. There's no plain-SMTP mode (TLS is always required), by design.
- **Live niche research CLI (2026-10-09):** `init --niches`, `collect` on kwork (4 pages, 48 orders), flru (3, 90) and pchel
  (3, 150), `yandex_maps` стоматология + автосервис in Kazan (1 page each, 46 leads, 39 sites crawled), then `market scan`:
  product table, clusters, supply per segment and scores. The run exposed and fixed: pchel budgets are all USD, so the
  "most common currency" became USD and RUB orders dropped out of the stats (now `[market] rates` converts, and the scan
  counts budgets it left out); product rules missed transliterations ("андройд айос"), Bitrix24 shorthand ("б24"),
  ZennoPoster and web-app work (added, plus a `web_app` type). A loose test cluster regex ("амо") matched inside
  unrelated words, hence the skill's "read before you count" rule. Plugin load checked with `claude -p --plugin-dir .`:
  `leadgen:niche-research`, `leadgen:market-scanner`, `/leadgen:niches`.

- **Live 2026-10-12:**
  - Certificates: `expired`, `wrong.host`, `untrusted-root.badssl.com` → reachable, `cert_ok = false` (also from the
    cache on a re-run); `badssl.com`, `example.com` → `true`. A TLS handshake failure no longer counts as a broken cert.
  - `twogis` over plain HTTP (Kostroma, стоматология, limit 30): 30 rows in 34 s, no browser; 20 leads after merge,
    20 with a phone, 16 with an email after the crawl. 2GIS sends an old Chrome UA (130) to `/museum`; `UA_BROWSER` is
    now Chrome 154, and that redirect raises `LayoutChanged` naming the fix.
  - `companies_house` (SIC 62012, Manchester, incorporated since 2026-09-01, limit 20) + registry step: 20 leads, 20
    found, 20 with officers, `new_registration` on all; 80 s (registry delay 2 s × 2 calls per company).
  - `sec_edgar` (Form D, TX, 14 days, limit 15): 15 leads, all with a phone and a `funding` signal, 38 named people,
    no websites. The run added `+1` to bare US phones and the default skip of pooled investment funds (15 → 13).

## Not started

1. **Live smoke test:** done for every free and free-key source (see Verified). Still to run, each waiting on the owner:
   a send through a real provider's SMTP to an inbox the owner controls (skipped 2026-10-12 by the owner's choice);
   `opencorporates` (paid token) and the `hunter` step (`HUNTER_API_KEY`), both built from their API references and
   tested only on synthetic responses. Keys for live checks live in `~/.config/leadgen/live.env` (chmod 600, outside
   the repo); load it with `set -a; . ~/.config/leadgen/live.env; set +a`, and quote values that contain spaces.
2. **Niche research, live:** the first live study ran 2026-10-09 (demand only, one snapshot, stopped early with a
   verdict; the record is in the gitignored `private/runs/`). Still to run end to end: supply scan + segment scores,
   `market-scanner` rounds, a niche card with a fact-checker pass. Local research records go in `private/`
   (gitignored), never in tracked files. 2026-10-10: supply scan, round 2 and card 01 ran (see `private/runs/`).
   **2026-10-12: the owner dropped card 01** (confirmed-interest intros): too little income for the time spent
   (≈ 4–5 h of manual outreach per intro). No candidate is open. Rule for later rounds: work out income per hour of
   the seller's time early, and drop niches that need manual work per sale unless that figure is high.
3. **Demand outside RU/CIS:** only `telegram` is market-agnostic. The probed candidates and the order to build them are
   in [docs/plans/data-sources.md](docs/plans/data-sources.md): Freelancer.com's public project API first (budgets, bid
   counts, skills), then the HN freelancer thread, FR/NO/FI registries, UK tenders (OCDS) and EU TED.

## Security findings (fixed 2026-10-07)
1. **CSV formula injection** in `store.write_csv`: string cells starting with `= + - @ \t \r` get a `'` prefix
   (`store.csv_safe`). Test: `tests/test_store.py`.
2. **SSRF in the crawler**: `Fetcher(public_only=True)` or `request(..., public_only=True)` allows only http(s) to
   hosts whose every resolved address is global unicast, and re-checks each redirect target (`http.check_public`,
   `_PublicRedirects`). `site.fetch` always sets it. DNS rebinding between check and connect is accepted residual
   risk. Test: `tests/test_http.py`.

## Known issues / notes
- `.gitignore` has entries from the original template (`main`, `server`, `collector`, `context*`) that could
  shadow future paths with those names. Nothing uses them yet; review before adding such paths.
- `UA_BROWSER` (`core/http.py`) must name a current Chrome: 2GIS redirects outdated browsers to `/museum`. Bump it when
  `twogis` raises that `LayoutChanged`.
- `yandex_maps` would cache a captcha page like any page (only `twogis` drops walls from the cache via
  `Fetcher.forget`). Left as is by the owner's call (2026-10-12): Yandex hasn't served captchas in these runs.
- The registry step's 2 s delay is per Fetcher, so Companies House lookups take ~4 s per company (2 calls).
- Fixed 2026-10-08: re-merging dropped the `dns`/`jobs`/`registry` blocks and reset `emails[].verified`, so every
  `leadgen run` redid those lookups (`tests/test_merge.py`). Any new enrichment block must be added to the carry-over
  list in `merge.merge`.
- `site.people_from` is a heuristic. Treat its output as unverified until the contact-discovery skill checks it.
- `hn_hiring` takes the first `|` segment of a post as the company. Posts that open with the role ("Senior Python Backend | ...")
  give junk names. They have no domain, so they score low, but they're noise in the list.
- The crawl collects every ОГРН on a site's pages, so requisites that also list the bank's or a licensor's give several
  `legal.registry_ids.ogrn` values. The ИНН list has the same risk, but it was single-valued in the live run.
- SEC EDGAR needs a User-Agent with a name and contact email (`SEC_EDGAR_UA`); without one it answers 403. Form D
  filers rarely list a website, so EDGAR leads need the contact-discovery website steps before the crawl.

## Resume
```sh
cd claude-lead-gen
bin/leadgen doctor && bin/leadgen sources
```
Run `python3 -m unittest`, then continue with "Not started" item 3 (the `freelancer` demand adapter, per the data-source
plan) unless the owner provides keys for item 1. Commit and push after each item, to `main` (owner decision).
