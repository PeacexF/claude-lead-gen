# Architecture

Two halves with one rule between them: **the CLI does the mechanical work, Claude does the judgment.** The `leadgen`
CLI fetches, caches, merges, crawls, scores, exports and sends, deterministically, with no model in the loop.
Claude, guided by the skills, decides who to target, which sources to use, whether a lead really fits, and what
to write. It reads and writes the same files the CLI does.

## Data flow

```
brief.md + campaign.toml          (icp-builder, lead-sourcing, lead-scoring skills)
        │
        ▼
leadgen collect   sources/*.py ──► raw/<source>/<date>/<unit>.jsonl     one cached file per unit
leadgen merge     core/merge.py ──► leads.jsonl                        dedupe, normalize
leadgen enrich    enrich/*.py   ──► leads.jsonl (site, dns, jobs, registry, signals)
leadgen score     score.py      ──► leads.jsonl (score, score_breakdown, tier)
leadgen export    core/store.py ──► leads.csv
        │
        ▼
verify            lead-qualifier agents, company-researcher agents ──► dossiers/<id>.md, leadgen mark
draft             outreach-writer agents ──► batch JSONL ──► fact-checker ──► leadgen drafts add ──► outreach/drafts.jsonl
send              leadgen send (off | confirm | auto) ──► outreach/sent.jsonl
```

`leadgen run` chains the first five steps.

## Workspace layout

The workspace is the current directory, or `$LEADGEN_HOME`. It's the user's folder, not the plugin's.

```
campaigns/<slug>/
├── brief.md              offer, ICP, signals, decision maker, channels, decisions log
├── campaign.toml         sources, enrichment, scoring, outreach (see configuration.md)
├── raw/<source>/<date>/  raw snapshots, one file per unit, never re-fetched without --refresh
├── leads.jsonl           canonical records
├── leads.csv             flat export (formula-injection safe)
├── dossiers/<id>.md      cited research per company
├── outreach/
│   ├── drafts.jsonl      one row per lead × step × channel
│   ├── batches/          confirm-mode previews (content-hashed, expire after 24 h)
│   └── sent.jsonl        send log; one send per draft, ever
├── reports/
└── .lock                 held while a command writes the campaign
suppression.txt           global do-not-contact list, shared by every campaign
.leadgen-cache/           HTTP response cache
leadgen_sources/          workspace source adapters (optional)
```

`leadgen init` appends `campaigns/`, `suppression.txt`, `.leadgen-cache/` and `leadgen_sources/*_fixtures/` to the
workspace `.gitignore`.

## The lead record

One JSON object per business in `leads.jsonl`. The `id` is the registrable domain when there is one, otherwise a
hash of normalized name + city + phone.

```
id, name, domain, website, country, city, address, lat, lon, categories[], segment,
phones[], emails[{value, source, type: generic|personal, verified: mx|none}],
socials{linkedin, facebook, instagram, x, youtube, tiktok, telegram, whatsapp, vk, max},
people[{name, role, source}], legal{name, registry_ids{inn, ogrn, company_number, vat, ...}},
rating, reviews,
site{reachable, https, builder, tech[], has_form, privacy_link, cookie_notice, copyright_year, mobile, ...},
dns{checked, mx, mail_provider, spf, dmarc, ...}, jobs{checked, open_roles, boards, ...}, registry{<name>: ...},
signals[{type, value, source, date}], sources[{source, url, collected}],
score, score_breakdown{rule: points}, tier, notes, status
```

`leadgen lead <slug> <id>` prints one in full.

## Core (`leadgen/core/`)

- **`http.py`**: one `Fetcher` per source with a per-host delay, a disk cache keyed by request, and `Blocked`
  raised on HTTP 429 or a captcha page. A blocked source stops for the run instead of retrying. The crawler sets
  `public_only`, which allows only http(s) to hosts whose every address is public, and re-checks each redirect
  (SSRF guard).
