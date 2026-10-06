"""Yandex Maps businesses (RU/CIS), no key. Ported from claude-kit.

Plain GET of the public search page; results are in the embedded state JSON (<script class="state-view">),
25 per page, paginated with ?page=N. A page without state JSON is a captcha: the source stops (Blocked)
so we don't hammer Yandex; re-run later and finished units are kept.

spec: {type="yandex_maps", queries=["стоматология"], locations=["kazan", "moscow"], pages=4}
locations: a key from CITIES, or a raw "<region id>/<slug>" taken from a yandex.ru/maps URL.
"""
from __future__ import annotations

import json
import re
import urllib.parse

from ..core.http import Blocked

NAME = "yandex_maps"
KIND = "businesses"
REGIONS = "RU/CIS"
ENV: list[str] = []
ABOUT = "Yandex Maps businesses: site, phones, Telegram/WhatsApp/VK, rating, reviews. Free; captcha-sensitive."

CITIES = {"moscow": "213/moscow", "spb": "2/saint-petersburg", "kazan": "43/kazan", "n_novgorod": "47/nizhny-novgorod",
          "voronezh": "193/voronezh", "yaroslavl": "16/yaroslavl", "tula": "15/tula", "ivanovo": "5/ivanovo",
          "kostroma": "7/kostroma", "ekaterinburg": "54/yekaterinburg", "novosibirsk": "65/novosibirsk",
          "krasnodar": "35/krasnodar", "samara": "51/samara", "rostov": "39/rostov-na-donu", "ufa": "172/ufa",
          "chelyabinsk": "56/chelyabinsk", "perm": "50/perm", "krasnoyarsk": "62/krasnoyarsk", "tyumen": "55/tyumen",
          "volgograd": "38/volgograd", "omsk": "66/omsk", "sochi": "239/sochi", "kaliningrad": "22/kaliningrad",
          "irkutsk": "63/irkutsk", "vladivostok": "75/vladivostok", "minsk": "157/minsk", "almaty": "162/almaty",
          "astana": "163/astana", "tashkent": "10335/tashkent"}


def units(spec: dict) -> list[dict]:
    return [{"query": q, "location": loc, "pages": int(spec.get("pages", 4))}
            for loc in spec.get("locations") or [] for q in spec.get("queries") or []]


def unit_key(u: dict) -> str:
    return f"{u['location'].replace('/', '-')}__{u['query']}"


def fetcher(camp):
    return camp.fetcher(delay=4.0, lang="ru")


def region(loc: str) -> str:
    if loc in CITIES:
        return CITIES[loc]
    if re.match(r"^\d+/[\w-]+$", loc):
        return loc
    raise ValueError(f"unknown Yandex city {loc!r}; use a key from CITIES or '<id>/<slug>' from a yandex.ru/maps URL")


def parse_state(html: str) -> dict:
    m = re.search(r'<script type="application/json" class="state-view">(.*?)</script>', html, re.S)
    if not m:
        raise Blocked("yandex captcha / no state JSON")
    return json.loads(m.group(1))["stack"][0].get("results") or {}


def normalize(it: dict, city: str, query: str) -> dict:
    socials = {s.get("type"): s.get("href") for s in it.get("socialLinks") or []}
    rating = it.get("ratingData") or {}
    return {
        "source_id": it.get("id"), "name": it.get("title"), "city": city, "segment": query,
        "address": it.get("fullAddress") or it.get("address"),
        "categories": [c.get("name") for c in it.get("categories") or []],
        "phones": [p.get("value") or p.get("number") for p in it.get("phones") or []],
        "sites": [re.sub(r"[?#].*$", "", u) for u in it.get("urls") or []],  # drop utm/yclid tails
        "telegram": socials.get("telegram"), "whatsapp": re.sub(r"\?.*$", "", socials.get("whatsapp") or "") or None,
        "vk": socials.get("vkontakte"), "instagram": socials.get("instagram"), "facebook": socials.get("facebook"),
        "rating": rating.get("ratingValue"), "reviews": rating.get("reviewCount"),
        "url": f"https://yandex.ru/maps/org/{it.get('seoname')}/{it.get('id')}/",
        "lat": (it.get("coordinates") or [None, None])[1], "lon": (it.get("coordinates") or [None, None])[0],
        "country": None,
    }


def collect_unit(ctx, unit: dict) -> list[dict]:
    reg = region(unit["location"])
    rows, seen = [], set()
    for p in range(1, unit["pages"] + 1):
        url = f"https://yandex.ru/maps/{reg}/search/{urllib.parse.quote(unit['query'])}/" + (f"?page={p}" if p > 1 else "")
        res = parse_state(ctx.fetcher.text(url))
        items = [i for i in res.get("items") or [] if i.get("type") == "business"]
        new = [i for i in items if i.get("id") not in seen]
        seen.update(i.get("id") for i in new)
        rows += [normalize(i, unit["location"], unit["query"]) for i in new]
        if not new or len(seen) >= (res.get("totalResultCount") or 0):
            break
    return rows
