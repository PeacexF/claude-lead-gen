---
name: outreach
description: Writes personalized outreach drafts built on one verified evidence hook per lead, stores them with `leadgen drafts`, plans follow-up sequences and channels, and runs the gated send flow (off / confirm / auto). Use when the user wants cold emails or messages written for leads, wants to review drafts, or asks to send.
---

# Outreach drafts and sending

Drafting is always allowed. Sending is a separate, gated step (see the end). Every draft cites its evidence, so a
reviewer or the `fact-checker` agent can verify each claim the message makes.

## Who gets a draft

Leads at or above `[outreach] min_tier` (default B) with status `new`/`drafted`, not suppressed, with a usable
route (`contact-discovery`). Get the list with `leadgen export <slug> --min-tier B --has-email` or from
`leads.jsonl`. For big batches, spawn `outreach-writer` agents (about 20 leads each), in parallel.

## Writing one message

- **One hook, from evidence**: the most specific verified observation about *this* business that connects to the
  offer ("your booking form at /contacts asks for a phone number but has no privacy notice", "you're hiring a
  second receptionist"). Take it from the dossier's outreach hooks or the lead's signals.
- **Structure**: hook (one line, factual) → why it matters to them (one line) → what you offer, concretely, with
  price or scope when the brief has it → one low-effort ask (a yes/no question, not "a 30-minute call").
- **Short**: about 60–120 words for email; Telegram/WhatsApp shorter. Subject: specific, plain, no clickbait,
  no "Re:" on a first message.
- **Language and register** from `[campaign] language` and the market. Use the recipient's name only if it came
  from a source.
- **Never**: invented facts, fake familiarity ("loved your recent post"), fear or legal threats ("you face a fine
  of..."), claims about results you can't prove, or tracking pixels.
- Compliance footer (identity, address, opt-out) is appended by the sender from `[outreach]`, so don't write it
  into the body. Draft-only channels get a short identity line in the body.

## Draft format and storing

```json
{"lead_id": "clinic.pt", "step": 1, "channel": "email", "to": "info@clinic.pt",
 "subject": "Booking form on clinic.pt", "body": "...",
 "evidence": [{"fact": "contact form collects phone, no privacy link", "source": "https://clinic.pt/contacts"}]}
```

```sh
leadgen drafts <slug> add drafts.jsonl          # or pipe JSON/JSONL on stdin; all-or-nothing validation
leadgen drafts <slug> list [--status draft]
leadgen drafts <slug> show <lead-id>            # body, evidence, and a deep link (mailto:, t.me, wa.me, tel:)
```

One `evidence` entry per claim about the lead. `channel` is one of email, telegram, whatsapp, linkedin, phone,
sms, contact_form; only email is sendable by the CLI. Re-adding the same lead/step/channel replaces the draft
unless it was already sent. Write the JSONL to the scratchpad or the campaign's `outreach/` dir, never to a
committed path.

## Sequences

Step 2 (and 3) are separate drafts with `"step": 2`. They go out only after the previous step was sent and
`followup_days` passed, are threaded as replies, and stop automatically when the lead's status becomes `replied`,
`won`, `lost` or `suppressed` (`leadgen mark`). A follow-up adds something new (a second observation, a short
example) rather than "just bumping this".

## Before sending: review

1. Run the `fact-checker` agent over the drafts. Fix or drop any claim it can't verify.
2. Check the `compliance` skill for the market: profile set, sender identity, address, opt-out text.
3. `leadgen send <slug> --dry-run` shows what would go out and why the rest is skipped.

## Sending (gated by `[outreach] send_mode`, which only the user changes)

- `off`: hand the user the drafts and deep links. Nothing is sent.
- `confirm`: `leadgen send <slug>` saves a preview batch and prints its id. Show the user the preview (recipients,
  subjects, counts). Only after they say yes, run `leadgen send <slug> --approve <id>` **as a command on its own**.
  The plugin hook asks them again. For the strongest guarantee, the user runs `--approve` in their own terminal
  with SMTP credentials kept out of this session.
- `auto`: sends within `daily_cap` and `per_domain_cap` without asking.

Never change `send_mode`, never approve a batch on the user's behalf, never send outside the CLI. When a reply
comes in, `leadgen mark <slug> <lead-id> replied` (or `won`/`lost`/`suppressed`).