- **`schema.py`**: normalization of domains, phones (with the campaign's default country code), and emails,
  plus the own-site test, social URL patterns, and the lead skeleton.
- **`merge.py`**: union-find over raw rows on domain → phone → name + city. Fields are unioned, and the record
  keeps its sources. A re-merge keeps what later steps added (`site`, `dns`, `jobs`, `registry`, score, status,
  notes), so `leadgen run` never redoes enrichment. A new enrichment block must be added to the carry-over list in
  `merge.merge`.
- **`store.py`**: atomic JSONL writes (temp file + rename) and the CSV export. Cells starting with `= + - @` get a
  `'` prefix.
- **`campaign.py`**: workspace and campaign layout, `campaign.toml` with defaults, and the campaign lock.

## Idempotency and concurrency

Every command can be re-run. Collection skips units it already has. Enrichment skips leads that already have a
step's result, and checkpoints `leads.jsonl` every 25 leads, so an interrupted run resumes. Scoring and export
are pure functions of `leads.jsonl` and the config.

`leads.jsonl` and `drafts.jsonl` are read, changed and rewritten whole. Commands that write a campaign (`collect,
merge, enrich, score, run, mark, send, drafts add`) take an exclusive `flock` on `campaigns/<slug>/.lock`, so a
second writer waits instead of overwriting the first one's changes. Readers don't lock, because writes are atomic
renames. On Windows there's no `fcntl`, and commands run unlocked.

Agents add a second rule on top: they only read the shared files and return the `leadgen mark` / `drafts add`
commands, which the main session reviews and runs.

## Sources, enrichment, scoring, outreach

- **Sources** (`leadgen/sources/`): one module per adapter with a small contract (`units`, `collect_unit`,
  `parse`). See [sources.md](sources.md). `KIND = "demand"` sources (freelance orders, tenders) are for niche
  research and don't merge into leads.
- **Enrichment** (`leadgen/enrich/`): a thread pool over leads, with steps in order: site crawl → DNS/MX → job
  boards → registries. DNS checks the emails the crawl found, and job boards use the links it found. Each step
  adds signals (`no_website`, `outdated_site`, `no_https`, `form_without_privacy_link`, `no_mx`, `hiring`, ...).
- **Scoring** (`leadgen/score.py`): rules from `campaign.toml`, summed, with tiers from thresholds. Every lead
  carries its `score_breakdown`. No weights are learned or hidden.
- **Outreach** (`leadgen/outreach/`): the draft store validates that each draft cites evidence. The suppression
  list is global. Compliance profiles define required sender fields and the footer. The sender enforces
  `send_mode`, caps, suppression, follow-up timing and preview hashes. See [compliance.md](compliance.md).

## Claude Code components

| Component | Where | Role |
|---|---|---|
| Skills | `skills/<name>/SKILL.md` | Method: how to build an ICP, pick sources, write rules, research, find contacts, write outreach, check compliance, build a parser. `lead-gen` orchestrates. |
| Agents | `agents/<name>.md` | Parallel workers with restricted tools: `company-researcher` (one dossier), `lead-qualifier` (batch verdicts), `outreach-writer` (batch drafts to a file), `fact-checker` (per-claim verdicts, read only). Loaded as `leadgen:<name>`. |
| Commands | `commands/<name>.md` | `/leadgen:new`, `run`, `research`, `drafts`, `send`, `status`, `setup`. Thin entry points into the skills. Only the user can start `/leadgen:send`. |
| Hooks | `hooks/hooks.json` → `hooks/guard.py` | PreToolUse on Bash and Edit/Write: send gate and PII guard. See [compliance.md](compliance.md#the-send-gate-and-its-limits). |
| MCP | `.mcp.json` | Playwright (headless, isolated) for JS-heavy pages and screenshots. Keyed search and scraping providers are separate plugins in `providers/`. |
| CLI | `bin/leadgen` | Bash wrapper. Resolves symlinks, needs Python ≥ 3.11, and runs `python -P` so files in the workspace can't shadow the package. |
