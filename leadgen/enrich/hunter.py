"""Hunter.io domain search: the emails Hunter knows at a lead's domain, with names, positions and the pattern.

Keyed (HUNTER_API_KEY, sent as the X-API-KEY header). Searches cost credits: the free plan has a small monthly
allowance and returns at most 10 emails per domain, and Hunter counts a search when it returns at least one email.
So the step is off by default and runs only on leads already scored into `[enrich] hunter_tiers` (default A and B):
`leadgen run` does it after scoring (then re-scores); `leadgen enrich <slug> --steps hunter` on an already scored list.

Personal emails of named people are personal data: the compliance skill's checklist applies before any outreach.
Results land in lead["hunter"]; emails join lead.emails (source "hunter.io", verified "smtp" when Hunter's own
verification says valid); people join lead.people with their position.
"""
from __future__ import annotations

import datetime
import json
import os
import urllib.parse

from ..core import schema
from ..core.http import Blocked

API = "https://api.hunter.io/v2/domain-search"
ENV = ["HUNTER_API_KEY"]


def ready() -> bool:
    return all(os.environ.get(e) for e in ENV)


def wanted(lead: dict, cfg: dict) -> bool:
    tiers = cfg["enrich"].get("hunter_tiers") or ["A", "B"]
    return bool(lead.get("domain")) and lead.get("tier") in tiers


def parse(data: dict, domain: str) -> dict:
    d = data.get("data") or {}
    emails = []
    for e in d.get("emails") or []:
        if not e.get("value"):
            continue
        name = " ".join(x for x in (e.get("first_name"), e.get("last_name")) if x) or None
        emails.append({"value": e["value"].lower(), "type": e.get("type"), "confidence": e.get("confidence"),
                       "name": name, "position": e.get("position"), "seniority": e.get("seniority"),
                       "department": e.get("department"),
                       "status": (e.get("verification") or {}).get("status"),
                       "sources": [s.get("uri") for s in e.get("sources") or [] if s.get("uri")][:3]})
    return {"checked": datetime.date.today().isoformat(), "domain": domain, "pattern": d.get("pattern"),
            "organization": d.get("organization"), "found": len(emails), "emails": emails,
            "url": f"https://hunter.io/search/{domain}"}


def apply(lead: dict, res: dict) -> dict:
    lead["hunter"] = res
    have = {e["value"] for e in lead.get("emails") or [] if isinstance(e, dict)}
    people = {p.get("name") for p in lead.get("people") or []}
    for e in res["emails"]:
        v = schema.clean_email(e["value"])
        if v and v not in have:
            have.add(v)
            lead.setdefault("emails", []).append({
                "value": v, "source": (e["sources"] or [res["url"]])[0], "via": "hunter.io",
                "type": "personal" if e["type"] == "personal" else schema.email_type(v),
                "verified": "smtp" if e["status"] == "valid" else "none", "confidence": e["confidence"]})
        if e["name"] and e["name"] not in people:
            people.add(e["name"])
            lead.setdefault("people", []).append({"name": e["name"], "role": e["position"], "email": v,
                                                  "source": res["url"]})
    return lead


def enrich(fetcher, lead: dict, limit: int = 10) -> dict:
    domain = lead["domain"]
    url = API + "?" + urllib.parse.urlencode({"domain": domain, "limit": max(1, min(int(limit), 100))})
    status, _, text = fetcher.request(url, headers={"X-API-KEY": os.environ["HUNTER_API_KEY"]}, ttl=90 * 86400)
    if status >= 400:
        fetcher.forget(url)  # a refusal or quota error must not be replayed from the cache
    if status == 401:
        raise Blocked("hunter: key refused (401); check HUNTER_API_KEY")
    if status == 429:
        raise Blocked("hunter: usage limit reached (429)")
    if status == 403:
        raise Blocked("hunter: rate limited (403)")
    if status >= 400:
        detail = ""
        try:
            detail = "; ".join(e.get("details", "") for e in json.loads(text).get("errors") or [])
        except ValueError:
            pass
        raise RuntimeError(f"hunter {status}: {detail}"[:200])
    return apply(lead, parse(json.loads(text), domain))
