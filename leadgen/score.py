"""Transparent, config-driven lead scoring: score = sum of points of the rules a lead matches; tier from thresholds.

Rules come from [[scoring.rules]] in campaign.toml. Every condition in one rule must hold (AND):

    has = "emails"                    path has a non-empty / truthy value
    missing = "website"               path is empty
    field = "reviews" + gte = 20      compare a path: eq, ne, gte, lte, in (list), contains, matches (regex)
    signal = "hiring"                 lead has a signal of this type (or any of a list)
    tech = ["wordpress", "wix"]       site.tech contains any of these
    category = "dent|ortho"           regex over categories + segment
    points = 10                       may be negative (a penalty)
    disqualify = true                 a match puts the lead in tier D regardless of score (ICP exclusions)

Paths are dotted ("site.reachable", "dns.mail_provider"). Through a list they fan out: "emails.verified" is the
list of every email's verified value, and a comparison holds when any element satisfies it.
"""
from __future__ import annotations

import re

COMPARE = ("eq", "ne", "gte", "lte", "in", "contains", "matches")
KNOWN = {"name", "points", "disqualify", "has", "missing", "field", "signal", "tech", "category", *COMPARE}
TIER_ORDER = ["A", "B", "C", "D"]


class RuleError(ValueError):
    pass


def values(obj, path: str) -> list:
    """All values at a dotted path, fanning out through lists along the way."""
    cur = [obj]
    for part in path.split("."):
        flat = [x for c in cur for x in (c if isinstance(c, list) else [c])]
        cur = [c.get(part) for c in flat if isinstance(c, dict)]
    out = [x for v in cur for x in (v if isinstance(v, list) else [v])]
    return [v for v in out if v is not None]


def truthy(vs: list) -> bool:
    return any(v not in ("", {}, [], False, 0) for v in vs)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def check(rule: dict) -> None:
    unknown = set(rule) - KNOWN
    if unknown:
        raise RuleError(f"rule {rule.get('name')!r}: unknown keys {sorted(unknown)}; allowed: {sorted(KNOWN)}")
    if "points" not in rule and not rule.get("disqualify"):
        raise RuleError(f"rule {rule.get('name')!r}: needs points (or disqualify = true)")
    cmp = [k for k in COMPARE if k in rule]
    if cmp and "field" not in rule:
        raise RuleError(f"rule {rule.get('name')!r}: {cmp} need field = \"<path>\"")
    if not ({"has", "missing", "field", "signal", "tech", "category"} & set(rule)):
        raise RuleError(f"rule {rule.get('name')!r}: no condition")
    if "matches" in rule:
        re.compile(rule["matches"])
    if "category" in rule:
        re.compile(rule["category"])


def matches(rule: dict, lead: dict) -> bool:
    if "has" in rule and not truthy(values(lead, rule["has"])):
        return False
    if "missing" in rule and truthy(values(lead, rule["missing"])):
        return False
    if "field" in rule:
        vs = values(lead, rule["field"])
        if "eq" in rule and not any(v == rule["eq"] for v in vs):
            return False
        if "ne" in rule and any(v == rule["ne"] for v in vs):
            return False
        if "gte" in rule and not any((n := _num(v)) is not None and n >= rule["gte"] for v in vs):
            return False
        if "lte" in rule and not any((n := _num(v)) is not None and n <= rule["lte"] for v in vs):
            return False
        if "in" in rule and not any(v in rule["in"] for v in vs):
            return False
        if "contains" in rule and not any(str(rule["contains"]).lower() in str(v).lower() for v in vs):
            return False
        if "matches" in rule and not any(re.search(rule["matches"], str(v), re.I) for v in vs):
            return False
    if "signal" in rule:
        want = rule["signal"] if isinstance(rule["signal"], list) else [rule["signal"]]
        if not any(s.get("type") in want for s in lead.get("signals") or []):
            return False
    if "tech" in rule:
        want = rule["tech"] if isinstance(rule["tech"], list) else [rule["tech"]]
        if not set(want) & set((lead.get("site") or {}).get("tech") or []):
            return False
    if "category" in rule:
        blob = " | ".join([*(lead.get("categories") or []), lead.get("segment") or ""])
        if not re.search(rule["category"], blob, re.I):
            return False
    return True


def describe(rule: dict) -> str:
    parts = []
    for k in ("has", "missing", "signal", "tech", "category"):
        if k in rule:
            parts.append(f"{k} {rule[k]}")
    if "field" in rule:
        parts += [f"{rule['field']} {k} {rule[k]!r}" for k in COMPARE if k in rule]
    return " and ".join(parts)


def tier_for(score: float, tiers: dict) -> str:
    for t in sorted(tiers, key=lambda t: -tiers[t]):
        if score >= tiers[t]:
            return t
    return "D"


def score_lead(lead: dict, rules: list[dict], tiers: dict) -> dict:
    total, breakdown, dq = 0, {}, None
    for r in rules:
        if matches(r, lead):
            name = r.get("name") or describe(r)
            if r.get("disqualify"):
                dq = dq or name
                breakdown[name] = "disqualified"
            else:
                breakdown[name] = r["points"]
                total += r["points"]
    lead["score"] = total
    lead["score_breakdown"] = breakdown
    lead["tier"] = "D" if dq else tier_for(total, tiers)
    return lead


def formula(rules: list[dict], tiers: dict) -> str:
    lines = ["score = sum of matched rules:"]
    for r in rules:
        pts = "DISQUALIFY" if r.get("disqualify") else f"{r['points']:+}"
        lines.append(f"  {pts:>10}  {r.get('name') or describe(r)}   [{describe(r)}]")
    t = sorted(tiers.items(), key=lambda kv: -kv[1])
    lines.append("tiers: " + ", ".join(f"{k} >= {v}" for k, v in t) + ", else D")
    return "\n".join(lines)


def score_all(leads: list[dict], cfg: dict) -> dict:
    rules = cfg["scoring"].get("rules") or []
    tiers = cfg["scoring"].get("tiers") or {"A": 60, "B": 40, "C": 20}
    for r in rules:
        check(r)
    for lead in leads:
        score_lead(lead, rules, tiers)
    counts = {t: sum(1 for l in leads if l.get("tier") == t) for t in TIER_ORDER}
    hits = {(r.get("name") or describe(r)): sum(1 for l in leads if (r.get("name") or describe(r)) in l["score_breakdown"])
            for r in rules}
    return {"leads": len(leads), "tiers": counts, "rule_hits": hits, "formula": formula(rules, tiers)}


def tier_at_least(tier: str | None, min_tier: str) -> bool:
    return tier in TIER_ORDER and TIER_ORDER.index(tier) <= TIER_ORDER.index(min_tier)
