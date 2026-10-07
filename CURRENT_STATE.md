# Current state — 2026-10-07

Build paused at the owner's request after milestone 6 (outreach) of [SPEC.md](SPEC.md) §11; the CLI is next. This file says what
exists, what was verified, and the exact next steps, so the next session can pick up without re-deriving anything.

## Done

| Milestone | State |
|---|---|
| 1. Spec + plugin scaffold | **Done.** `SPEC.md`; `.claude-plugin/plugin.json` (plugin `leadgen`) and `marketplace.json` (marketplace `claude-lead-gen`), both passing `claude plugin validate`. `.mcp.json` bundles Playwright MCP. `providers/{firecrawl,exa,brave,tavily,apify}` are opt-in plugins that ask for their key via `userConfig` (sensitive). Every npx package is pinned to an exact version. |
| 2. Core package | **Done.** `leadgen/core/`: `http.py` (per-host throttle, disk cache, `Blocked` on 429/captcha; TLS fallback is opt-in and used only by the crawler, never for keyed APIs), `schema.py` (domain/phone/email normalization, own-site test, social patterns, lead skeleton), `campaign.py` (workspace + campaign layout, TOML config with defaults, `Campaign.create` also gitignores campaign data), `store.py` (atomic JSONL, flat CSV export), `merge.py` (union-find dedup on domain → phone → name+city; keeps enrichment/score/status across re-merges). |
| 3. Sources | **Code done, mostly untested end to end.** `leadgen/sources/__init__.py` is the runner (one cached raw file per unit; skips collected units; `SNAPSHOT` sources refresh daily; `Blocked` stops a source). Adapters: `osm`, `google_places`*, `companies_house`*, `hn_hiring`, `file`, `yandex_maps`, `twogis`, `telegram`, `kwork`, `kwork_gigs`, `flru`, `pchel`, `workspace_ru` (* = needs API key). The RU adapters are ports of claude-kit collectors; `tools/parser-2gis-headless.patch` is copied over. |
| 4. Enrichment | **Done.** `enrich/site.py` (crawl: contacts, socials, legal ids, people, tech, site health, ATS job-board links), `enrich/tech.py` (~90 fingerprints), `enrich/dns.py` (MX/SPF/DMARC via DoH → mail provider, sending tools, `emails[].verified="mx"`, `no_mx`), `enrich/jobs.py` (Greenhouse/Lever/Ashby; guessed board tokens must prove ownership), `enrich/registry.py` (RKN by ИНН; Companies House profile + officers, keyed), `enrich/__init__.py` (thread-pool runner, per-step resume, checkpoints every 25 leads, `Blocked` turns a step off, `no_website` signal). Lead gets extra blocks `dns`, `jobs`, `registry` beyond §4.2. |
| 5. Scoring | **`leadgen/score.py` done** (ops over dotted paths, signal/tech/category, negative points, `disqualify`, tiers, formula). `export`/`run`/`status` wait for the CLI. |
| 6. Outreach | **Done.** `outreach/drafts.py` (store, validation: evidence `[{fact, source}]` required, deep links), `outreach/suppression.py`, `outreach/compliance.py` (profiles can-spam/gdpr/uk-pecr/casl/ru → required fields, footer; `ru` needs `ru_consent = true`), `outreach/send.py` (off/confirm/auto, batches with content hashes + 24 h expiry, caps, idempotent `sent.jsonl`, follow-ups after `followup_days`, threading headers, SMTP from env). |
| Templates | `templates/campaign.toml` (sources, enrich, scoring rules, tiers, outreach send modes) and `templates/brief.md`. |

### Verified so far
- `claude plugin validate` passes on the marketplace, the plugin, and all 5 provider plugins.
- All 13 adapters import; `ready()` reports missing keys or setup correctly.
- Live endpoints respond: Nominatim, Overpass (dentists in Lisbon came back), HN Algolia, Greenhouse, Ashby,
  Cloudflare DoH, Kwork, FL.ru, RKN registry, Yandex Maps (no captcha at the time), t.me/s.
- Smoke tests: merge collapses the same domain across sources; INN checksum; tech detection; a live crawl of
  a real site found WordPress/WooCommerce/GTM/CF7/CookieYes.
- Live (2026-10-07): MX/provider for real domains, Greenhouse/Ashby boards (and a common-token guess correctly rejected), RKN lookup, crawl through the SSRF-guarded opener.
- `python3 -m unittest`: 40 offline tests (http guard, store/CSV, crawl/dns/jobs/registry with fixtures, scoring, outreach send gating).
- **Not yet run end to end:** no adapter has been run through the runner into a campaign, because the CLI doesn't exist yet.

## Not started

1. **`leadgen/cli.py` + `bin/leadgen`** (on PATH when the plugin is enabled): `init, sources, collect, merge, enrich,
   score, export, run, status, drafts add/list/show, send [--dry-run] [--approve], suppress, mark <lead> <status>,
   doctor, setup 2gis, market` (market research: port claude-kit `normalize_orders.py`, `label_orders.py`,
   `clusters.py`, `segments.py`, `score.py` as generic, config-driven versions). `--json` everywhere. All the library
   functions it needs exist: `sources.run_source/load_raw`, `core.merge.merge`, `enrich.run`, `score.score_all`,
   `store.write_csv`, `outreach.drafts.Drafts`, `outreach.send.run`, `outreach.suppression.Suppression`.
2. **Skills** (`skills/*/SKILL.md`): lead-gen, icp-builder, lead-sourcing, company-research, contact-discovery,
   lead-scoring, outreach, niche-research (port claude-kit's, generalized), compliance.
3. **Agents** (`agents/`): company-researcher, lead-qualifier, outreach-writer, market-scanner, fact-checker.
4. **Commands** (`commands/`): new, run, research, niches, drafts, send, status, setup.
5. **Hooks** (`hooks/hooks.json` + script). Send gate decided: allow `--dry-run`; allow in `auto`; allow the
   confirm-mode preview (no `--approve`); **ask** for `--approve`; ask when the campaign/mode can't be read. Match
   `leadgen send`, `leadgen.cli send`, `bin/leadgen send`. PII guard on `git add` (-f, campaigns/, suppression.txt, *.leads.*).
6. **CI:** GitHub Actions running `python -m unittest` and `claude plugin validate`.
7. **Docs:** README (install, quickstart), `docs/architecture.md`, `configuration.md`, `sources.md`, `compliance.md`.
8. **Live smoke test:** one small OSM campaign end to end, then fix whatever breaks.

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
Run `python3 -m unittest`, then continue with "Not started" item 1. Commit and push after each item, to `main` (owner decision).
