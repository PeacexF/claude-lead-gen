---
name: lead-gen
description: Orchestrates a lead-generation campaign end to end - brief and ICP, source plan, collect, merge, enrich, verify, score, export, outreach drafts, gated sending - with the leadgen CLI. Use when the user asks to "find leads/clients/customers for X", "build a prospect list", "who should I sell X to in <place>", or to continue/check an existing campaign.
---

# Lead generation, end to end

The `leadgen` CLI (on PATH while the plugin is enabled) does the mechanical work: fetching, caching, merging,
crawling, scoring, exporting and sending. You do the judgment: ICP, source choice, verification, writing. Every
fact you state about a business must come from collected data (a URL or file with a date). Data that's missing
is reported as missing, never filled in from memory.

Run commands with `--json` when you need to read the result; progress goes to stderr. Everything is idempotent:
re-running a step only does what's missing.

## 0. Find or create the campaign

```sh
leadgen status <slug> --json          # existing campaign: where is it?
leadgen init <slug> --offer "<one line>"
```

The workspace is the current directory (or `$LEADGEN_HOME`). The campaign lives in `campaigns/<slug>/` and is
gitignored, because it holds personal data. `leadgen doctor` checks the setup.

## 1. Brief and ICP: `icp-builder` skill

Fill `campaigns/<slug>/brief.md` (offer, ICP, buying signals, decision maker, channels, compliance) and the
`[campaign]` section of `campaign.toml`. Don't collect anything before the ICP has geography, segment, and
at least one observable buying signal. Without them, scoring has nothing to rank by.

## 2. Source plan: `lead-sourcing` skill

Choose sources by geography and business type (`leadgen sources` lists them with readiness), and write
`[[sources]]` blocks. Start small: one or two queries × one location, low limits. Widen once the first results
look right. If the best source for this niche isn't covered, build an adapter with the `parser-builder` skill.

## 3. Collect → merge → enrich → score → export

```sh
leadgen run <slug>                    # all five steps, using the config
leadgen inspect <slug>                # per-source fill rates: did the sources deliver what you expected?
leadgen status <slug>
```

Or step by step: `collect [--source x]`, `merge`, `enrich [--steps site,dns,jobs,registry] [--limit N]`,
`score`, `export [--min-tier B] [--has-email]`. A `BLOCKED` source stopped politely (captcha or rate limit).
Re-run later, and finished units are kept. `LAYOUT CHANGED` means the adapter's parser needs fixing
(`parser-builder`).

## 4. Score and tune: `lead-scoring` skill

Write `[[scoring.rules]]` from the ICP's must-haves, buying signals and exclusions, then run `leadgen score <slug>`.
Read the printed formula and rule hits. Open a few A-tier and D-tier leads and check that the ranking makes
sense. Tune, re-score. Scoring is instant and needs no network.

## 5. Verify the top of the list

Before anyone writes to a lead, check it:
- `lead-qualifier` agent: batches of A/B leads against the ICP with fresh checks; flags false positives
  (closed, chain HQ, wrong segment, already a customer of the offer).
- `company-research` skill / `company-researcher` agent: a cited dossier per top lead, written to
  `campaigns/<slug>/dossiers/<lead-id>.md`.
- `contact-discovery` skill: decision makers and the right channel.

Record outcomes with `leadgen mark <slug> <lead-id> <status> --note "..."` (`lost` for false positives,
`suppressed` for do-not-contact).

Agents run in parallel but only read the shared files (`leads.jsonl`, `drafts.jsonl`, `suppression.txt`): they
write their own outputs (dossiers, draft batches) and return the `leadgen mark` / `drafts add` commands. Review and
run those yourself. Commands that write a campaign take its lock, so a second writer waits for the first.

## 6. Drafts: `outreach` skill

One draft per qualified lead, built on one evidence hook, with every claim cited. Store drafts with
`leadgen drafts <slug> add` (validation is all-or-nothing). Run the `fact-checker` agent over drafts before
anything is sent.

## 7. Sending (gated)

Read the `compliance` skill first. `send_mode` in `campaign.toml` decides:
- `off` (default): nothing is sent. Hand the user `leadgen export` plus `leadgen drafts <slug> show <id>` deep links.
- `confirm`: `leadgen send <slug>` writes a preview batch and prints its id. Show the user the preview. Only after
  they approve, run `leadgen send <slug> --approve <id>` on its own line (the plugin hook asks them again).
- `auto`: sends within caps. Only the user switches to it. Never edit `send_mode` yourself.

Always `leadgen send <slug> --dry-run` first. Never send because it seems like the natural next step.

## Reporting back

Report counts from `leadgen status --json`, tier distribution, top leads with their evidence hooks, which
sources were blocked or thin, and what's left manual. Point to `campaigns/<slug>/leads.csv`. Don't paste
personal data (names, phones, emails) into chat beyond what the user asked to see.
