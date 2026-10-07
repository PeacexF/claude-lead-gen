---
name: icp-builder
description: Builds the ideal customer profile and campaign brief for a lead-gen campaign - offer, firmographics, geography, observable buying signals, exclusions, decision maker, channels - and turns it into campaign.toml sources/scoring stubs. Use at the start of a campaign, when the user describes what they sell, or when lead quality is poor and the targeting needs rework.
---

# Building the ICP and brief

Output: a filled `campaigns/<slug>/brief.md` (template in `templates/brief.md`) and a `campaign.toml` whose
`[campaign]`, `[[sources]]` and `[[scoring.rules]]` follow from it. Every later step reads these files.

## Interview, briefly

Ask only what you can't infer from what the user said or from their site, and ask in one message:

1. **Offer**: what exactly is sold, the outcome for the buyer, price or deal size, and proof (cases, numbers).
2. **Who already bought** (best evidence there is): 2–3 past customers or the kind of business they are.
3. **Geography and language**: where they can sell and deliver; the language outreach will use.
4. **Exclusions**: segments they won't serve, competitors, existing clients, size limits.
5. **Channel constraints**: email allowed? Do they have a sending domain? Telegram/WhatsApp (draft-only)?

If the user gives a website, read it first (WebFetch) and propose answers for them to confirm.

## Turn it into observable criteria

An ICP is useful only when every criterion can be **checked in collected data**. Translate each into a field
the pipeline fills:

| ICP statement | Observable as | Where it comes from |
|---|---|---|
| "dental clinics" | `categories` / `segment` | source query (OSM preset, 2GIS rubric, Places type) |
| "in Lisbon and Porto" | `city` | source `locations` |
| "established" | `reviews >= 20`, `rating` | maps sources |
| "no online booking" | `site.tech` lacks booking vendors; or a custom adapter | site crawl / `parser-builder` |
| "outdated website" | `signals: outdated_site`, `site.builder`, `site.mobile` | site crawl |
| "growing" | `signals: hiring` | `jobs` step, `hn_hiring` |
| "new companies" | registration date | `companies_house` (UK), registries |
| "has someone to email" | `emails[].verified = mx` | crawl + `dns` step |
| "uses Google Workspace" | `dns.mail_provider` | `dns` step |

Criteria that can't be observed ("open to change", "has budget") go in the brief as notes, not as rules.
When a must-have needs data no source collects, say so, and suggest the `parser-builder` skill or a manual
check in the verification step.

## Buying signals

Write 2–5 signals: observable facts that suggest **need or timing**. A good signal is specific to the offer
("form collects phone numbers without a privacy link" for a compliance fix) rather than generic ("has a
website"). Each signal becomes a scoring rule with points, and the best one becomes the outreach hook.

## Write the files

- `brief.md`: all sections. Put the date and each decision in the decisions log.
- `campaign.toml`:
  - `[campaign]`: `country`, `language`, `default_phone_cc`.
  - `[[sources]]`: queries and locations from the segment and geography (see `lead-sourcing`). Use small limits for the first run.
  - `[[scoring.rules]]`: one rule per must-have (points), per signal (points), per exclusion (`disqualify = true`). See `lead-scoring`.
  - `[outreach]`: `compliance` profile for the market (see `compliance`). Leave `send_mode = "off"`.

Show the user the ICP table (criterion → observable field → rule) and get a yes before collecting.
