# claude-lead-gen

A Claude Code plugin that turns Claude into a lead-generation and business-research agent. Tell it what you sell
and where. It builds the ideal customer profile, collects businesses from public sources, crawls their sites,
checks their email setup, scores them with rules you can read, researches the best ones, and writes outreach
drafts. Every claim in a draft is tied to a URL or a collected record.

- **Any market.** Sources are pluggable adapters: OpenStreetMap, Google Places, UK Companies House, Hacker News
  hiring threads, your own CSV, plus RU/CIS directories (2GIS, Yandex Maps) and freelance boards.
- **Free first.** Everything works with no API keys and no spend. Keys add sources. They don't change the method.
- **Evidence, not intuition.** Facts carry a source and a date. Missing data is reported as missing.
- **Personal data stays local.** Campaign data lives in your workspace, is gitignored, and a hook blocks
  committing it.
- **A human controls sending.** Drafts are always written. Sending is `off` by default, and in `confirm` mode you
  approve each batch.

Stdlib Python (≥ 3.11) behind a CLI, plus skills, agents, slash commands and hooks for Claude Code. MIT.

## Install

In Claude Code (2.1.275 or later):

```
/plugin install leadgen --marketplace PeacexF/claude-lead-gen
```

Or in two steps on any version:

```
/plugin marketplace add PeacexF/claude-lead-gen
/plugin install leadgen@claude-lead-gen
```

Then run `/leadgen:setup` to check Python, network and optional tools. The `leadgen` CLI is on Claude's PATH
while the plugin is enabled. The bundled Playwright MCP server (for JS-heavy pages and screenshots) needs
Node.js.

Optional keyed providers live in the same marketplace and ask for their key on install:
`leadgen-firecrawl`, `leadgen-exa`, `leadgen-brave`, `leadgen-tavily`, `leadgen-apify`.

## Quickstart

Open Claude Code in an empty folder. That folder becomes the workspace (or set `LEADGEN_HOME`).

```
/leadgen:new online booking for dental clinics in Porto
```

Claude asks what it can't infer, writes `campaigns/<slug>/brief.md` and `campaign.toml`, shows you the ICP as a
table (criterion → field it checks → scoring rule) and stops. After you say yes:

```
/leadgen:run dental-booking-porto        collect → merge → enrich → score → export
/leadgen:research <lead-id>              cited dossier on a lead
/leadgen:drafts dental-booking-porto     drafts for tier B and better, fact-checked
/leadgen:status dental-booking-porto     where the campaign stands
/leadgen:send dental-booking-porto       gated: compliance check, dry run, your approval
```

Or just ask: "find me 50 accounting firms in Manchester that are hiring". The `lead-gen` skill runs the same flow.

The result is `campaigns/<slug>/leads.csv` (flat export) and `leads.jsonl` (canonical records), dossiers in
`dossiers/`, and drafts in `outreach/drafts.jsonl`.

## What's inside

| Part | What it does |
|---|---|
| `leadgen` CLI | Fetching (throttled, cached), merging, site crawl, DNS/MX, job boards, registries, scoring, export, drafts store, gated SMTP sender. Every step is idempotent and resumable. `--json` on every command. |
| Skills | `lead-gen` (orchestrator), `icp-builder`, `lead-sourcing`, `lead-scoring`, `company-research`, `contact-discovery`, `outreach`, `compliance`, `parser-builder` (build an adapter for a new source). |
| Agents | `company-researcher`, `lead-qualifier`, `outreach-writer`, `fact-checker`, run in parallel on batches. |
| Commands | `/leadgen:new`, `run`, `research`, `drafts`, `send`, `status`, `setup`. |
| Hooks | Send gate (asks before an approved batch goes out) and PII guard (keeps campaign data out of git). |

## CLI

```
leadgen init <slug> --offer "..."      new campaign from templates
leadgen sources                        adapters, coverage, readiness
leadgen run <slug>                     collect → merge → enrich → score → export
leadgen collect | merge | enrich | score | export <slug>
leadgen inspect <slug>                 fill rate per field per source
leadgen status <slug>                  counts per stage, tier, outreach status
leadgen lead <slug> <id>               one lead record
leadgen mark <slug> <id> <status>      new|drafted|sent|replied|won|lost|suppressed
leadgen drafts <slug> add|list|show
leadgen send <slug> [--dry-run | --approve <batch>]
leadgen suppress <email|domain|phone>  global do-not-contact list
leadgen doctor | setup 2gis
```

Exit codes: 1 error, 2 usage, 3 send refused.

## Docs

- [Architecture](docs/architecture.md): data flow, files, the lead record, how Claude and the CLI split the work.
- [Configuration](docs/configuration.md): `campaign.toml` and environment variables.
- [Sources](docs/sources.md): every adapter, its spec keys and coverage; enrichment steps; building a new adapter.
- [Compliance and safety](docs/compliance.md): what the sender enforces, the send gate, and its threat model.
- [SPEC.md](SPEC.md): scope and decisions. [CURRENT_STATE.md](CURRENT_STATE.md): what's built and verified.

## Development

```sh
git clone https://github.com/PeacexF/claude-lead-gen && cd claude-lead-gen
python3 -m unittest                    # offline, stdlib only
claude --plugin-dir .                  # run Claude Code with the plugin from this checkout
claude plugin validate .
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md). Fixtures in tests are synthetic. Never commit
real lead data.

## License

MIT. Not legal advice: the compliance checks are a working minimum, and you're responsible for how you contact people.
