---
description: Find niches to earn money in - demand scan, supply scan, scored shortlist, then evidence-backed niche cards one at a time
argument-hint: [what you can build or sell] [market] | <study-slug>
---

Niche research for: $ARGUMENTS

Follow the `niche-research` skill.

1. **Study**: if the argument names an existing study (`leadgen status <slug> --json` succeeds), read its
   `brief.md` and continue where the findings log stops. Otherwise pick a short slug from the market (e.g.
   `niches-ru-2026-10`) and run `leadgen init <slug> --niches --offer "<what the seller can build or sell>"`.
2. **Brief**: fill the Seller and Market sections. Ask what you can't infer in one message (skills, product
   forms, sales channels, budget, geography and language, exclusions).
3. **Source plan**: demand sources for the market, then a small supply sample per segment later. Write the
   `[[sources]]` blocks, check readiness with `leadgen sources`, show the plan, and **stop**. Collect only after
   the user says yes.
4. After the yes: `leadgen collect <slug>`, then `leadgen market <slug> scan`, and go on with the skill's steps 2–6
   (clusters, supply, scoring, `market-scanner` agents for hypothesis rounds, deep dive, niche cards). Present
   each card as soon as it's ready and keep going until the user picks a niche or stops.

If the arguments are empty, ask in one message what they can build or sell, for which market, and how they would
reach buyers.
