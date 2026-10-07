---
name: company-research
description: Builds a deep, cited dossier on one company - website, legal entity and registry data, people, tech stack, hiring, news, reviews, social presence, competitors - with every fact tied to a URL and date. Use when the user asks to research a company or URL, before writing outreach to a top-tier lead, or when qualifying a lead needs more than the pipeline collected.
---

# Company dossier

Output: `campaigns/<slug>/dossiers/<lead-id>.md` when the company is a lead in a campaign. Otherwise answer in
chat, or write to a path the user names. For several companies at once, spawn one `company-researcher` agent per
company, in parallel.

## Rules

- **Every fact has a source and a date**: `fact — <url> (2026-10-08)`. Facts from the pipeline cite the lead
  record (`leads.jsonl: site.tech, crawled 2026-10-08`).
- **Missing is a finding.** Write "no public team page found (checked /about, /team, /contacts)" rather than
  leaving a gap or guessing.
- **Separate facts from inferences.** Inferences go in their own section and name the facts they rest on.
- **Public, logged-out sources only.** No logged-in LinkedIn, no paywalled databases, no captcha solving.

## Start from what's collected

```sh
leadgen lead <slug> <lead-id>          # the full record as JSON
```

The lead already holds the site crawl (`site.*`: pages, tech, builder, forms, copyright year), contacts,
socials, `legal.registry_ids` (INN/OGRN, VAT, company number), `dns` (mail provider), `jobs`, `registry`,
signals, and `sources[].url` (the directory listings). Don't re-collect what's there. Verify what matters.

## Sections

1. **Snapshot**: what they do, where, size proxies (locations, staff on the team page, reviews), legal entity.
2. **Legal and registry**: entity name and ids from the site footer or legal page. Look them up in the official
   registry (UK Companies House, RU ЕГРЮЛ/RKN, EU VAT VIES, US SEC EDGAR / state registries): status, incorporation
   date, officers and directors (public registry data only).
3. **People**: decision makers from the site team page, registry officers, and the press. See `contact-discovery`.
4. **Website and tech**: builder, stack, booking/forms/chat, mobile, HTTPS, copyright year, speed problems you
   can observe. Screenshots via the Playwright MCP when visual state matters.
5. **Activity and timing**: hiring (ATS boards, job posts), recent news, new locations, funding, registry
   changes, latest social posts (with dates).
6. **Reputation**: rating and review count per platform, and recurring themes in recent reviews. Quote short
   excerpts with links.
7. **Competitors and context**: 2–3 comparable businesses nearby or in the niche, and how this one differs
   (only observable differences).
8. **Fit for the offer**: which ICP criteria and buying signals hold, each with its evidence; what argues
   against; open questions.
9. **Outreach hooks**: 1–3 specific, verifiable observations a message could open with, each with its source.
   These feed the `outreach` skill.

## Tools

WebFetch for pages, WebSearch for news and mentions, the Playwright MCP for JS-heavy pages and screenshots,
`leadgen enrich <slug> --only <lead-id> --refresh` to re-crawl one lead. Keep requests polite: a dossier is
a few dozen page loads, not a crawl.
