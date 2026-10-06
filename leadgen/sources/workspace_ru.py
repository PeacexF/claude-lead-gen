"""workspace.ru tenders: RU businesses posting digital projects with budgets. Ported from claude-kit.

The catalog only server-renders 10 tenders, so the list comes from the public-tenders sitemap; the newest N
detail pages are parsed (title, description, budget, dates, status, required service, participants,
customer type and city). Customers here are businesses, so tenders double as warm leads.

spec: {type="workspace_ru", newest=500}
"""
from __future__ import annotations

import html as htmllib
import re

NAME = "workspace_ru"
KIND = "demand"
REGIONS = "RU"
ENV: list[str] = []
SNAPSHOT = True
ABOUT = "workspace.ru tenders: budget, service, participants, customer city. Demand signal."

SITEMAP = "https://workspace.ru/sitemap-tenders-public-items.xml"


def units(spec: dict) -> list[dict]:
    return [{"newest": int(spec.get("newest", 500))}]


def unit_key(u: dict) -> str:
    return f"tenders_{u['newest']}"


def fetcher(camp):
    return camp.fetcher(delay=2.0, lang="ru")


def parse_budget(s: str) -> tuple[int | None, int | None]:
    nums = [int(re.sub(r"\D", "", n)) for n in re.findall(r"\d[\d \xa0]*", s)]
    if not nums:
        return None, None
    return (None, nums[0]) if s.startswith("до") else (nums[0], nums[-1])


def after(t: str, label: str, n: int = 1) -> str | None:
    m = re.search(re.escape(label) + r":? \|((?: [^|]+ \|){%d})" % n, t)
    return m.group(1).strip(" |") if m else None


def parse_detail(h: str) -> dict:
    h = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", h, flags=re.S)
    t = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " | ", h)))
    t = re.sub(r"(\|\s*)+", "| ", t)
    title_m = re.search(r"<h1[^>]*>\s*(.*?)\s*<", h, re.S)
    title = htmllib.unescape(title_m.group(1)).strip() if title_m else None
    desc = None
    if title:
        m = re.search(r"Разместить похожий тендер \| " + re.escape(title) + r" \|(.*?)\| Бюджет:", t)
        desc = m.group(1).replace(" | ", "\n").strip(" |") if m else None
    price = after(t, "Бюджет") or ""
    lo, hi = parse_budget(price)
    part_m = re.search(r"В тендере участвуют \|(.*?)\| Реклама", t)
    city_m = re.search(r"организован заказчиком из ([^.|]+)\.", t)
    return {
        "title": title, "description": (desc or "")[:4000], "price_text": price, "budget": lo, "budget_max": hi,
        "currency": "RUB" if (lo or hi) else None, "created": after(t, "Опубликован"),
        "deadline": after(t, "Крайний срок приема заявок"), "status": "open" if "Идет прием заявок" in t else "closed",
        "category": after(t, "Требуемая услуга"),
        "offers": len([p for p in part_m.group(1).split("|") if p.strip() and p.strip() != "PRO"]) if part_m else 0,
        "customer_type": after(t, "Oрганизатор") or after(t, "Организатор"),
        "customer_city": city_m.group(1).strip() if city_m else None, "type": "tender",
    }


def collect_unit(ctx, unit: dict) -> list[dict]:
    xml = ctx.fetcher.text(SITEMAP, ttl=20 * 3600)
    urls = {int(m.group(2)): m.group(1) for m in
            re.finditer(r"<loc>(https://workspace\.ru/tenders/(?!private-tender)[^<]*-(\d+)/)</loc>", xml)}
    rows = []
    for tid in sorted(urls, reverse=True)[: unit["newest"]]:
        try:
            rows.append({"source_id": tid, "url": urls[tid], **parse_detail(ctx.fetcher.text(urls[tid]))})
        except Exception as e:
            ctx.log(f"[workspace_ru] {urls[tid]}: {type(e).__name__}")
    return rows
