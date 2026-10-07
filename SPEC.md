# claude-lead-gen — specification

Status: v1 spec, written 2026-10-06 from the owner's answers. This file is the source of truth for scope;
change it first when scope changes.

## 1. Goal

Turn Claude Code into a lead-generation and business-research agent. Given an offer and a target market, it
finds businesses that fit, researches them, verifies facts, scores them, and writes personalized outreach,
with every claim traceable to collected data.

It generalizes [claude-kit](#9-origin) (a Russia-only niche-research workspace) into a market-agnostic toolkit
that ships as a Claude Code plugin.

## 2. Decisions (owner, 2026-10-06)

| Topic | Decision |
|---|---|
| Scope | **Generic, any market.** Niche- and country-agnostic. Sources are pluggable adapters: global sources plus the RU/CIS sources ported from claude-kit. |
| Packaging | **Plugin + marketplace.** The repo is a Claude Code marketplace (`.claude-plugin/marketplace.json`) with the `leadgen` plugin at its root. Install: `/plugin marketplace add PeacexF/claude-lead-gen` → `/plugin install leadgen@claude-lead-gen`. Dev: `claude --plugin-dir .` |
| Spend | **Free-first, paid optional.** Everything works with zero spend and no API keys. Paid/keyed services are opt-in: separate small plugins in the same marketplace, or env-var-gated CLI sources. |
| Reference code | **Port + generalize** claude-kit collectors into this MIT repo. Never copy claude-kit `data/`, lead lists, or niche cards. |
| Outreach | **Draft always, send configurable.** Every qualified lead gets a draft. Sending is a separate, gated step whose mode is set in config (`off` by default). |
| Output | **CSV + JSONL.** `leads.jsonl` is canonical; `leads.csv` is a flat export of it. |
| Git | Autonomous build; small commits pushed straight to `main`. |

## 3. Principles

1. **Evidence, not intuition.** Every fact about a lead or market carries a source (URL or file), a date, and
   where it was collected. Missing data is reported as missing, never filled in from model memory.
2. **Free by default.** Each workflow has a no-key path. Keyed providers improve coverage, not correctness.
3. **Polite collection.** Throttle every source, cache raw responses, never re-fetch what's cached, and stop on
   captcha or rate-limit walls instead of retrying hard. Don't scrape logged-in pages.
4. **Personal data stays local.** Campaign data is gitignored, and a hook blocks force-adding it.
5. **A human controls sending.** Drafts are free to make. Sending follows the configured mode, a suppression list,
   and daily caps. Claude never sends anything just because it inferred it should.
6. **Stdlib Python.** The CLI runs on Python ≥ 3.11 with the standard library alone. Optional extras (2GIS parser,
   browser) are installed by explicit setup commands.

## 4. Architecture

```
claude-lead-gen/                      (marketplace root = leadgen plugin root)
├── .claude-plugin/
│   ├── marketplace.json              lists leadgen + optional provider plugins
│   └── plugin.json                   leadgen manifest
├── skills/                           workflow knowledge (see §5)
├── commands/                         thin slash-command entry points
├── agents/                           subagents for parallel research / writing
├── hooks/hooks.json                  guards (send gating, PII-in-git)
├── .mcp.json                         free MCP servers bundled with leadgen
├── bin/leadgen                       CLI entry point (on the Bash PATH when the plugin is enabled)
├── leadgen/                          Python package behind the CLI
│   ├── core/                         http (throttle + cache), config, campaign, schema, storage, dedup
│   ├── sources/                      one module per source adapter
│   ├── enrich/                       site crawl, tech stack, DNS/email checks, registry lookups
│   ├── score.py                      transparent, config-driven scoring
│   ├── outreach/                     draft storage, suppression list, gated senders
│   └── cli.py
├── providers/                        optional keyed MCP plugins (one directory each)
├── templates/                        campaign.toml, brief.md, outreach templates
├── tools/                            parser-2gis setup script + patch
├── tests/                            unittest suite with HTML/JSON fixtures
└── docs/                             architecture, configuration, sources, compliance
```

### 4.1 Campaign workspace (created in the user's project, not in the plugin)

```
campaigns/<slug>/
├── brief.md            ICP, offer, geography, constraints, decisions log
├── campaign.toml       sources + queries + locations, enrichment, scoring weights, outreach settings
├── raw/<source>/<date>/…   raw snapshots (cached, never refetched)
├── leads.jsonl         canonical merged + enriched + scored leads
├── leads.csv           flat export
├── dossiers/<lead-id>.md   deep research per company (optional)
├── outreach/drafts.jsonl   one draft per lead × step
├── outreach/sent.jsonl     send log (idempotency)
└── reports/            run summaries, market/niche cards
suppression.txt          global do-not-contact list (emails, domains, phones), shared across campaigns
```

`campaigns/` and `suppression.txt` are gitignored. The workspace root is the current directory, or
`$LEADGEN_HOME` when set. The HTTP cache lives in `.leadgen-cache/`.

### 4.2 Lead record (`leads.jsonl`)

One JSON object per business, keyed by `id` (registrable domain when there is one, otherwise a hash of
normalized name + city + phone):

```
id, name, domain, website, country, city, address, lat, lon, categories[], segment,
phones[], emails[{value, source, type: generic|personal, verified: mx|smtp|none}],
socials{linkedin, facebook, instagram, x, youtube, tiktok, telegram, whatsapp, vk, max},
people[{name, role, source}],
legal{name, registry_ids{inn, ogrn, company_number, vat, cik, ...}},
rating, reviews,
site{reachable, https, builder, tech[], has_form, privacy_link, cookie_notice, copyright_year, mobile},
signals[{type, value, source, date}],     e.g. hiring, new_registration, outdated_site, no_website, funding
sources[{source, url, collected}],
score, score_breakdown{rule: points}, tier (A/B/C/D), notes, status (new|drafted|sent|replied|won|lost|suppressed)
```

### 4.3 CLI (`leadgen`)

| Command | Does |
|---|---|
| `leadgen init <slug>` | create a campaign from templates |
| `leadgen sources` | list source adapters, their coverage, and whether they're ready (keys, setup) |
| `leadgen collect <slug> [--source …]` | run the configured sources → `raw/` |
| `leadgen merge <slug>` | normalize + dedupe raw records → `leads.jsonl` |
| `leadgen enrich <slug> [--steps site,dns,registry]` | crawl sites, detect tech, check MX, registry lookups |
| `leadgen score <slug>` | apply scoring rules, print the formula and tier counts |
| `leadgen export <slug>` | write `leads.csv` (filters: tier, has-email, …) |
| `leadgen run <slug>` | collect → merge → enrich → score → export |
| `leadgen status <slug>` | counts per stage, tier, and outreach status |
| `leadgen drafts <slug> add/list/show` | store and inspect drafts that Claude writes |
| `leadgen send <slug> [--dry-run] [--approve <batch>]` | gated sending (see §7) |
| `leadgen suppress <value…>` | add to the suppression list |
| `leadgen doctor` | check Python, network, optional tools, keys, MCP setup |
| `leadgen market …` | demand scans (freelance orders, job posts) for niche research |

Every command is idempotent and resumable. Output is human-readable on stderr; `--json` prints
machine-readable results for Claude.

## 5. Claude Code components

### 5.1 Skills (`skills/<name>/SKILL.md`)

| Skill | Purpose |
|---|---|
| `lead-gen` | Orchestrator: brief → ICP → source plan → collect → merge → enrich → verify → score → drafts. Entry point for "find me leads for X". |
| `icp-builder` | Interview the user or infer an ICP from an offer: firmographics, geography, buying signals, exclusions. Writes `brief.md` + `campaign.toml`. |
| `lead-sourcing` | Source catalog and selection by geography and business type; how to run each source, including browser-only ones. |
| `company-research` | Deep, cited dossier on one company: site, registry, people, tech, hiring, news, reviews, social, competitors. |
| `contact-discovery` | Find decision makers and contact routes: team pages, public profiles, email patterns + MX check. Compliance-aware. |
| `lead-scoring` | Write and tune scoring rules and tiers; explain why each lead is ranked where it is. |
| `outreach` | Personalized drafts that use evidence hooks, sequences, channel choice, and send modes. |
| `niche-research` | Ported from claude-kit, generalized: demand × gap × reach scans, niche cards with evidence. |
| `compliance` | GDPR/PECR, CAN-SPAM, CASL, 152-ФЗ/38-ФЗ, source ToS; per-geo checklist that runs before outreach. |
| `parser-builder` | Guidebook for building a parser (source adapter) for one specific source: qualify it (ToS, login, captcha), find the data path, units and pagination, synthetic fixtures, offline tests, small live check, registration. Workspace adapters (`<workspace>/leadgen_sources/<name>.py`, loaded only when a campaign names them) for one-off sources; `LayoutChanged` makes a broken parser fail loudly. [Design](docs/plans/parser-builder-skill.md). |

### 5.2 Agents (`agents/`)

- `company-researcher`: builds one dossier; spawned in parallel for top-tier leads.
- `lead-qualifier`: checks a batch of leads against the ICP with fresh web checks and flags false positives.
- `outreach-writer`: writes drafts for a batch, one evidence hook per lead, no invented facts.
- `market-scanner`: runs a niche/demand scan and returns the numbers.
- `fact-checker`: verifies every claim in a dossier, draft, or niche card against its cited source.

### 5.3 Slash commands (`commands/`)

`/leadgen:new` · `/leadgen:run` · `/leadgen:research <company|url>` · `/leadgen:niches` ·
`/leadgen:drafts` · `/leadgen:send` · `/leadgen:status` · `/leadgen:setup`

### 5.4 Hooks (`hooks/hooks.json`)

- **Send gate** (PreToolUse/Bash): a `leadgen send` without `--dry-run` asks the user for permission unless the
  campaign's `send_mode = "auto"`.
- **PII guard** (PreToolUse/Bash): blocks `git add -f` and `git add` of `campaigns/`, `suppression.txt`, or `*.leads.*`.

### 5.5 MCP servers

Bundled with `leadgen` (free, no key): **Playwright** (`@playwright/mcp`), used for JS-heavy sites, maps UIs, and
screenshots. Claude's built-in WebSearch/WebFetch and the claude-in-chrome extension cover search and
logged-out browsing.

Optional provider plugins in the same marketplace, each asking for its key through `userConfig` (sensitive):

| Plugin | Server | Free tier |
|---|---|---|
| `leadgen-firecrawl` | `firecrawl-mcp` | yes (limited credits) |
| `leadgen-exa` | `exa-mcp-server` | yes (limited) |
| `leadgen-brave` | `@brave/brave-search-mcp-server` | yes (limited) |
| `leadgen-tavily` | `tavily-mcp` | yes (limited) |
| `leadgen-apify` | `@apify/actors-mcp-server` | yes (monthly credit); Google Maps / LinkedIn actors |

## 6. Sources

### 6.1 Global, no key
- **OpenStreetMap Overpass + Nominatim**: businesses by tag in any city or area (name, site, phone, email, address).
- **Company websites**: crawl the homepage plus contact/about/team/legal pages.
- **DNS over HTTPS**: MX/SPF lookup → email deliverability and mail provider (Google Workspace, Microsoft 365, …).
- **Hacker News (Algolia API)**: "Who is hiring" threads and keyword search → hiring signals and companies.
- **Public ATS boards** (Greenhouse, Lever, Ashby): open roles per company → hiring signals.
- **SEC EDGAR**: US public-company filings, company metadata (no key; contact UA required).
- **Telegram public channels** (`t.me/s/…`): posts, no account.

### 6.2 Global, keyed (optional, env var)
- **Google Places API** (`GOOGLE_PLACES_API_KEY`): Maps businesses with ratings.
- **UK Companies House** (`COMPANIES_HOUSE_API_KEY`, free).
- **OpenCorporates** (`OPENCORPORATES_API_TOKEN`).
- **Hunter.io** (`HUNTER_API_KEY`): domain email search and verification.

### 6.3 RU/CIS (ported from claude-kit)
2GIS (patched parser-2gis), Yandex Maps, Kwork projects and gigs, FL.ru, pchel.net, workspace.ru tenders,
RKN personal-data operator registry, and RU legal identifiers in the site crawl (ИНН with checksum, ОГРН).

### 6.4 Browser-assisted (no code adapter)
Google Maps, Google search, LinkedIn (public pages only, no logged-in scraping), review sites, and
app stores via the Playwright MCP or claude-in-chrome. Skills explain how and record findings into the lead file.

## 7. Outreach and sending

- **Drafting** always runs for qualified leads. Drafts live in `outreach/drafts.jsonl`
  (`lead_id, step, channel, to, subject, body, evidence[], status`).
- **Channels:** email can be sent by the CLI. Telegram, WhatsApp, LinkedIn, and phone are draft-only, with deep
  links for manual sending, because cold-messaging from personal accounts breaks those platforms' terms.
- **`[outreach] send_mode`** in `campaign.toml`:
  - `off` (default): no sending.
  - `confirm`: `leadgen send` prints a batch preview and a batch id. Nothing goes out until it's re-run with
    `--approve <id>`, and the hook asks the user before that call runs.
  - `auto`: sends within the caps without asking.
- **Guards for every mode:** suppression list, `daily_cap`, per-domain cap, `sent.jsonl` idempotency,
  `--dry-run`, and the unsubscribe or opt-out line and sender identity that the compliance profile requires.
- **Transport:** SMTP via env (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`).

## 8. Quality

- `python3 -m unittest` covers parsers (fixtures), dedup, scoring, email/ID extraction, INN checksum,
  the send-gate logic, and hook decisions.
- CI (GitHub Actions) runs the tests and `claude plugin validate .` when the CLI is available.
- Live smoke test before v1: one small campaign end to end on free sources.

## 9. Origin

Ported from the owner's private `claude-kit` workspace: its `niche-research` skill, collectors (2GIS, Yandex Maps,
Kwork, FL.ru, pchel, workspace.ru, Telegram, site crawl/check, RKN), and analysis (segments, scoring, merge).
claude-kit's rules carry over: data-first claims, breadth before depth, throttled sources with caching, and
leads kept out of git.

## 10. Non-goals (v1)

- Hosted service, UI, or database server (files are the database).
- Logged-in scraping of LinkedIn or other platforms; bypassing captchas.
- Automated sending on Telegram, WhatsApp, or LinkedIn.
- Buying or bundling third-party contact databases.

## 11. Milestones

1. Spec + plugin scaffold (manifests, marketplace, gitignore).
2. Core package: http cache/throttle, config, campaign, schema, storage, dedup.
3. Sources: global no-key, then the RU ports, then keyed sources.
4. Enrichment: site crawl, tech detection, DNS/MX, registries.
5. Scoring + export + `run`/`status`.
6. Outreach: drafts, suppression, gated SMTP sender.
7. Skills, agents, commands, hooks, MCP + provider plugins.
8. Tests + CI; docs (README, architecture, configuration, sources, compliance).
9. Live smoke test and fixes.
