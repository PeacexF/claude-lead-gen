---
description: Show where a campaign stands - leads per stage and tier, drafts, sends, and the next step
argument-hint: [slug]
allowed-tools: Bash(leadgen status:*), Bash(leadgen doctor:*)
---

Report the status of campaign: $ARGUMENTS

1. If no slug was given, `leadgen doctor --json` lists the workspace's campaigns. Report on the only one, or
   briefly on each.
2. `leadgen status <slug> --json`.
3. Summarize in a few lines: raw rows per source, leads (with website / email / phone), enrichment coverage,
   tiers, lead statuses, drafts, sent today and in total, and `send_mode`.
4. Name the next step from the `lead-gen` skill's flow: no sources → `/leadgen:new`; raw but no leads or no
   scores → `/leadgen:run`; scored but unverified → `lead-qualifier` / `/leadgen:research`; qualified without
   drafts → `/leadgen:drafts`; drafts ready → `/leadgen:send`.

No personal data in the summary.
