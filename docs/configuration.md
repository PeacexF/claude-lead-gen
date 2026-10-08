# Configuration

Each campaign has one `campaigns/<slug>/campaign.toml`, created from [`templates/campaign.toml`](../templates/campaign.toml)
by `leadgen init`. Every section is optional. Missing keys take the defaults in `leadgen/core/campaign.py`
(`DEFAULTS`). The `icp-builder`, `lead-sourcing` and `lead-scoring` skills write most of it with you.

## `[campaign]`

| Key | Default | Meaning |
|---|---|---|
| `name` | slug | Display name. |
| `offer` | `""` | One line: what you sell and the outcome it gives. |
| `language` | `"en"` | Sent as `Accept-Language`, and the language of outreach drafts. |
| `country` | `""` | ISO code of the main market (`"PT"`, `"US"`, `"RU"`). |
| `default_phone_cc` | `""` | Calling code for local phone numbers, e.g. `"351"`. RU/KZ `8…` numbers are handled. |

## `[[sources]]`

One block per adapter run. `type` names the adapter, and the other keys are that adapter's spec. See
[sources.md](sources.md) for each adapter's keys.

```toml
[[sources]]
type = "osm"
queries = ["dentist", "orthodontist"]
locations = ["Porto, Portugal"]
limit = 200
```

A unit is one query × one location, stored as one raw file. Adding a query fetches only the new units.
`leadgen collect --refresh` re-fetches. A `type` that isn't built in loads `<workspace>/leadgen_sources/<type>.py`
(see the `parser-builder` skill).

## `[enrich]`

| Key | Default | Meaning |
|---|---|---|
| `site` | `true` | Crawl each lead's own website: contacts, socials, legal ids, people, tech, site health, ATS links. |
| `max_inner_pages` | `4` | Contact/about/team/legal pages per site, after the homepage. |
| `dns` | `true` | MX/SPF/DMARC over DNS-over-HTTPS: mail provider, `emails[].verified = "mx"`, `no_mx` signal. |
| `jobs` | `false` | Greenhouse/Lever/Ashby boards for the lead's domain: `jobs.open_roles` and a `hiring` signal. |
| `registry` | `[]` | `"rkn"` (RU, by ИНН, free) and `"companies_house"` (UK, needs a key). |
| `workers` | `8` | Leads enriched in parallel. Per-host throttling still applies. |

`leadgen enrich <slug> --steps site,dns --only <id> --limit N --refresh` overrides these for one run.

## `[[scoring.rules]]` and `[scoring.tiers]`

Score = the sum of the points of every rule a lead matches. All conditions within one rule must hold.

| Key | Meaning | Example |
|---|---|---|
| `name` | Shown in `score_breakdown` | `"reachable by email"` |
| `has` / `missing` | Path is non-empty / empty | `has = "emails"` |
| `field` + `eq` `ne` `gte` `lte` `in` `contains` `matches` | Compare a path | `field = "reviews"`, `gte = 20` |
| `signal` | Lead has a signal of this type (or any of a list) | `signal = ["hiring", "new_registration"]` |
| `tech` | `site.tech` contains any | `tech = ["wix", "tilda"]` |
| `category` | Regex over categories + segment | `category = "dent\|ortho"` |
| `points` | May be negative | `points = 20` |
| `disqualify` | Forces tier D | `disqualify = true` |

Paths are dotted and fan out through lists. `field = "emails.verified"` with `eq = "mx"` matches when any email
has MX. Useful paths: `site.reachable`, `site.https`, `site.builder`, `site.mobile`, `site.copyright_year`,
`dns.mail_provider`, `jobs.open_roles`, `rating`, `reviews`, `city`, `legal.registry_ids.inn`, `status`.

```toml
[scoring.tiers]     # minimum score per tier; below C is D
A = 60
B = 40
C = 20
```

`leadgen score <slug>` prints the formula, hits per rule, and tier counts, in under a second.

## `[outreach]`

| Key | Default | Meaning |
|---|---|---|
| `send_mode` | `"off"` | `off`: never send. `confirm`: preview a batch, then send it with `--approve <id>`. `auto`: send within caps. Only the user changes it. |
| `channels` | `["email"]` | Channels to draft for. Only `email` is sent by the CLI. `telegram`, `whatsapp`, `linkedin`, `phone`, `sms` and `contact_form` are draft-only, with deep links. |
| `min_tier` | `"B"` | Draft and send for this tier and better. |
| `daily_cap` | `30` | Emails per day for this campaign. Start at 20–30 on a new sending domain. |
| `per_domain_cap` | `1` | Emails per recipient domain per day. |
| `followup_days` | `4` | A step 2+ draft goes out only this many days after the previous step. |
| `send_delay` | `10` | Seconds between emails. |
| `compliance` | `""` | `gdpr`, `uk-pecr`, `can-spam`, `casl` or `ru`. Sending refuses until this is set. See [compliance.md](compliance.md). |
| `sender_name`, `sender_company`, `sender_address` | `""` | Identity in the footer. Which ones are required depends on the profile. |
| `unsubscribe_text` | `""` | Opt-out line in the footer, e.g. "Not relevant? Reply 'no' and I won't write again." |
| `ru_consent` | `false` | `ru` profile only: set to `true` only if every recipient gave prior consent (38-ФЗ ст.18). |

## `[http]`

| Key | Default | Meaning |
|---|---|---|
| `delay` | `1.0` | Default seconds between requests to the same host. Adapters set their own where a source needs it (Yandex Maps 4 s, Companies House 0.6 s). |
| `cache` | `true` | Cache responses in `<workspace>/.leadgen-cache/`. |

## Environment variables

| Variable | Used by |
|---|---|
| `LEADGEN_HOME` | Workspace root (default: the current directory). |
| `LEADGEN_TOOLS` | Where `leadgen setup 2gis` installs parser-2gis (default `~/.local/share/leadgen/tools`). |
| `GOOGLE_PLACES_API_KEY` | `google_places` source. |
| `COMPANIES_HOUSE_API_KEY` | `companies_house` source and registry step (free key). |
| `OPENCORPORATES_API_TOKEN`, `HUNTER_API_KEY` | Reported by `leadgen doctor`. No adapter uses them yet. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | The email sender. Port 465 uses implicit TLS, any other port STARTTLS. |

Set keys in your shell profile or in Claude Code's `env` settings, never in a file in a repo. For the strongest
send guarantee, keep the `SMTP_*` variables out of the Claude Code session entirely (see
[compliance.md](compliance.md#the-send-gate-and-its-limits)).
