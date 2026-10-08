---
description: Gated outreach sending - compliance check, dry run, preview, and your explicit approval per batch
argument-hint: <slug>
disable-model-invocation: true
---

The user asked to send outreach for campaign: $ARGUMENTS

Follow the `outreach` skill's "Sending" section and the `compliance` skill's pre-send checklist. Sending is
gated: you prepare, the user decides.

1. `leadgen status <slug> --json`: note `send_mode`, drafts, and sent today.
2. Run the `compliance` pre-send checklist for the campaign's market. Report anything missing (profile, sender
   fields, PECR legal form, CASL address source, RU consent). Don't fill sender identity or consent in for the user.
3. `leadgen send <slug> --dry-run`: show what would go out and what's skipped and why.
4. Then, by `send_mode`:
   - `off`: stop. Explain that sending is off, and hand over `leadgen drafts <slug> show <lead-id>` for manual
     sending. If they want the CLI to send, they set `send_mode` in `campaign.toml` themselves.
   - `confirm`: run `leadgen send <slug>`. It saves a preview batch and prints its id. Show the recipients,
     subjects and count, then **stop and ask**. Only after the user says yes to this batch, run
     `leadgen send <slug> --approve <id>` as a command on its own (the plugin hook asks them again). Mention
     that they can run `--approve` in their own terminal instead, with SMTP credentials kept out of this session.
   - `auto`: the user chose automatic sending. Run `leadgen send <slug>` once and report what went out.

Never change `send_mode`, never approve a batch the user hasn't seen, and never send by any route other than
`leadgen send`. Report sent, skipped, and remaining against the daily cap.
