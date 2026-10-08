---
description: Write outreach drafts for a campaign's qualified leads, fact-check them, and store them
argument-hint: <slug> [lead-id ...] [--min-tier B] [--step 2]
---

Write outreach drafts for: $ARGUMENTS

Follow the `outreach` skill. Nothing is sent here.

1. **Who**: the lead ids given, or the leads at or above `--min-tier` (default: `[outreach] min_tier`) with
   status `new`/`drafted` and a usable route: `leadgen export <slug> --min-tier B --has-email --json`, or read
   `leads.jsonl` for non-email channels. `--step 2` writes follow-ups for leads whose step 1 was sent.
2. **Write**: up to ~5 leads yourself. More than that: spawn `outreach-writer` agents of about 20 leads each,
   in parallel, each writing its batch to `campaigns/<slug>/outreach/batch-<n>.jsonl`.
3. **Fact-check**: run the `fact-checker` agent over each batch file. Cut or reword every claim it marks
   `unsupported` or `outdated`. Drop a draft whose hook fails.
4. **Store**: `leadgen drafts <slug> add <file>` for each batch. Validation is all-or-nothing, so fix and re-add
   on an error.
5. **Report**: drafts added per channel, leads skipped and why, drafts with no verified recipient, and how to
   review them (`leadgen drafts <slug> show <lead-id>`). Sending is a separate step: `/leadgen:send <slug>`.
