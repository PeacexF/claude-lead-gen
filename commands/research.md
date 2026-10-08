---
description: Build a cited dossier on one or more companies (names, URLs, or lead ids from a campaign)
argument-hint: <company | url | lead-id ...> [--campaign <slug>]
---

Research: $ARGUMENTS

Follow the `company-research` skill.

- **A campaign lead** (`--campaign <slug>`, or a lead id found in `campaigns/*/leads.jsonl`): start from
  `leadgen lead <slug> <lead-id>` and write the dossier to `campaigns/<slug>/dossiers/<lead-id>.md`.
- **A company outside any campaign**: research it and answer in chat, unless the user named a file.
- **Several companies**: spawn one `company-researcher` agent per company, in parallel, each with the slug, the
  lead id (or URL), and the offer and ICP in a line each from `brief.md`. Apply the `leadgen mark` actions they
  return yourself, after checking them.

Every fact has a source and a date, missing data is reported as missing, and only public, logged-out pages are
used. End with the fit for the offer and the outreach hooks.
