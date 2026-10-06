"""Kwork gigs (sellers' offers) for search queries, plus each seller's profile. Ported from claude-kit.

Use it to find service providers or partners (e.g. lawyers who sell 152-ФЗ documents), or to size supply
and prices of a service. Rows are seller-level leads: one per seller, with gigs, prices and review counts.

spec: {type="kwork_gigs", queries=["152-фз"], category="63"}    (63 = «Юридическая помощь»; omit for all)
"""
from __future__ import annotations

import html as htmllib
import json
import re
import urllib.parse

NAME = "kwork_gigs"
KIND = "businesses"
REGIONS = "RU"
ENV: list[str] = []
ABOUT = "Kwork sellers for a service query: gigs, prices, reviews, profile bio. Partners/suppliers/competitors."

MAX_PAGES = 15
KEEP = ["id", "url", "gtitle", "userId", "userName", "price", "isFrom", "days", "userRating", "userRatingCount",
        "rating", "sellerLevel", "queueCount", "categoryTitle"]


def units(spec: dict) -> list[dict]:
    return [{"query": q, "category": str(spec.get("category") or "")} for q in spec.get("queries") or []]


def unit_key(u: dict) -> str:
    return f"{u['query']}__c{u['category'] or 'all'}"


def fetcher(camp):
    return camp.fetcher(delay=2.0, lang="ru")


def gigs_in(html: str) -> list[dict]:
    out = []
    for m in re.finditer(r'"data":\[\{"id":', html):
        try:
            arr, _ = json.JSONDecoder().raw_decode(html[m.start() + 7:])
        except ValueError:
            continue
        out += [g for g in arr if isinstance(g, dict) and "gtitle" in g]
    return out


def profile(html: str) -> dict:
    def meta(pat):
        m = re.search(pat, html, re.S)
        return htmllib.unescape(m.group(1)).strip() if m else None
    title = meta(r"<title>(.*?)</title>") or ""
    lvl = meta(r'"userSellerLevel":(\d+)')
    return {"title": re.sub(r"^Фрилансер\s+|\s+-\s+Kwork$", "", title), "bio": meta(r'<meta name="description" content="([^"]*)"'),
            "registered": meta(r'"userProfileAddTime":"([^"]+)"'), "seller_level": int(lvl) if lvl else None}


def collect_unit(ctx, unit: dict) -> list[dict]:
    gigs, seen = {}, set()
    for n in range(1, MAX_PAGES + 1):
        url = f"https://kwork.ru/search?query={urllib.parse.quote(unit['query'])}" + \
              (f"&c={unit['category']}" if unit["category"] else "") + (f"&page={n}" if n > 1 else "")
        found = gigs_in(ctx.fetcher.text(url))
        new = [g for g in found if g["id"] not in seen]
        seen.update(g["id"] for g in found)
        for g in new:
            gigs[g["id"]] = {k: g.get(k) for k in KEEP}
        if not new:
            break
    sellers: dict[str, list[dict]] = {}
    for g in gigs.values():
        if g.get("userName"):
            sellers.setdefault(g["userName"], []).append(g)
    rows = []
    for name, gs in sellers.items():
        purl = f"https://kwork.ru/user/{name.lower()}"
        try:
            p = profile(ctx.fetcher.text(purl))
        except Exception as e:
            p = {"error": type(e).__name__}
        prices = [float(g["price"]) for g in gs if g.get("price")]
        rows.append({
            "source_id": name, "url": purl, "name": name, "segment": unit["query"], "categories": ["kwork seller"],
            "reviews": max((int(g.get("userRatingCount") or 0) for g in gs), default=None),
            "rating": None, "profile": p,
            "gigs": [{"title": g["gtitle"], "price": g.get("price"), "url": g.get("url")} for g in gs],
            "min_price": min(prices) if prices else None,
        })
    return rows
