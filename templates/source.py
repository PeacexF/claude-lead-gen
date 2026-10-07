"""<Source name>: <what it lists> (<coverage>). Template for a new source adapter; see the parser-builder skill.

Copy to <workspace>/sources/<name>.py (one-off source) or leadgen/sources/<name>.py (built in; add it to MODULES).
Replace every TODO, delete what you don't need, and keep the docstring accurate:
  - where the data comes from (API / embedded JSON / HTML) and why that path was chosen
  - pagination and the stop rule
  - what the source allows (robots.txt / ToS checked on <date>) and the delay used
  - the spec keys, with an example

spec: {type="<name>", queries=["..."], locations=["..."], max_pages=5}
"""
from __future__ import annotations

import html as htmllib
import json
import re
import urllib.parse

from leadgen.core.http import Blocked, HTTPStatusError
from leadgen.sources import LayoutChanged

NAME = "TODO_name"           # must equal the file name; lowercase, [a-z0-9_]
KIND = "businesses"          # "businesses": rows become leads · "demand": orders/posts for market research
REGIONS = "TODO"             # e.g. "PT", "EU", "global (tech)"
ENV: list[str] = []          # env vars with keys, e.g. ["FOO_API_KEY"]; empty = free
ABOUT = "TODO: one line for `leadgen sources`: what, which fields, free or keyed."
# SNAPSHOT = True            # uncomment for live feeds (orders, posts): re-collect once a day instead of once ever

BASE = "https://TODO.example"


def units(spec: dict) -> list[dict]:
    """One unit = one raw file, collected once. Usually query × location."""
    return [{"query": q, "location": loc, "max_pages": int(spec.get("max_pages", 5))}
            for loc in spec.get("locations") or [None] for q in spec.get("queries") or [None]]


def unit_key(u: dict) -> str:
    """Stable file stem for a unit: same unit → same key, forever (that's what makes re-runs free)."""
    return f"{u['location'] or 'all'}__{u['query'] or 'all'}"


def fetcher(camp):
    # The most conservative rate the source tolerates. Set lang to the source's language.
    # API sources that identify themselves: ua=leadgen.core.http.UA_BOT.
    return camp.fetcher(delay=2.0)


def page_url(unit: dict, page: int) -> str:
    q = {k: v for k, v in (("q", unit["query"]), ("city", unit["location"]), ("page", page)) if v}
    return f"{BASE}/search?{urllib.parse.urlencode(q)}"


def text(fragment: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def parse(payload: str, unit: dict) -> tuple[list[dict], bool]:
    """Pure: one page → (rows, has_next). No I/O, so fixtures can test it.

    Raise LayoutChanged when the structure you rely on is missing, and Blocked when the page is a captcha or
    access wall. Return [] only for a page that is valid but empty (e.g. "no results").
    """
    if "captcha" in payload.lower():  # TODO: the source's real wall marker
        raise Blocked("captcha")
    # --- pattern A: JSON (API, or state embedded in the HTML) -------------------------------------------------
    # m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', payload, re.S)
    # if not m:
    #     raise LayoutChanged("no __NEXT_DATA__ script")
    # items = json.loads(m.group(1))["props"]["pageProps"]["results"]
    # --- pattern B: server-rendered HTML blocks ---------------------------------------------------------------
    marker = 'class="TODO-result-item'
    if marker not in payload:
        if re.search(r"TODO no results text", payload, re.I):
            return [], False
        raise LayoutChanged(f"no {marker!r} blocks")
    rows = []
    for block in payload.split(marker)[1:]:
        name = re.search(r'<h2[^>]*>(.*?)</h2>', block, re.S)            # TODO
        link = re.search(r'href="(/company/[^"]+)"', block)              # TODO: the record's own page = url
        site = re.search(r'data-website="([^"]+)"', block)               # TODO
        phone = re.search(r'href="tel:([^"]+)"', block)
        if not name:
            continue
        rows.append({
            # partial lead record: field names are the ones core/merge.normalize reads
            "source_id": link.group(1).rsplit("/", 1)[-1] if link else None,
            "url": urllib.parse.urljoin(BASE, link.group(1)) if link else None,
            "name": text(name.group(1)),
            "sites": [htmllib.unescape(site.group(1))] if site else [],
            "phones": [phone.group(1)] if phone else [],
            "emails": [],
            "city": unit["location"], "country": None, "address": None,
            "categories": [], "segment": unit["query"],
            # "rating": ..., "reviews": ..., "legal": {"name": ..., "registry_ids": {...}},
            # "linkedin": [...], "instagram": [...], "telegram": [...],     (any key from schema.SOCIAL_KEYS)
            # "signals": [{"type": "new_registration", "value": "...", "source": url, "date": "YYYY-MM-DD"}],
        })
    has_next = 'rel="next"' in payload                                   # TODO: the source's real next marker
    return rows, has_next


def collect_unit(ctx, unit: dict) -> list[dict]:
    rows, seen = [], set()
    for page in range(1, unit["max_pages"] + 1):
        try:
            payload = ctx.fetcher.text(page_url(unit, page))  # live feeds: pass ttl=20 * 3600
        except HTTPStatusError as e:
            if e.code == 404 and page > 1:  # ran past the last page
                break
            raise
        got, has_next = parse(payload, unit)
        new = [r for r in got if r["source_id"] not in seen]
        seen.update(r["source_id"] for r in new)
        rows += new
        if not new or not has_next:  # stop rule: no new ids, or no next page
            break
    return rows


# def ready() -> str | None:
#     """Optional: None when usable, else what setup is missing (external tool, browser...)."""
#     return None


_ = json  # keep the import for pattern A
