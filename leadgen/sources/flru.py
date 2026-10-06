"""FL.ru project listings (RU freelance demand). Ported from claude-kit.

Walks /projects/page-N/ until a page brings no new projects or max_pages.
spec: {type="flru", max_pages=60}
"""
from __future__ import annotations

import html as htmllib
import re
import urllib.error

NAME = "flru"
KIND = "demand"
REGIONS = "RU"
ENV: list[str] = []
SNAPSHOT = True
ABOUT = "FL.ru projects: budget, type (project/vacancy/contest), offers. Demand signal."


def units(spec: dict) -> list[dict]:
    return [{"max_pages": int(spec.get("max_pages", 60))}]


def unit_key(u: dict) -> str:
    return "projects"


def fetcher(camp):
    return camp.fetcher(delay=2.0, lang="ru")


def text(fragment: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def parse_budget(s: str) -> tuple[int | None, int | None]:
    nums = [int(re.sub(r"\D", "", n)) for n in re.findall(r"\d[\d \xa0]*", s)]
    return (nums[0], nums[-1]) if nums else (None, None)


def parse(page_html: str) -> list[dict]:
    rows = []
    for block in page_html.split('qa-project-name="project-item')[1:]:
        pid = re.match(r"(\d+)", block)
        if not pid:
            continue
        title_m = re.search(r'id="prj_name_\d+"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        price_m = re.search(r'b-post__price[^"]*">(.*?)</div>', block, re.S)
        desc_m = re.search(r'class="b-post__txt text-5 ">(.*?)</div>', block, re.S)
        foot = text(block.rsplit("Откликнуться", 1)[-1])[:300]
        price = text(price_m.group(1)) if price_m else ""
        lo, hi = parse_budget(price) if "₽" in price else (None, None)
        offers_m = re.search(r"(\d+)\s+ответ", foot)
        rows.append({
            "source_id": int(pid.group(1)), "url": "https://www.fl.ru" + title_m.group(1) if title_m else None,
            "title": text(title_m.group(2)) if title_m else None, "description": text(desc_m.group(1)) if desc_m else "",
            "price_text": price, "budget": lo, "budget_max": hi, "currency": "RUB" if lo else None, "category": None,
            "type": "vacancy" if foot.startswith("Вакансия") else "contest" if foot.startswith("Конкурс") else "project",
            "offers": int(offers_m.group(1)) if offers_m else 0,
            "created": foot.split(" назад")[0][-40:] if " назад" in foot else None,
        })
    return rows


def collect_unit(ctx, unit: dict) -> list[dict]:
    seen, rows = set(), []
    for page in range(1, unit["max_pages"] + 1):
        try:
            h = ctx.fetcher.text(f"https://www.fl.ru/projects/page-{page}/", ttl=20 * 3600)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                break
            raise
        new = [r for r in parse(h) if r["source_id"] not in seen]
        if not new:
            break
        seen.update(r["source_id"] for r in new)
        rows += new
    return rows
