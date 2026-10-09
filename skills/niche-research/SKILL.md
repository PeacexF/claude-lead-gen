---
name: niche-research
description: Data-driven search for niches where the user can make money selling a product or service to businesses. It measures what businesses already pay for (freelance orders, tenders, order channels), who could buy (business samples per segment and their digital gaps) and how crowded each niche is, then presents one evidence-backed niche card at a time, each with a product, price points and an implementation spec. Use when the user asks for business ideas or niches, "what can I sell / earn money with", what businesses will pay for, to continue a niche study, or to evaluate one niche idea.
---

# Niche research

Find several segments where the seller can make money, propose what to sell to each, and present each niche
as soon as it's ready. Keep going until the user stops on one. The `leadgen` CLI collects and counts. You read,
judge and write. The study lives in `campaigns/<slug>/`, like a lead campaign, so its data stays local and
gitignored.

## Hard rules

1. **Data only.** Every claim in a niche card cites collected data: number · source · date · file or URL. If you
   "just know" something about a market, it's a hypothesis to test, never evidence. Missing data → say "no data"
   and go collect it.
2. **Read before you count.** Product types and cluster regexes are keyword rules, and a match is not a buyer.
   Before a number goes into a card, read the orders behind it (`leadgen market <slug> orders ... --full`) and
   count the real buyer orders by hand. Vacancies, resellers, homework, spam, fake-review jobs and test posts
   don't count. Report both: "23 matched, 9 real buyer orders".
3. **Breadth before depth.** Scan every segment with cheap signals, then dig into the top ones. Pick segments
   from scan results, never by intuition.
4. **Kill early.** Check for an existing product before writing a spec. Most ideas die here: a vendor the buyers
   already use ships it, or a ready tool sells for less than a custom build. A dropped idea with its numbers is a
   result. Log it.
5. **Don't stop after one niche.** After presenting a card, continue with the next segment.
6. **Spend what the brief allows (default zero).** No paid APIs or tools without the user's yes.
7. **Polite collection.** The CLI throttles and caches. Never lower delays. Logged-out public pages only, no
   captcha solving.

## 0. Study and brief

```sh
leadgen status <slug> --json                                   # existing study?
leadgen init <slug> --niches --offer "<what the seller can build or sell>"
```

`--niches` writes `campaign.toml` with demand sources and a `[market]` section (all commented, see
`templates/niches.toml`) and a study `brief.md`. Fill the brief's **Seller** and **Market** sections, asking
what you can't infer in one message: skills and stack, product forms (custom build, template per client, ready
product, SaaS, service), sales channels, budget, who pays running costs, geography and language, exclusions.

The brief shapes the scoring. Reach depends on the channel, so set `[market.score] reach_metric` to match:
cold Telegram/WhatsApp → `messenger_pct`, cold email → `email_pct`, calls → `phone_pct`. Products the seller
can't build don't get shortlisted, however strong the demand.

## 1. Sources

**Demand** (what businesses pay for now). `leadgen sources` lists them as KIND `demand`:

| Market | Adapters | Notes |
|---|---|---|
| RU/CIS | `kwork`, `flru`, `pchel`, `workspace_ru` | Kwork has the cleanest data (category, offers, buyer hire rate). FL.ru mixes in vacancies and has relative dates only. pchel lists budgets in USD, has no dates and keeps old projects up. workspace.ru tenders come from businesses, so they double as warm leads. |
| Any | `telegram` (public channels) | Order channels for the market. Find them with WebSearch, check that `t.me/s/<name>` shows posts, and skip dead or vacancy-only channels. |
| Elsewhere | none built in yet | Build a demand adapter for a public order or tender board of that market with the `parser-builder` skill (`KIND = "demand"`, rows with `title, description, budget, budget_max, currency, category, offers, created, type`). Or read listings by hand at human pace and record counts with URLs in the findings log. Never log in to read. |

**Supply** (who could buy): `osm` (global), `yandex_maps` / `twogis` (RU/CIS), `google_places` (key). A sample
is enough: about 50 businesses per segment per city, in 2–3 cities of different sizes.

**By hand** (WebSearch, WebFetch, the browser): competitors and their prices, app marketplaces of the platforms
buyers already use (Bitrix24, amoCRM, Shopify, WordPress plugins), review complaints, small-product sale
listings, search trends. Each finding gets a URL and a date.

Write the `[[sources]]` blocks, show the plan, and collect after the user says yes.

## 2. Demand scan

```sh
leadgen collect <slug>                 # demand sources refresh daily; later runs add new orders
leadgen market <slug> scan             # tables -> campaigns/<slug>/market/
```

- **Currency.** Budget stats use one currency. With several in the data, set `[market] currency` and `rates`
  (`rates = {USD = 81}` means 1 USD = 81 of the main currency) and note the rate's source and date in the brief.
  Otherwise the scan reports how many budgets it left out.
- **Product types** come first: orders per type, budgets, median offers per order (competition). Note that
  `other` holds whatever no rule caught. Read it.
- For each product type the seller can deliver: `leadgen market <slug> terms --product <type>` for the common
  words, then `orders --product <type> --full --n 30` and read. Name **clusters**, each one *what is bought ×
  by whom* ("site form → CRM for clinics"), and add them as `[[market.clusters]]` with a regex over word stems
  (in TOML write `\\b` for `\b`, or use a single-quoted string). Check what each one catches with
  `orders --cluster <name>`, then re-scan. Iterate until the clusters explain most real orders in those product
  types.
