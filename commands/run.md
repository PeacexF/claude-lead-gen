---
description: Run a campaign's pipeline (collect, merge, enrich, score, export) and report the results
argument-hint: <slug> [--no-collect] [--source x] [--steps site,dns]
---

Run the lead-gen pipeline for: $ARGUMENTS

Follow step 3 of the `lead-gen` skill:

1. The first argument is the campaign slug. If it's missing, `leadgen doctor` lists the campaigns in the
   workspace. Use the only one, or ask which.
2. `leadgen status <slug> --json`: check that the campaign has `[[sources]]` and a brief. If not, run
   `/leadgen:new` first.
3. `leadgen run <slug> <remaining arguments>`. It can take minutes on a large campaign, and progress goes to
   stderr. Everything is cached and resumable, so a re-run continues where it stopped.
4. `leadgen inspect <slug>` for fill rates per source, and `leadgen status <slug> --json`.
5. If the tiers look wrong (A over ~15 %, a rule with 0 hits), tune with the `lead-scoring` skill and run
   `leadgen score <slug>` again. Scoring needs no network.

Report as the `lead-gen` skill says: counts, tier distribution, the top leads with their strongest signal,
blocked or thin sources (`BLOCKED` means re-run later, `LAYOUT CHANGED` means use the `parser-builder` skill),
and the path to `leads.csv`. Suggest the next step: verify the A/B leads (`lead-qualifier` agents), then
`/leadgen:research` and `/leadgen:drafts`. Don't paste personal data beyond what the user asks to see.
