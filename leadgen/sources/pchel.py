"""pchel.net project listings (RU/CIS freelance demand). Ported from claude-kit.

spec: {type="pchel", max_pages=40}
"""
from __future__ import annotations

import html as htmllib
import re

NAME = "pchel"
KIND = "demand"
REGIONS = "RU/CIS"
ENV: list[str] = []
SNAPSHOT = True
ABOUT = "pchel.net projects: budget (RUB/USD), categories, offers. Demand signal."


def units(spec: dict) -> list[dict]:
    return [{"max_pages": int(spec.get("max_pages", 40))}]


def unit_key(u: dict) -> str:
    return "projects"


def fetcher(camp):
    return camp.fetcher(delay=2.0, lang="ru")


def text(fragment: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def parse(page_html: str) -> list[dict]:
    rows = []
    for block in page_html.split('name="project_id" value="')[1:]:
        pid = re.match(r"(\d+)", block)
        if not pid:
            continue
        title_m = re.search(r'class="project-title">(?:<img[^>]*>)*<a href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        desc_m = re.search(r'class="project-text">(.*?)</div>', block, re.S)
        price_m = re.search(r'class="price">(?:<div class="no-mobile">)?(.*?)</div>', block, re.S)
        cats = re.findall(r'<a href="/jobs/[a-z0-9-]+/" class="b-link">(.*?)</a>', block.split("project-block-cov")[0])
        offers_m = re.search(r'class="p-user" title="(\d+)', block)
        price = text(price_m.group(1)) if price_m else ""
        nums = [int(re.sub(r"\D", "", n)) for n in re.findall(r"\d[\d \xa0]*", price)]
        rows.append({
            "source_id": int(pid.group(1)), "url": "https://pchel.net" + title_m.group(1) if title_m else None,
            "title": text(title_m.group(2)) if title_m else None, "description": text(desc_m.group(1)) if desc_m else "",
            "price_text": price, "budget": nums[0] if nums else None, "budget_max": nums[-1] if nums else None,
            "currency": "USD" if "$" in price else "RUB" if nums else None,
            "category": "; ".join(text(c) for c in cats) or None, "offers": int(offers_m.group(1)) if offers_m else 0,
            "created": None, "type": "project",
        })
    return rows


def collect_unit(ctx, unit: dict) -> list[dict]:
    seen, rows = set(), []
    for page in range(1, unit["max_pages"] + 1):
        h = ctx.fetcher.text("https://pchel.net/jobs/" + (f"page-{page}/" if page > 1 else ""), ttl=20 * 3600)
        new = [r for r in parse(h) if r["source_id"] not in seen]
        if not new:
            break
        seen.update(r["source_id"] for r in new)
        rows += new
    return rows
