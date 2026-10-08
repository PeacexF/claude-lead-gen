# Compliance and safety

**Not legal advice.** leadgen enforces a mechanical minimum per market and keeps a human in control of sending.
Whether a given message to a given person is lawful is your call. When it's unclear (sole traders, consumer
addresses, regulated sectors such as health), ask a lawyer. The `compliance` skill is the working checklist Claude
follows before any outreach.

## What the sender enforces

`leadgen send` refuses to send until `[outreach] compliance` names a profile and that profile's required fields
are filled. It appends an identity and opt-out footer to every email.

| Profile | Market | Required fields | Also blocks |
|---|---|---|---|
| `can-spam` | US | `sender_name`, `sender_address`, `unsubscribe_text` | — |
| `gdpr` | EU/EEA | `sender_name`, `sender_company`, `unsubscribe_text` | — |
| `uk-pecr` | UK | `sender_name`, `sender_company`, `unsubscribe_text` | — |
| `casl` | Canada | `sender_name`, `sender_company`, `sender_address`, `unsubscribe_text` | — |
| `ru` | Russia | `sender_name`, `sender_company`, `unsubscribe_text` | Any send unless `ru_consent = true`. Cold promotional email needs prior consent (38-ФЗ ст.18). |

Choose by the **recipient's** market. With mixed markets, use the strictest profile, or split the campaign.

What the profile can't check, and you must:
- **UK PECR**: cold B2B email is allowed to corporate subscribers (Ltd, PLC, LLP). Sole traders and partnerships
  count as individuals and need prior consent. Check the legal form.
- **CASL**: consent is implied only for a conspicuously published address with no "no unsolicited email" note,
  and a message relevant to the recipient's business role. Keep the source URL (`emails[].source`).
- **GDPR**: a named person's address is personal data. Keep a legitimate-interest note, collect the minimum,
  and honor objections and access or deletion requests. Some national e-privacy laws require consent even for
  B2B.
- **152-ФЗ** (RU): storing personal data of individuals (including ИП) can make you an operator with
  notification duties.

## Guards in every send mode

Re-checked at send time, also for a batch that was already approved:

- **Suppression list** (`suppression.txt`, global): emails, domains (covering every address there) and phones.
  `leadgen mark <slug> <id> suppressed` adds the lead's domain, or else its emails and phones.
  `leadgen suppress <value>` adds anything.
- **Lead status**: `replied`, `won`, `lost` and `suppressed` stop a sequence.
- **`min_tier`**, **`daily_cap`**, and **`per_domain_cap`** (per recipient domain per day).
- **One send per draft, ever** (`sent.jsonl`, written after each message, so a crash never re-sends).
- **Follow-ups** only `followup_days` after the previous step went out, threaded as replies.
- **Confirm batches** are content-hashed. An approved draft must be byte-identical to what was previewed, and
  batches expire after 24 hours.

## Send modes

| `send_mode` | Behavior |
|---|---|
| `off` (default) | Nothing is sent. Drafts and deep links (`mailto:`, `t.me`, `wa.me`, `tel:`) for manual sending. |
| `confirm` | `leadgen send <slug>` saves a preview batch and prints its id. Nothing goes out until `leadgen send <slug> --approve <id>`. |
| `auto` | Sends within the caps without asking. |

Telegram, WhatsApp, LinkedIn, phone and SMS are always draft-only. Those platforms forbid automated cold messages
from personal accounts.

Claude is told never to change `send_mode`, never to approve a batch on your behalf, and never to send outside
the CLI. `/leadgen:send` can only be started by you, not by Claude on its own.

## The send gate and its limits

The plugin's PreToolUse hook (`hooks/guard.py`) reviews Claude's Bash commands and file edits:

- **Ask** before `leadgen send --approve` (including argparse-style abbreviations), before a send chained with
  other commands, when the campaign or `send_mode` can't be read, before shell indirection that mentions leadgen
  and approval (`$(...)`, `sh -c`, `python -c`, variables), and before any Bash command that may write
  `campaign.toml`.
- **Ask** before an Edit or Write that sets `send_mode = "auto"`, drops a campaign entry from `.gitignore`, or
  writes a script that would send an approved batch later.
- **Deny** `git add` of `campaigns/`, `suppression.txt`, `*.leads.*` or adapter fixtures, `git add -f` on broad paths,
  and `git add` together with ignore-rule edits.

The hook never answers "allow", so a safe-looking segment can't carry an unsafe one chained to it.

**Threat model.** The hook is a guardrail against mistakes and casual workarounds, **not a sandbox**. A shell is
too expressive for a hook to parse completely: encoded commands, copied campaign directories, scripts assembled
at run time. And an agent with SMTP credentials in its environment can reach the mail server without leadgen
at all. If you need a hard guarantee that a human approves every send:

1. Keep `SMTP_*` out of the Claude Code session (don't export them in the shell Claude Code starts from, and
   don't put them in its `env` settings).
2. Let Claude prepare: drafts, fact-check, `leadgen send <slug> --dry-run`, `leadgen send <slug>` (the preview).
3. Run `leadgen send <slug> --approve <id>` yourself, in your own terminal, with the SMTP variables set there.

## Data handling

- Campaign data stays in your workspace. `campaigns/`, `suppression.txt` and `.leadgen-cache/` are gitignored by
  `leadgen init`, and the hook blocks adding `campaigns/` and `suppression.txt` to git, forced or not.
- Collect what the offer needs, no more. Delete finished campaigns, but keep `suppression.txt`.
- Every contact records where it came from (`sources[].url`, `emails[].source`). That's the answer to "where did
  you get my address?"
- Sources are used logged out, at polite rates, without captcha bypass. New sources are qualified on their terms
  first (`parser-builder` skill).
- Test fixtures are synthetic. Never commit real lead data, even in an issue or PR.
