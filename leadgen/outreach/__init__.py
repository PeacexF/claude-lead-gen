"""Outreach: drafts Claude writes, the suppression list, compliance footers, and the gated email sender.

Drafting is always allowed. Sending follows [outreach] send_mode (off | confirm | auto) and, in every mode, the
suppression list, daily and per-domain caps, sent.jsonl idempotency, the tier floor, and the compliance profile.
Only email is sendable; other channels get deep links for a human to send by hand.
"""
