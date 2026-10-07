---
name: lead-scoring
description: Writes and tunes transparent scoring rules and tiers in campaign.toml ([[scoring.rules]], [scoring.tiers]) and explains why each lead ranks where it does. Use when setting up scoring from an ICP, when the tier distribution looks wrong, or when the user asks why a lead is A or D.
---

# Scoring rules

Score = sum of the points of every rule a lead matches. The tier comes from thresholds. A `disqualify` rule
forces tier D. Rules live in `campaign.toml`. `leadgen score <slug>` applies them in under a second and
prints the formula, rule hits and tier counts. `leadgen.score` has the full reference in its docstring.

## Rule conditions (all in one rule must hold)

| Key | Meaning | Example |
|---|---|---|
| `has = "<path>"` | path has a non-empty value | `has = "emails"` |
| `missing = "<path>"` | path is empty | `missing = "website"` |
| `field` + `eq` `ne` `gte` `lte` `in` `contains` `matches` | compare a path | `field = "reviews"`, `gte = 20` |
| `signal = "<type>"` or a list | lead has that signal | `signal = ["hiring", "new_registration"]` |
| `tech = [..]` | `site.tech` contains any | `tech = ["wix", "tilda"]` |
| `category = "<regex>"` | over categories + segment | `category = "dent|ortho"` |
| `points = N` | may be negative | `points = -10` |
| `disqualify = true` | tier D regardless of score | ICP exclusions |

Paths are dotted and fan out through lists: `emails.verified` with `eq = "mx"` matches when any email has MX.
Useful paths: `site.reachable`, `site.https`, `site.builder`, `site.mobile`, `site.copyright_year`,
`dns.mail_provider`, `jobs.open`, `rating`, `reviews`, `city`, `legal.registry_ids.inn`, `status`.
Signal types from enrichment: `no_website`, `outdated_site`, `no_https`, `broken_ssl`, `not_mobile_friendly`,
`form_without_privacy_link`, `no_mx`, `hiring`, plus whatever sources add.

## From ICP to rules

1. **Reachability** (can we contact them at all): `has = "emails"` with MX verified, phone, Telegram. Roughly 20–30 points.
2. **Fit** (must-haves): category, size proxies (`reviews`), geography. Roughly 10 each.
3. **Signals** (need or timing): the offer-specific signal gets the most points (20–30); generic ones 5–10.
4. **Exclusions**: `disqualify = true` for chains or HQs (`matches` on name), competitors, out-of-area, `status`
   `lost`/`suppressed`.

Set tiers so that A = reachable + fit + the main signal, B = reachable + fit, C = fit without contact, and D
= everything else. Then check the counts: if A is more than ~15% of leads, the signal isn't selective enough.

## Tune by reading leads, not numbers

After `leadgen score <slug>`:
- Look at 5 A-tier and 5 D-tier leads (`leads.jsonl`, or `leadgen export --min-tier A` and open the CSV). For
  each, ask whether a human would rank it the same way. A wrong A usually means a missing exclusion. A wrong D
  usually means a data gap (the site wasn't crawled, a source lacks phones), not a bad rule.
- A rule with 0 hits is checking a path that's never filled. Check the path name in a lead.
- A rule that hits everything doesn't separate leads. Raise the bar or drop it.

## Explaining a score

Each lead carries `score_breakdown` (`rule name → points` or `"disqualified"`). Quote it with the facts behind
each rule (e.g. "reachable by email +20: info@… found on /contacts, MX ok"). Don't invent reasons beyond the breakdown.
