"""Per-market rules the sender enforces mechanically. Legal judgment stays with the user (see the compliance skill).

Each profile lists what every sent email must carry and what blocks sending outright. These are minimums taken
from the laws' texts, not legal advice:
- can-spam (US): accurate sender, physical postal address, a working opt-out honored within 10 business days.
- gdpr / uk-pecr (EU/UK B2B): identify yourself, legitimate-interest basis, opt-out in every message. PECR treats
  sole traders and partnerships like individuals (prior consent needed); only corporate subscribers are fair game.
- casl (Canada): sender identity + contact info + unsubscribe; needs consent, implied only when the address is
  conspicuously published and the message relates to the recipient's business role.
- ru (152-ФЗ / 38-ФЗ): advertising by email needs prior consent (38-ФЗ ст.18), so cold promotional email is not
  allowed; the sender refuses unless the campaign states consent was obtained (ru_consent = true).
"""
from __future__ import annotations

PROFILES = {
    "can-spam": {"requires": ["sender_name", "sender_address", "unsubscribe_text"]},
    "gdpr": {"requires": ["sender_name", "sender_company", "unsubscribe_text"]},
    "uk-pecr": {"requires": ["sender_name", "sender_company", "unsubscribe_text"]},
    "casl": {"requires": ["sender_name", "sender_company", "sender_address", "unsubscribe_text"]},
    "ru": {"requires": ["sender_name", "sender_company", "unsubscribe_text"], "needs_flag": "ru_consent"},
}


def issues(out_cfg: dict) -> list[str]:
    """Blocking problems for sending under this campaign's [outreach] config. Empty list = OK to send."""
    prof = out_cfg.get("compliance") or ""
    if prof not in PROFILES:
        return [f"set [outreach] compliance to one of {sorted(PROFILES)} (got {prof!r}); see the compliance skill"]
    p = PROFILES[prof]
    probs = [f"[outreach] {k} is empty but required by {prof}" for k in p["requires"] if not str(out_cfg.get(k) or "").strip()]
    if p.get("needs_flag") and not out_cfg.get(p["needs_flag"]):
        probs.append(f"{prof}: cold promotional email needs prior consent (38-ФЗ ст.18); set {p['needs_flag']} = true "
                     "only if every recipient consented")
    return probs


def footer(out_cfg: dict) -> str:
    """Identity + opt-out block appended to every sent email."""
    who = ", ".join(x for x in (out_cfg.get("sender_name"), out_cfg.get("sender_company")) if x)
    lines = ["--", who] if who else ["--"]
    if out_cfg.get("sender_address"):
        lines.append(out_cfg["sender_address"])
    if out_cfg.get("unsubscribe_text"):
        lines.append(out_cfg["unsubscribe_text"])
    return "\n".join(lines)
