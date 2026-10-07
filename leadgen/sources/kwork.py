"""Kwork buyer orders (what RU businesses pay freelancers for right now). Ported from claude-kit.

Each page of kwork.ru/projects embeds a JSON "pagination" object with the orders. Demand signal for niche
research: budget, category, number of offers (competition), buyer hire rate.

spec: {type="kwork", max_pages=50}
"""
from __future__ import annotations

import json
import re

from . import LayoutChanged

NAME = "kwork"
KIND = "demand"
REGIONS = "RU"
ENV: list[str] = []
SNAPSHOT = True
ABOUT = "Kwork buyer orders: budget, category, offers. Demand signal for niche research."


def units(spec: dict) -> list[dict]:
    return [{"max_pages": int(spec.get("max_pages", 50))}]


def unit_key(u: dict) -> str:
    return "projects"


def fetcher(camp):
    return camp.fetcher(delay=2.0, lang="ru")


def pagination(html: str) -> dict:
    i = html.find('"pagination":')
    if i < 0:
        raise LayoutChanged('no "pagination": JSON on kwork.ru/projects')
    obj, _ = json.JSONDecoder().raw_decode(html[i + len('"pagination":'):])
    return obj


def categories(html: str) -> dict[str, str]:
    names = {}
    for pat in (r'"CATID":"?(\d+)"?,"name":"([^"]+)"', r'"id":"?(\d+)"?,"name":"([^"]{3,60})"'):
        for cid, name in re.findall(pat, html):
            names.setdefault(cid, name.encode().decode("unicode_escape") if "\\u" in name else name)
    return names


def to_row(w: dict, cats: dict) -> dict:
    return {
        "source_id": w["id"], "url": f"https://kwork.ru/projects/{w['id']}", "title": w.get("name"),
        "description": w.get("description") or "", "budget": float(w["priceLimit"]) if w.get("priceLimit") else None,
        "budget_max": float(w["possiblePriceLimit"]) if w.get("possiblePriceLimit") else None, "currency": "RUB",
        "category": cats.get(str(w.get("category_id")), str(w.get("category_id"))), "offers": w.get("kwork_count"),
        "created": w.get("date_create"), "type": "project",
        "buyer_hired_pct": ((w.get("user") or {}).get("data") or {}).get("wants_hired_percent"),
    }


def collect_unit(ctx, unit: dict) -> list[dict]:
    page, last, seen, rows, cats = 1, None, set(), [], {}
    while (last is None or page <= last) and page <= unit["max_pages"]:
        html = ctx.fetcher.text(f"https://kwork.ru/projects?page={page}", ttl=20 * 3600)
        if page == 1:
            cats = categories(html)
        p = pagination(html)
        last = p["last_page"]
        for w in p["data"]:
            if w["id"] not in seen:
                seen.add(w["id"])
                rows.append(to_row(w, cats))
        page += 1
    return rows
