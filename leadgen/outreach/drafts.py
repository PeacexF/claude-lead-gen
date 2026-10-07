"""Draft store: <campaign>/outreach/drafts.jsonl, one row per lead × step × channel.

Claude writes drafts (outreach skill / outreach-writer agent) and stores them with `leadgen drafts <slug> add`.
Each draft must cite its evidence: [{"fact": "...", "source": "<url or file>"}], one entry per claim the message
makes about the lead, so a reviewer (or the fact-checker agent) can verify every line.

Row: id, lead_id, step, channel, to, subject, body, evidence[], status (draft|sent|skipped), created, updated.
Re-adding a draft replaces it unless it was already sent.
"""
from __future__ import annotations

import datetime
import re
import urllib.parse

from ..core.store import read_jsonl, write_jsonl

CHANNELS = ["email", "telegram", "whatsapp", "linkedin", "phone", "sms", "contact_form"]
SENDABLE = {"email"}


class DraftError(ValueError):
    pass


def draft_id(d: dict) -> str:
    return f"{d['lead_id']}:{int(d.get('step') or 1)}:{d.get('channel') or 'email'}"


def validate(d: dict, leads_by_id: dict | None = None) -> dict:
    d = dict(d)
    for k in ("lead_id", "body"):
        if not str(d.get(k) or "").strip():
            raise DraftError(f"draft missing {k}: {str(d)[:120]}")
    d["step"] = int(d.get("step") or 1)
    d["channel"] = d.get("channel") or "email"
    if d["channel"] not in CHANNELS:
        raise DraftError(f"{d['lead_id']}: unknown channel {d['channel']!r}; use one of {CHANNELS}")
    if leads_by_id is not None and d["lead_id"] not in leads_by_id:
        raise DraftError(f"unknown lead_id {d['lead_id']!r} (not in leads.jsonl)")
    ev = d.get("evidence")
    if not isinstance(ev, list) or not ev:
        raise DraftError(f"{d['lead_id']}: evidence must be a non-empty list of {{fact, source}}")
    for e in ev:
        if not isinstance(e, dict) or not e.get("fact") or not e.get("source"):
            raise DraftError(f"{d['lead_id']}: each evidence item needs fact and source, got {e!r}")
    if d["channel"] == "email":
        if not d.get("subject"):
            raise DraftError(f"{d['lead_id']}: email draft needs a subject")
        if d.get("to") and "@" not in d["to"]:
            raise DraftError(f"{d['lead_id']}: email 'to' is not an address: {d['to']!r}")
    return d


class Drafts:
    def __init__(self, path):
        self.path = path
        self.rows: dict[str, dict] = {r["id"]: r for r in read_jsonl(path)}

    def add(self, drafts: list[dict], leads_by_id: dict | None = None) -> dict:
        now = datetime.datetime.now().isoformat(timespec="seconds")
        added, replaced, kept = 0, 0, []
        valid = [validate(d, leads_by_id) for d in drafts]  # all-or-nothing
        for d in valid:
            did = draft_id(d)
            old = self.rows.get(did)
            if old and old.get("status") == "sent":
                kept.append(did)
                continue
            row = {"id": did, **{k: d.get(k) for k in ("lead_id", "step", "channel", "to", "subject", "body", "evidence")},
                   "status": "draft", "created": (old or {}).get("created") or now, "updated": now}
            for k, v in d.items():
                row.setdefault(k, v)  # keep extra fields (language, variant, notes)
            replaced += bool(old)
            added += not old
            self.rows[did] = row
        self.save()
        return {"added": added, "replaced": replaced, "kept_sent": kept}

    def save(self) -> None:
        write_jsonl(self.path, sorted(self.rows.values(), key=lambda r: (r["lead_id"], r["step"], r["channel"])))

    def for_lead(self, lead_id: str) -> list[dict]:
        return [r for r in self.rows.values() if r["lead_id"] == lead_id]

    def set_status(self, did: str, status: str, **extra) -> None:
        self.rows[did].update(status=status, updated=datetime.datetime.now().isoformat(timespec="seconds"), **extra)


def deeplink(draft: dict, lead: dict | None = None) -> str | None:
    """A link a human can click to send a draft-only channel by hand."""
    lead = lead or {}
    to = draft.get("to") or ""
    socials = lead.get("socials") or {}
    ch = draft["channel"]
    if ch == "email":
        to = to or next((e["value"] for e in lead.get("emails") or []), "")
        q = urllib.parse.urlencode({"subject": draft.get("subject") or "", "body": draft["body"]}, quote_via=urllib.parse.quote)
        return f"mailto:{to}?{q}" if to else None
    if ch == "telegram":
        t = to or next(iter(socials.get("telegram") or []), "")
        handle = re.sub(r"^(https?://)?(t\.me|telegram\.me)/", "", t).lstrip("@")
        return f"https://t.me/{handle}" if handle else None
    if ch == "whatsapp":
        digits = re.sub(r"\D", "", to or next(iter(lead.get("phones") or []), ""))
        return f"https://wa.me/{digits}?text={urllib.parse.quote(draft['body'])}" if digits else None
    if ch == "linkedin":
        return to or next(iter(socials.get("linkedin") or []), None)
    if ch in ("phone", "sms"):
        digits = re.sub(r"\D", "", to or next(iter(lead.get("phones") or []), ""))
        return (f"sms:+{digits}" if ch == "sms" else f"tel:+{digits}") if digits else None
    if ch == "contact_form":
        return to or (lead.get("site") or {}).get("final_url") or lead.get("website")
    return None
