---
name: contact-discovery
description: Finds decision makers and the right contact route for a lead - team and about pages, registry officers, public profiles, email patterns checked against MX - and records them with sources, while respecting privacy rules (generic vs personal addresses, B2B legitimate interest, no guessed emails sent without a check). Use when a lead lacks a usable contact, when choosing who to write to, or before outreach to top-tier leads.
---

# Contact discovery

Goal: for each qualified lead, **one right person and one right channel**, each with a source. More contacts
aren't better: one well-chosen route beats five guessed addresses.

## What the pipeline already found

- `emails[]`: each has `type` (`generic` = info@/hello@..., `personal`) and `verified` (`mx` = the domain accepts
  mail, not that the mailbox exists). `dns.no_mx` means email to that domain will bounce.
- `phones[]`, `socials{}` (Telegram, WhatsApp, LinkedIn company page...).
- `people[]` from team/about pages. **Heuristic**: names and roles extracted by pattern. Treat as unverified
  until you've seen the page.
- `legal.registry_ids` → registry officers (`registry` step) for the legal decision maker.

## Find the decision maker

Use the ICP's decision-maker role (`brief.md`). In order:
1. The company's own site: team, about, imprint/legal notice (EU sites often name the managing director).
2. The official registry: directors and officers (Companies House, ЕГРЮЛ, national registries).
3. Public professional profiles and press: a logged-out search such as `"<company>" <role>` or
   `site:linkedin.com/in "<company>"`. Read the search snippet or the public page only. No logged-in scraping.
4. For small businesses (one location), the owner is usually the decision maker, and the generic inbox reaches them.

Record each person as `{name, role, source}` with the URL. If the role isn't stated on the source, write
"role unknown". Don't promote someone to "owner" from a guess.

## Choose the channel

| Situation | Route |
|---|---|
| Personal address published on the company's site for that person | email it |
| Only a generic inbox (info@) at a small business | the generic inbox, addressed to the role ("To the practice manager") |
| Generic inbox at a larger company | generic inbox, or the decision maker's published route; don't guess |
| Business messenger listed by the company (Telegram/WhatsApp Business) | a draft with a deep link; sent by hand |
| Only a phone | phone/SMS draft for a human, or skip |
| Contact form only | `contact_form` draft with the form URL |

## Email patterns: only when allowed and checked

Guessing `first.last@domain` is a last resort:
- Only for B2B where the compliance profile allows it (`compliance` skill). Under PECR/GDPR-style rules, a guessed
  personal address of an individual carries more risk than a published generic one. Under 38-ФЗ (RU) cold
  promotional email needs prior consent regardless.
- Infer the pattern from at least one **published** address at the same domain, not from a guess.
- `verified = "mx"` checks the domain only. Never mark a guessed address as verified, and never send to one
  without the user's explicit go-ahead.
- Note `type: personal, source: "pattern from <published address> (<url>)"`.

## Record it

Add what you found to the dossier (`company-research`) and to the draft's `to` field when writing outreach.
`leadgen mark <slug> <id> suppressed` when someone asks not to be contacted. That adds them to the global
suppression list, and the sender honors it in every campaign.