- Per cluster, record real buyer orders, the median budget of those, median offers, and whether the buyers are
  businesses in an identifiable industry. Write findings to the brief's log as you go.
- **Reposts inflate counts.** One poster can put the same order up a dozen times under different titles and
  cities. The tables show `distinct` (orders with different text) next to `orders`, and `buyers*` where the
  source shows who posted (Kwork). Scores use distinct orders. Quote distinct orders and buyers in cards, not raw
  matches.
- **Offers are not comparable across sources.** FL.ru and pchel show fewer offers than Kwork, and fresh posts
  have fewer than old ones. Compare competition within one source.

Orders accumulate across days (`first_seen` / `last_seen` per order), so a study that collects for a week
measures demand better than one snapshot.

## 3. Supply scan

Take the buyer industries from the clusters, plus segments the brief names, and sample them:

```toml
[[sources]]
type = "yandex_maps"            # or osm, twogis
queries = ["стоматология", "автосервис"]
locations = ["kazan", "yaroslavl", "kostroma"]
pages = 2
```

```sh
leadgen run <slug>                     # collect -> merge -> crawl own sites (enrich site) -> leads.jsonl
leadgen market <slug> scan
```

The supply table per segment: no own site, social-only presence, Telegram/WhatsApp/MAX, email, site issues
among crawled sites (`[market] site_issues`), `gap_pct` (no own site, plus a broken site among the rest),
median rating and reviews, and the most common site tech. Per-city numbers are in `market/segments.json`. Add one
**control** segment with no order evidence, to see what the baseline looks like.

## 4. Score and shortlist

```toml
[[market.segments]]
name = "стоматология"           # matches leads whose segment equals this
demand = "стоматолог|клиник"    # regex over order text
# supply = "стомат|dent"        # optional regex over a lead's segment + categories
# product = ["crm_integration"] # optional: only orders of these product types count as demand
# control = true
```

`score = demand·distinct orders/max + gap·gap_metric/max + reach·reach_metric/max − competition·median_offers/max`, with
the weights in `[market.score]`. Set `gap_metric` to the gap the product removes: `no_own_site_pct` for sites,
`site_issue_pct` for fixes, `social_only_pct` for presence. Show the user the formula and the table, and say
when a segment's sample is small (n < 30 shares are rough). Shortlist 3–5.

**Hypothesis rounds.** For a list of concrete product ideas (H1…Hn: a product for a buyer), spawn
`market-scanner` agents in parallel, 2–3 hypotheses each, with the slug, the brief's seller line, and a demand
regex per hypothesis. Each returns matched vs real orders, budgets, offers, supply numbers, existing products
with prices, and a keep/drop call. Check their numbers before logging them. Agents only read: you run
`scan` and edit the config.

## 5. Deep dive (top segment first)

- **Competition.** Who sells it already, at what price, with what free tier, and what users complain about.
  Look in the app marketplaces of the platforms the buyers use, the vendors seen in the supply sample's
  `top_tech`, and WebSearch in the market's language. If a ready product covers the need for less than the
  build would cost the buyer, drop the idea and log the numbers.
- **Pain.** Buyer orders in their own words (quote one with its URL), reviews of the businesses or of competitor
  products.
- **Reach.** Leads in the sample, the source's own total for the segment and geography, the contact channels
  available, and the compliance profile that applies to the channel (the `compliance` skill).
- **Product.** The smallest thing that removes the measured gap, in a form the seller can deliver, with running
  costs paid by whoever the brief says.

## 6. Present a niche card

Save `campaigns/<slug>/reports/niches/NN-<slug>.md`, add a row to the brief's "Niches presented" table and a
line to the findings log. Run the `fact-checker` agent on the card and fix what it marks unsupported. Then show
the user a short summary with the path, and continue with the next segment.

```
# NN — <segment>: <product> (<market>)
## Evidence            every bullet: number · source · date · file or URL ("23 matched, 9 real" where counted)
## Product             what exactly is sold, its form (custom / template / SaaS / service), scope
## Buyer & price       who pays, price points seen in the data, proposed test price (labeled as untested)
## Reaching buyers     lead count, channels, outreach outline, compliance profile
## Competition & gap   existing products with prices and URLs, and what they leave open
## Implementation spec stack, components, data model, integrations, hosting and monthly cost for the client,
                       acceptance criteria, failure modes, what "done" means per client
## Unit economics      hours per delivery (an estimate, labeled as one), price, running cost
## Risks / unknowns    and the data that would resolve each
## Confidence          high / medium / low, and why
```

The implementation spec must be detailed enough to build with no further questions.

Rejected ideas go to the brief's "Dropped" table with the numbers that killed them. Don't re-propose a dropped
idea without new data.

## When the user picks a niche

Stop scanning. Run a realism check together: re-test the riskiest assumptions with fresh data (re-collect
demand, re-check competitors and prices). Then hand off to lead generation: `/leadgen:new <product> for
<segment> in <geography>`. The card's gap becomes the ICP's buying signal (`no_website`,
`form_without_privacy_link`, a tech fingerprint), and the supply queries become the campaign's sources. Ask
before contacting anyone. Outreach goes through the `outreach` and `compliance` skills and the send gate.

## Reporting

Keep it short: orders collected per source and the date range, the top product types and clusters with real
counts and budgets, the shortlisted segments with scores, cards presented, ideas dropped and why, and the next
step. Point to `campaigns/<slug>/market/` and `reports/niches/`.
