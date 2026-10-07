---
name: compliance
description: Per-market checklist for B2B prospecting and cold outreach - GDPR and UK PECR, US CAN-SPAM, Canada CASL, Russia 152-ФЗ and 38-ФЗ - plus source terms of service and data handling; sets the [outreach] compliance profile and sender fields that leadgen enforces. Use before any outreach or sending, when choosing channels for a market, or when the user asks whether a contact or message is allowed. Not legal advice.
---

# Compliance before outreach

This is a working checklist, **not legal advice**. When a case is unclear (sole traders, consumer-facing
addresses, sensitive sectors such as health), tell the user and suggest they ask a lawyer. Never tell them
something "is legal".

The sender enforces the mechanical minimum per profile (`leadgen/outreach/compliance.py`): it refuses to send
until the required sender fields are filled, and it appends an identity + opt-out footer to every email.
Judgment stays with the user.

## Set the profile

`campaign.toml`:

```toml
[outreach]
compliance = "gdpr"        # gdpr | uk-pecr | can-spam | casl | ru
sender_name = "..."
sender_company = "..."
sender_address = "..."     # postal address; required by CAN-SPAM and CASL
unsubscribe_text = "Not relevant? Reply 'no' and I won't write again."
```

Pick by **recipient** market, not by where the user is. With mixed markets, use the strictest that applies, or
split the campaign.

## Per market

| Profile | Cold B2B email | Must carry | Watch out for |
|---|---|---|---|
| `gdpr` (EU/EEA) | Possible under legitimate interest for relevant B2B offers; national e-privacy laws vary (some require consent even for B2B personal addresses) | identity, how you got the data, opt-out in every message | Personal addresses of named people are personal data: keep a legitimate-interest note, honor objections immediately, keep data minimal, answer access/deletion requests. |
| `uk-pecr` (UK) | To **corporate subscribers** (Ltd, PLC, LLP) without prior consent | identity, opt-out | Sole traders and partnerships count as individuals: they need prior consent. Check the legal form (`legal.name`, Companies House). |
| `can-spam` (US) | Allowed | accurate sender and subject, **physical postal address**, working opt-out honored within 10 business days | No deceptive subjects; opt-out has to keep working for 30 days. |
| `casl` (Canada) | Needs consent; **implied** only when the address is conspicuously published, not marked "no unsolicited email", and the message relates to the recipient's business role | identity, contact info, unsubscribe | Keep the source URL of each published address (it proves implied consent). |
| `ru` (Russia) | Promotional email needs **prior consent** (38-ФЗ ст.18), so cold promo email is out; the sender refuses unless `ru_consent = true` | identity, opt-out | 152-ФЗ governs storing and processing personal data of individuals (incl. ИП), and Roskomnadzor notification may apply to the user as an operator. Messenger outreach is draft-only and must follow platform rules. |

Everywhere: honor every opt-out immediately with `leadgen mark <slug> <id> suppressed` or `leadgen suppress
<email|domain|phone>`. The suppression list is global across campaigns.

## Channels

- **Email**: the only channel the CLI sends, within caps.
- **Telegram, WhatsApp, LinkedIn, phone/SMS**: draft-only, sent by a human. Platforms forbid automated cold
  messaging from personal accounts (spam bans, ToS). Use business accounts, low volume, and only where the
  business published that contact for inquiries.
- **Contact forms**: fill by hand, one message, no automation.

## Data handling (all markets)

- Campaign data stays local and out of git (`campaigns/`, `suppression.txt` are gitignored; the plugin hook blocks
  force-adding them).
- Collect what the offer needs, no more. Delete campaigns that are done, but keep `suppression.txt`.
- Record where each contact came from (`sources[].url`, `emails[].source`): it's the answer to "where did you get
  my address?".
- Respect source terms: logged-out pages only, polite rates, no captcha bypass (`parser-builder` qualifies each
  new source on this).

## Pre-send checklist

1. Profile set, and required sender fields filled (`leadgen send <slug> --dry-run` reports what's missing).
2. Market-specific checks done (PECR legal form, CASL published-address source, RU consent).
3. Drafts fact-checked: no unverifiable claims, no threats, honest subject lines.
4. Suppression list current; `daily_cap` and `per_domain_cap` sensible for a new sending domain (start at
   20–30/day).
5. The user has chosen `send_mode` themselves.
