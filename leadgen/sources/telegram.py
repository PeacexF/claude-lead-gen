"""Public Telegram channel posts via the t.me/s/<channel> web preview (no account). Ported from claude-kit.

Use for order/tender channels, industry news channels, or a competitor's channel. Posts land as demand
records (title = first line, description = rest, budget parsed when stated).

spec: {type="telegram", channels=["some_orders_channel"], pages=30}
"""
from __future__ import annotations

import html as htmllib
import re

NAME = "telegram"
KIND = "demand"
REGIONS = "global"
ENV: list[str] = []
SNAPSHOT = True
ABOUT = "Public Telegram channel posts (t.me/s preview, no account). Orders, news, competitor channels."


def units(spec: dict) -> list[dict]:
    return [{"channel": c.lstrip("@").removeprefix("https://t.me/"), "pages": int(spec.get("pages", 30))}
            for c in spec.get("channels") or []]


def unit_key(u: dict) -> str:
    return u["channel"]


def fetcher(camp):
    return camp.fetcher(delay=2.0)


def text(fragment: str) -> str:
    t = re.sub(r"<br\s*/?>", "\n", fragment)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"[ \t]+", " ", htmllib.unescape(t)).strip()


def budget_from_text(t: str) -> float | None:
    m = re.search(r"(?:бюджет|оплата|цена|стоимость|budget|rate|pay)[^0-9]{0,20}(\d[\d \xa0,]{2,9})\s*(?:₽|руб|р\b|rub|\$|usd|€|eur)",
                  t, re.I)
    return float(re.sub(r"\D", "", m.group(1))) if m else None


def parse(page: str, channel: str) -> list[dict]:
    posts = []
    for block in page.split('class="tgme_widget_message_wrap')[1:]:
        pid = re.search(rf'data-post="{re.escape(channel)}/(\d+)"', block, re.I)
        body = re.search(r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', block, re.S)
        date = re.search(r'<time[^>]*datetime="([^"]+)"', block)
        views = re.search(r'tgme_widget_message_views">([^<]+)<', block)
        if not pid or not body:
            continue
        t = text(body.group(1))
        first, _, rest = t.partition("\n")
        posts.append({"source_id": int(pid.group(1)), "url": f"https://t.me/{channel}/{pid.group(1)}", "channel": channel,
                      "created": date.group(1) if date else None, "views": views.group(1) if views else None,
                      "title": first[:200], "description": rest[:3000], "budget": budget_from_text(t),
                      "budget_max": None, "currency": None, "category": None, "offers": None, "type": "post"})
    return posts


def collect_unit(ctx, unit: dict) -> list[dict]:
    seen, rows, before = set(), [], None
    for _ in range(unit["pages"]):
        url = f"https://t.me/s/{unit['channel']}" + (f"?before={before}" if before else "")
        posts = [p for p in parse(ctx.fetcher.text(url, ttl=20 * 3600), unit["channel"]) if p["source_id"] not in seen]
        if not posts:
            break
        seen.update(p["source_id"] for p in posts)
        rows += posts
        before = min(p["source_id"] for p in posts)
    return sorted(rows, key=lambda r: r["source_id"])
