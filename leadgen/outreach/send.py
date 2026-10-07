"""Gated email sending. See SPEC.md §7.

send_mode (campaign.toml [outreach]):
  off      nothing is sent (dry runs still show what would go out)
  confirm  `leadgen send <slug>` writes a batch preview and prints its id; nothing goes out until
           `leadgen send <slug> --approve <id>` (the plugin hook asks the user before that call runs)
  auto     sends within the caps without asking

Guards in every mode, re-checked at send time (also for an approved batch):
  suppression list · lead status (replied/won/lost/suppressed stop a sequence) · min_tier · one send per draft
  (sent.jsonl) · daily_cap · per_domain_cap (per recipient domain per day) · follow-ups only after the previous step
  went out followup_days ago · compliance profile (sender identity, address, opt-out) · approved drafts must be
  byte-identical to what was previewed · batches expire after 24 h.
Transport: SMTP from env (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM). Port 465 = implicit TLS,
anything else = STARTTLS.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import smtplib
import ssl
import time
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from .. import score
from ..core.campaign import Campaign
from ..core.store import append_jsonl, read_jsonl, write_jsonl
from . import compliance
from .drafts import SENDABLE, Drafts
from .suppression import Suppression

SMTP_ENV = ["SMTP_HOST", "SMTP_FROM"]
STOP_STATUSES = {"replied", "won", "lost", "suppressed"}
BATCH_TTL = 24 * 3600


class SendRefused(Exception):
    pass


def now() -> datetime.datetime:
    return datetime.datetime.now().astimezone()


def content_hash(d: dict, to: str) -> str:
    return hashlib.sha256(json.dumps([to, d.get("subject"), d.get("body")], ensure_ascii=False).encode()).hexdigest()[:16]


def best_email(lead: dict) -> str | None:
    """Prefer a personal address with MX, then a generic one with MX, then anything."""
    es = [e for e in lead.get("emails") or [] if isinstance(e, dict) and e.get("value")]
    rank = lambda e: (e.get("verified") not in ("mx", "smtp"), e.get("type") != "personal")  # noqa: E731
    return min(es, key=rank)["value"] if es else None


class Outbox:
    """Everything send needs about one campaign, loaded once."""

    def __init__(self, camp: Campaign):
        self.camp = camp
        self.cfg = camp.config["outreach"]
        self.leads = {l["id"]: l for l in read_jsonl(camp.leads_path)}
        self.drafts = Drafts(camp.outreach_dir / "drafts.jsonl")
        self.sent_path = camp.outreach_dir / "sent.jsonl"
        self.sent = list(read_jsonl(self.sent_path))
        self.sup = Suppression(camp.suppression_path())

    # --- planning ------------------------------------------------------------------------------------------
    def sent_today(self) -> list[dict]:
        day = now().date().isoformat()
        return [s for s in self.sent if (s.get("sent_at") or "")[:10] == day]

    def check(self, d: dict) -> tuple[str | None, str | None]:
        """(recipient, None) when the draft may go out now, else (None, reason)."""
        if d["channel"] not in SENDABLE:
            return None, f"{d['channel']} is draft-only (send by hand)"
        if d.get("status") != "draft":
            return None, f"status {d.get('status')}"
        if any(s["draft_id"] == d["id"] for s in self.sent):
            return None, "already sent"
        lead = self.leads.get(d["lead_id"])
        if not lead:
            return None, "lead not in leads.jsonl"
        if lead.get("status") in STOP_STATUSES:
            return None, f"lead status {lead['status']}"
        if not score.tier_at_least(lead.get("tier"), self.cfg.get("min_tier") or "B"):
            return None, f"tier {lead.get('tier')} below min_tier {self.cfg.get('min_tier')}"
        to = (d.get("to") or best_email(lead) or "").strip().lower()
        if not to:
            return None, "no email address"
        if self.sup.email_blocked(to) or self.sup.lead_blocked(lead):
            return None, "suppressed"
        if d["step"] > 1:
            prev = [s for s in self.sent if s["lead_id"] == d["lead_id"] and s.get("step") == d["step"] - 1]
            if not prev:
                return None, f"step {d['step'] - 1} not sent yet"
            due = datetime.datetime.fromisoformat(prev[-1]["sent_at"]) + datetime.timedelta(
                days=float(self.cfg.get("followup_days", 4)))
            if now() < due:
                return None, f"follow-up due {due.date().isoformat()}"
        return to, None

    def plan(self) -> tuple[list[dict], list[dict]]:
        """(ready, skipped). ready respects caps; order: step 1 before follow-ups, then tier, then score."""
        ready, skipped = [], []
        cap = int(self.cfg.get("daily_cap", 30)) - len(self.sent_today())
        per_dom = int(self.cfg.get("per_domain_cap", 1))
        dom_count: dict[str, int] = {}
        for s in self.sent_today():
            dom_count[s["to"].rsplit("@", 1)[-1]] = dom_count.get(s["to"].rsplit("@", 1)[-1], 0) + 1

        def order(d):
            lead = self.leads.get(d["lead_id"]) or {}
            t = lead.get("tier")
            return (d["step"], score.TIER_ORDER.index(t) if t in score.TIER_ORDER else 9, -(lead.get("score") or 0), d["id"])

        for d in sorted(self.drafts.rows.values(), key=order):
            to, why = self.check(d)
            if why:
                if d["channel"] in SENDABLE and d.get("status") == "draft":
                    skipped.append({"draft_id": d["id"], "reason": why})
                continue
            dom = to.rsplit("@", 1)[-1]
            if dom_count.get(dom, 0) >= per_dom:
                skipped.append({"draft_id": d["id"], "reason": f"per_domain_cap reached for {dom}"})
                continue
            if len(ready) >= cap:
                skipped.append({"draft_id": d["id"], "reason": "daily_cap reached"})
                continue
            dom_count[dom] = dom_count.get(dom, 0) + 1
            ready.append({"draft_id": d["id"], "lead_id": d["lead_id"], "step": d["step"], "to": to,
                          "subject": d.get("subject"), "hash": content_hash(d, to)})
        return ready, skipped

    # --- batches -------------------------------------------------------------------------------------------
    @property
    def batch_dir(self):
        p = self.camp.outreach_dir / "batches"
        p.mkdir(exist_ok=True)
        return p

    def save_batch(self, ready: list[dict]) -> str:
        bid = hashlib.sha1(json.dumps([r["draft_id"] + r["hash"] for r in ready]).encode()
                           + str(time.time()).encode()).hexdigest()[:8]
        (self.batch_dir / f"{bid}.json").write_text(json.dumps(
            {"id": bid, "created": now().isoformat(timespec="seconds"), "items": ready}, ensure_ascii=False, indent=1))
        return bid

    def load_batch(self, bid: str) -> dict:
        p = self.batch_dir / f"{bid}.json"
        if not p.exists() or not bid.isalnum():
            raise SendRefused(f"no batch {bid!r} in {self.batch_dir}")
        b = json.loads(p.read_text())
        if (now() - datetime.datetime.fromisoformat(b["created"])).total_seconds() > BATCH_TTL:
            raise SendRefused(f"batch {bid} is older than 24 h; run `leadgen send {self.camp.slug}` for a fresh preview")
        if b.get("approved"):
            raise SendRefused(f"batch {bid} was already approved at {b['approved']}")
        return b

    # --- sending -------------------------------------------------------------------------------------------
    def message(self, item: dict, sender_from: str) -> EmailMessage:
        d = self.drafts.rows[item["draft_id"]]
        msg = EmailMessage()
        msg["From"] = formataddr((self.cfg.get("sender_name") or "", sender_from))
        msg["To"] = item["to"]
        msg["Subject"] = d["subject"]
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain=sender_from.rsplit("@", 1)[-1])
        msg["List-Unsubscribe"] = f"<mailto:{sender_from}?subject=unsubscribe>"
        prev = [s for s in self.sent if s["lead_id"] == d["lead_id"] and s.get("step") == d["step"] - 1]
        if prev and prev[-1].get("message_id"):
            msg["In-Reply-To"] = msg["References"] = prev[-1]["message_id"]
        msg.set_content(d["body"].rstrip() + "\n\n" + compliance.footer(self.cfg) + "\n")
        return msg

    def deliver(self, items: list[dict], transport, batch: str | None, log) -> list[dict]:
        sender_from = os.environ.get("SMTP_FROM", "")
        delay = float(self.cfg.get("send_delay", 10))
        done = []
        for i, item in enumerate(items):
            msg = self.message(item, sender_from)
            try:
                transport.send(msg)
            except Exception as e:
                log(f"[send] {item['to']}: FAILED {type(e).__name__}: {e}")
                self.drafts.set_status(item["draft_id"], "draft", last_error=f"{type(e).__name__}: {e}"[:200])
                continue
            rec = {"draft_id": item["draft_id"], "lead_id": item["lead_id"], "step": item["step"], "to": item["to"],
                   "subject": msg["Subject"], "message_id": msg["Message-ID"],
                   "sent_at": now().isoformat(timespec="seconds"), "batch": batch}
            append_jsonl(self.sent_path, [rec])  # written per message: a crash never re-sends
            self.sent.append(rec)
            self.drafts.set_status(item["draft_id"], "sent", sent_at=rec["sent_at"])
            lead = self.leads[item["lead_id"]]
            if lead.get("status") in (None, "new", "drafted"):
                lead["status"] = "sent"
            done.append(rec)
            log(f"[send] {item['to']}: sent ({item['draft_id']})")
            if delay and i < len(items) - 1:
                time.sleep(delay)
        self.drafts.save()
        if done:
            write_jsonl(self.camp.leads_path, self.leads.values())
        return done


class SMTPTransport:
    def __init__(self):
        self.host = os.environ["SMTP_HOST"]
        self.port = int(os.environ.get("SMTP_PORT") or 587)
        self.user = os.environ.get("SMTP_USER")
        self.password = os.environ.get("SMTP_PASSWORD")
        self.conn = None

    def open(self):
        ctx = ssl.create_default_context()
        if self.port == 465:
            self.conn = smtplib.SMTP_SSL(self.host, self.port, context=ctx, timeout=30)
        else:
            self.conn = smtplib.SMTP(self.host, self.port, timeout=30)
            self.conn.starttls(context=ctx)
        if self.user:
            self.conn.login(self.user, self.password or "")
        return self

    def send(self, msg: EmailMessage) -> None:
        if self.conn is None:
            self.open()
        self.conn.send_message(msg)

    def close(self):
        if self.conn is not None:
            try:
                self.conn.quit()
            except Exception:
                pass


def run(camp: Campaign, dry_run: bool = False, approve: str | None = None, transport=None, log=print) -> dict:
    ob = Outbox(camp)
    mode = ob.cfg.get("send_mode") or "off"
    ready, skipped = ob.plan()
    res = {"mode": mode, "ready": ready, "skipped": skipped, "sent": [], "batch": None, "dry_run": dry_run}
    if dry_run:
        return res
    if mode not in ("off", "confirm", "auto"):
        raise SendRefused(f"unknown send_mode {mode!r}; use off, confirm or auto")
    if mode == "off":
        raise SendRefused("send_mode is \"off\" in campaign.toml [outreach]; drafts are kept, nothing was sent. "
                          "Set send_mode = \"confirm\" (or \"auto\") to send.")
    probs = compliance.issues(ob.cfg)
    if probs:
        raise SendRefused("compliance check failed:\n  " + "\n  ".join(probs))
    if mode == "confirm" and not approve:
        if ready:
            res["batch"] = ob.save_batch(ready)
        return res
    missing = [e for e in SMTP_ENV if not os.environ.get(e)]
    if missing and transport is None:
        raise SendRefused(f"missing SMTP env: {', '.join(missing)} (also SMTP_PORT, SMTP_USER, SMTP_PASSWORD)")
    if approve:
        batch = ob.load_batch(approve)
        now_ok = {r["draft_id"]: r for r in ready}
        items = []
        for it in batch["items"]:
            cur = now_ok.get(it["draft_id"])
            if not cur:
                why = next((s["reason"] for s in skipped if s["draft_id"] == it["draft_id"]), "no longer eligible")
                res["skipped"].append({"draft_id": it["draft_id"], "reason": f"approved but {why}"})
            elif cur["hash"] != it["hash"]:
                res["skipped"].append({"draft_id": it["draft_id"], "reason": "changed since the preview; re-preview"})
            else:
                items.append(cur)
        res["batch"] = approve
    else:
        items = ready
    own = transport is None
    transport = transport or SMTPTransport()
    try:
        res["sent"] = ob.deliver(items, transport, approve, log)
    finally:
        if own:
            transport.close()
    if approve:
        p = ob.batch_dir / f"{approve}.json"
        b = json.loads(p.read_text())
        b["approved"] = now().isoformat(timespec="seconds")
        p.write_text(json.dumps(b, ensure_ascii=False, indent=1))
    return res
