# Current state — 2026-10-06

Build paused at the owner's request, partway through milestone 4 of [SPEC.md](SPEC.md) §11. This file says what
exists, what was verified, and the exact next steps, so the next session can pick up without re-deriving anything.

## Done

| Milestone | State |
|---|---|
| 1. Spec + plugin scaffold | **Done.** `SPEC.md`; `.claude-plugin/plugin.json` (plugin `leadgen`) and `marketplace.json` (marketplace `claude-lead-gen`), both passing `claude plugin validate`. `.mcp.json` bundles Playwright MCP. `providers/{firecrawl,exa,brave,tavily,apify}` are opt-in plugins that ask for their key via `userConfig` (sensitive). Every npx package is pinned to an exact version. |
| 2. Core package | **Done.** `leadgen/core/`: `http.py` (per-host throttle, disk cache, `Blocked` on 429/captcha; TLS fallback is opt-in and used only by the crawler, never for keyed APIs), `schema.py` (domain/phone/email normalization, own-site test, social patterns, lead skeleton), `campaign.py` (workspace + campaign layout, TOML config with defaults, `Campaign.create` also gitignores campaign data), `store.py` (atomic JSONL, flat CSV export), `merge.py` (union-find dedup on domain → phone → name+city; keeps enrichment/score/status across re-merges). |
| 3. Sources | **Code done, mostly untested end to end.** `leadgen/sources/__init__.py` is the runner (one cached raw file per unit; skips collected units; `SNAPSHOT` sources refresh daily; `Blocked` stops a source). Adapters: `osm`, `google_places`*, `companies_house`*, `hn_hiring`, `file`, `yandex_maps`, `twogis`, `telegram`, `kwork`, `kwork_gigs`, `flru`, `pchel`, `workspace_ru` (* = needs API key). The RU adapters are ports of claude-kit collectors; `tools/parser-2gis-headless.patch` is copied over. |
| 4. Enrichment | **Partly done.** `enrich/tech.py` (~90 fingerprints: CMS, ecommerce, analytics, chat, booking, CRM/forms, payments, consent) and `enrich/site.py` (crawl of homepage + contact/about/team/legal pages in many languages: emails, phones, socials, RU ИНН/ОГРН, UK company no., EU VAT, DE HR, legal names, best-effort people, site health; `apply()` folds results into a lead and adds signals such as outdated_site, no_https, broken_ssl). |
| Templates | `templates/campaign.toml` (sources, enrich, scoring rules, tiers, outreach send modes) and `templates/brief.md`. |

### Verified so far
- `claude plugin validate` passes on the marketplace, the plugin, and all 5 provider plugins.
- All 13 adapters import; `ready()` reports missing keys or setup correctly.
- Live endpoints respond: Nominatim, Overpass (dentists in Lisbon came back), HN Algolia, Greenhouse, Ashby,
  Cloudflare DoH, Kwork, FL.ru, RKN registry, Yandex Maps (no captcha at the time), t.me/s.
- Smoke tests: merge collapses the same domain across sources; INN checksum; tech detection; a live crawl of
  a real site found WordPress/WooCommerce/GTM/CF7/CookieYes.
- **Not yet run end to end:** no adapter has been run through the runner into a campaign, because the CLI doesn't exist yet.

## Not started

1. **Rest of enrichment:** `enrich/dns.py` (MX via DoH → `verified: "mx"`, mail provider), `enrich/jobs.py`
   (Greenhouse/Lever/Ashby by domain token → hiring signal), `enrich/registry.py` (RKN by ИНН, ported from claude-kit
   `rkn_registry.py`; Companies House profile), and an `enrich` runner that uses a thread pool (`enrich.workers`)
   and skips leads already checked.
2. **`leadgen/score.py`:** rule ops `has/missing/eq/ne/gte/lte/in/contains/matches/signal/tech/category` over dotted
   paths, tiers, and a printed formula (the template already documents the shape).
3. **`leadgen/outreach/`:** drafts store (`drafts.jsonl`), suppression list, SMTP sender with `send_mode`
   off|confirm|auto, batch preview + `--approve <id>`, daily and per-domain caps, `sent.jsonl` idempotency,
   compliance footer.
4. **`leadgen/cli.py` + `bin/leadgen`** (on PATH when the plugin is enabled): `init, sources, collect, merge, enrich,
   score, export, run, status, drafts, send, suppress, doctor, setup 2gis, orders/segments` (market research: port
   claude-kit `label_orders.py`, `clusters.py`, `segments.py`, `score.py` as generic, config-driven versions).
5. **Skills** (`skills/*/SKILL.md`): lead-gen, icp-builder, lead-sourcing, company-research, contact-discovery,
   lead-scoring, outreach, niche-research (port claude-kit's, generalized), compliance.
6. **Agents** (`agents/`): company-researcher, lead-qualifier, outreach-writer, market-scanner, fact-checker.
7. **Commands** (`commands/`): new, run, research, niches, drafts, send, status, setup.
8. **Hooks** (`hooks/hooks.json` + script): send gate (asks unless `send_mode="auto"`), and a PII guard on `git add`.
9. **Tests + CI:** `tests/` with HTML/JSON fixtures (synthetic, no real personal data), plus a GitHub Actions
   workflow running `python -m unittest` and `claude plugin validate`.
10. **Docs:** README (install, quickstart), `docs/architecture.md`, `configuration.md`, `sources.md`, `compliance.md`.
11. **Live smoke test:** one small OSM campaign end to end, then fix whatever breaks.

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
- `twogis` installs parser-2gis under `$LEADGEN_TOOLS` or `~/.local/share/leadgen/tools` (outside the plugin dir,
  so plugin updates don't wipe it). The `leadgen setup 2gis` command that does this is not written yet.
- `site.people_from` is a heuristic. Treat its output as unverified until the contact-discovery skill checks it.
- `osm.area_clause` returns a tuple but is annotated `-> str`. Cosmetic; fix it when touching the file.
- SEC EDGAR returned 403 without a contact User-Agent, so it was left out of v1 sources. It needs a UA with an email if added.

## Resume
```sh
cd claude-lead-gen
python3 -c "import leadgen.sources as s; [print(m.NAME, s.readiness(m)) for m in s.all_sources()]"
```
Then continue with "Not started" item 1. Commit and push after each item, to `main` (owner decision).
