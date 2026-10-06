"""Fold partial records from all sources into one lead per business.

Match keys, strongest first: own-site domain → phone → normalized name + city. Records sharing any key are
merged (union-find), so a 2GIS entry with a site, a Yandex entry with the same phone, and an OSM entry with
the same name in the same city all collapse into one lead. Chains that list one site for many branches
collapse too; that's intended (one buyer).

Existing enrichment, scores, notes and status on leads.jsonl are kept across re-merges.
"""
from __future__ import annotations

import re

from . import schema


def _as_list(v) -> list:
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple, set)) else [v]


def normalize(rec: dict, default_cc: str | None = None) -> dict:
    """Partial source record → lead-shaped fragment."""
    sites = _as_list(rec.get("website")) + _as_list(rec.get("sites"))
    own = schema.own_sites(sites)
    socials = {k: _as_list((rec.get("socials") or {}).get(k)) + _as_list(rec.get(k)) for k in schema.SOCIAL_KEYS}
    # social links that sources listed as "websites"
    for u in sites:
        for k, rx in schema.SOCIAL_PATTERNS.items():
            if re.match(rx, u or "", re.I):
                socials[k].append(u)
    emails = []
    for e in _as_list(rec.get("emails")):
        v = schema.clean_email(e["value"] if isinstance(e, dict) else e)
        if v:
            emails.append({"value": v, "source": rec.get("source"), "type": schema.email_type(v), "verified": "none"})
    phones = [p for p in (schema.phone_digits(x, default_cc) for x in _as_list(rec.get("phones"))) if p]
    frag = schema.empty_lead()
    frag.update({
        "name": rec.get("name"), "names": [rec["name"]] if rec.get("name") else [],
        "website": own[0] if own else None, "domain": schema.host(own[0]) if own else None,
        "country": rec.get("country"), "city": rec.get("city"), "address": rec.get("address"),
        "lat": rec.get("lat"), "lon": rec.get("lon"),
        "categories": [c for c in _as_list(rec.get("categories")) if c], "segment": rec.get("segment"),
        "phones": phones, "emails": emails,
        "socials": {k: list(dict.fromkeys(v for v in vs if v)) for k, vs in socials.items()},
        "people": _as_list(rec.get("people")),
        "rating": rec.get("rating"), "reviews": rec.get("reviews"),
        "signals": _as_list(rec.get("signals")),
        "sources": [{"source": rec.get("source"), "id": rec.get("source_id"), "url": rec.get("url"),
                     "collected": rec.get("collected"), "query": rec.get("segment")}],
    })
    if rec.get("legal"):
        frag["legal"] = {"name": rec["legal"].get("name"), "registry_ids": dict(rec["legal"].get("registry_ids") or {})}
    frag["id"] = schema.lead_id(frag)
    return frag


def _keys(frag: dict) -> list[str]:
    keys = []
    if frag.get("domain"):
        keys.append("d:" + frag["domain"])
    keys += ["p:" + p for p in frag.get("phones") or [] if len(p) >= 9]
    nm = schema.norm_name(frag.get("name"))
    if nm and frag.get("city"):
        keys.append(f"n:{nm}|{frag['city'].lower()}")
    return keys or ["id:" + frag["id"]]


def _union(a: dict, b: dict) -> dict:
    """Merge fragment b into lead a (a wins on scalars that are already set)."""
    for k in ("name", "website", "domain", "country", "city", "address", "lat", "lon", "segment"):
        if not a.get(k) and b.get(k):
            a[k] = b[k]
    for k in ("names", "categories", "phones"):
        a[k] = list(dict.fromkeys((a.get(k) or []) + (b.get(k) or [])))
    seen = {e["value"] for e in a.get("emails") or []}
    a["emails"] = (a.get("emails") or []) + [e for e in b.get("emails") or [] if e["value"] not in seen]
    for k in schema.SOCIAL_KEYS:
        a["socials"][k] = list(dict.fromkeys((a["socials"].get(k) or []) + ((b.get("socials") or {}).get(k) or [])))
    pk = {(p.get("name"), p.get("role")) for p in a.get("people") or []}
    a["people"] = (a.get("people") or []) + [p for p in b.get("people") or [] if (p.get("name"), p.get("role")) not in pk]
    sk = {(s.get("type"), str(s.get("value"))) for s in a.get("signals") or []}
    a["signals"] = (a.get("signals") or []) + [s for s in b.get("signals") or [] if (s.get("type"), str(s.get("value"))) not in sk]
    srcs = {(s.get("source"), str(s.get("id")), s.get("url")) for s in a.get("sources") or []}
    a["sources"] = (a.get("sources") or []) + [s for s in b.get("sources") or [] if (s.get("source"), str(s.get("id")), s.get("url")) not in srcs]
    if b.get("rating") is not None:
        a["rating"] = max(float(a.get("rating") or 0), float(b["rating"]))
    if b.get("reviews") is not None:
        a["reviews"] = max(int(a.get("reviews") or 0), int(b["reviews"]))
    bl = b.get("legal") or {}
    al = a.setdefault("legal", {"name": None, "registry_ids": {}})
    al["name"] = al.get("name") or bl.get("name")
    al["registry_ids"] = {**(bl.get("registry_ids") or {}), **(al.get("registry_ids") or {})}
    return a


def merge(records: list[dict], existing: list[dict] | None = None, default_cc: str | None = None) -> list[dict]:
    frags = [normalize(r, default_cc) for r in records]
    # union-find over shared keys
    parent = list(range(len(frags)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    owner: dict[str, int] = {}
    for i, f in enumerate(frags):
        for k in _keys(f):
            if k in owner:
                ri, rj = find(i), find(owner[k])
                if ri != rj:
                    parent[ri] = rj
            else:
                owner[k] = i
    groups: dict[int, list[dict]] = {}
    for i, f in enumerate(frags):
        groups.setdefault(find(i), []).append(f)

    leads = []
    for members in groups.values():
        # prefer a member with an own site as the base so id = domain
        members.sort(key=lambda f: (f.get("domain") is None, -(f.get("reviews") or 0)))
        lead = members[0]
        for m in members[1:]:
            _union(lead, m)
        lead["id"] = schema.lead_id(lead)
        leads.append(lead)

    # keep enrichment / scoring / workflow state from the previous leads file
    prev = {l["id"]: l for l in existing or []}
    out = []
    for lead in leads:
        old = prev.pop(lead["id"], None)
        if old:
            for k in ("site", "score", "score_breakdown", "tier", "notes", "status"):
                if old.get(k):
                    lead[k] = old[k]
            lead = _union(lead, {**schema.empty_lead(), **{k: old.get(k) for k in
                                 ("emails", "people", "signals", "socials", "legal", "phones", "categories", "names", "sources")
                                 if old.get(k)}})
        out.append(lead)
    out.extend(prev.values())  # leads that came from a since-deleted raw file or were added by hand
    return out
