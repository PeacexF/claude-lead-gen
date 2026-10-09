"""Niche research tables: demand (orders, tenders, posts) × supply (leads) → products, clusters, segments, scores.

Ported from claude-kit (normalize_orders, label_orders, clusters, segments, score) and generalized. Reads a
campaign's raw rows from KIND = "demand" sources and its leads.jsonl, and writes campaigns/<slug>/market/:

    orders.jsonl    every order once (the latest snapshot wins), normalized and labeled with a product type
    products.json   orders per product type: count, budgets, offers
    clusters.json   orders per [[market.clusters]] regex, with every URL and title for checking by hand
    segments.json   supply per lead segment: own site, socials only, messengers, email, site issues, top tech
    scores.json     [[market.segments]] ranked by demand × gap × reach, with the formula

No network, no model: the same raw data and config give the same tables. The niche-research skill reads the
orders behind a number before it goes into a niche card.

A demand row (from any KIND = "demand" adapter, built in or workspace) uses these keys, all optional:
    source_id, url, title, description, budget, budget_max, currency, category, offers, created, type, channel
"""
from __future__ import annotations

import collections
import datetime
import html
import pathlib
import re
import statistics

from . import sources
from .core.campaign import Campaign
from .core.store import read_jsonl, write_json, write_jsonl

# First match wins, on lowercase title + description + category. [[market.products]] rules are tried first.
# RU patterns from claude-kit, plus English equivalents.
DEFAULT_PRODUCTS: list[tuple[str, str]] = [
    ("telegram_bot", r"телеграм[- ]?бот|telegram[- ]?бот|бот[а-я]* (в|для) (телеграм|telegram|tg)|\bтг[- ]?бот|чат[- ]?бот|"
                     r"\bбот\b|\bбота\b|mini ?app|мини[- ]?апп|telegram bot|chat ?bot|discord bot|whatsapp bot|\bbots?\b"),
    ("parser_scraper", r"парс(ер|инг|ить)|скрап|scrap|сбор (данных|базы|контакт)|выгрузк|crawler|data extraction|\bparser\b|"
                       r"zenno|зенно"),
    ("crm_integration", r"amo ?crm|амо ?срм|битрикс|bitrix|\bcrm\b|\bсрм\b|интеграц|\bapi\b|вебхук|webhook|\b1с\b|\b1c\b|"
                        r"мойсклад|retailcrm|\bб24\b|\bb24\b|телефони[яюи]|hubspot|salesforce|pipedrive|zoho|integrat"),
    ("ai_automation", r"нейросет|\bии\b|\bai\b|gpt|chatgpt|llm|n8n|make\.com|автоматизац|zapier|automat|openai|ai agent"),
    ("mobile_app", r"мобильн[а-я]* приложен|android|андро[иі]д|\bios\b|айос|flutter|react native|google play|app store|"
                   r"rustore|mobile app|приложени[еяю] (для|под)"),
    ("marketplace_ecom", r"wildberries|\bwb\b|озон|ozon|маркетплейс|интернет[- ]магазин|woocommerce|insales|shopify|"
                         r"карточ[а-я]* товар|amazon|etsy|e-?commerce|online store|marketplace"),
    ("site_fix", r"доработ|исправ|ошибк|баг|почин|перенос сайт|ускор|оптимизац[а-я]* скорост|не работает|правк|"
                 r"\bfix|\bbug|broken|not working|speed up|migrat"),
    ("web_app", r"личн[а-я]* кабинет|\bphp\b|laravel|django|\breact\b|\bvue\b|javascript|фронт[- ]?энд|бэк[- ]?энд|"
                r"frontend|front-end|backend|веб[- ]?(приложен|сервис)|web ?app|\bsaas\b|dashboard|admin panel|админк"),
    ("landing_site", r"лендинг|landing|сайт|tilda|тильд|wordpress|вордпресс|верстк|верстать|website|web site|webflow|"
                     r"\bwix\b|squarespace|framer"),
    ("script_tool", r"скрипт|python|питон|программ[а-я]* для|расширени[ея] (для )?(хром|браузер)|chrome extension|excel|"
                    r"google ?(таблиц|sheets)|макрос|\bscript|spreadsheet|macro|browser extension"),
    ("game", r"\bигр[аыу]\b|unity|unreal|геймдев|roblox|\bgame\b"),
    ("design", r"дизайн|логотип|баннер|фигма|figma|иллюстрац|макет|инфографик|обложк|презентац|design|\blogo|banner|"
               r"illustrat|mockup|presentation"),
    ("video_audio", r"видео|монтаж|ролик|reels|анимац|озвуч|подкаст|трек|video|animation|voice ?over|podcast"),
    ("seo_ads", r"\bseo\b|сео|продвижен|директ|таргет|реклам|трафик|ссылк|контекст|google ads|facebook ads|meta ads|"
                r"\bppc\b|traffic|backlink"),
    ("smm_content", r"smm|контент|ведени[ея]|пост[ыо]в|статьи|копирайт|текст|рерайт|сторис|инстаграм|вконтакт|\bвк\b|дзен|"
                    r"content|copywrit|article|blog post|social media"),
    ("leadgen_sales", r"клиент|лид|продаж|холодн|обзвон|рассылк|менеджер по продаж|поиск заказчик|lead gen|\bleads\b|"
                      r"cold (email|call)|appointment setting|\bsales\b"),
]

MESSENGERS = ("telegram", "whatsapp", "max")
STOP = set("""и в во не на с со что как для по из от до за к ко о об а но или же ли бы то это все так уже при без
под над про через нужно нужен нужна нужны надо есть будет можно который которые которая чтобы если также только
очень более сделать необходимо требуется задача задачи работа работы проект проекта проекту заказ заказа ищем ищу
делать создать разработка разработать человек каждый оплата формат срочно опыт работать задание нужен нам наш наша
наши мне меня вас вам ваш ваши свой своих один одна одно день дней есть было будет может хочу хотим примерно где
the and for with that this from have need needs are you your our will can into who what want looking help would
should about there their they them been more some any all also just like work project task job using use create
make build please each per day days one new get its it's has was were which when how""".split())


class MarketError(ValueError):
    pass


def _rx(pattern: str, what: str) -> re.Pattern:
    try:
        return re.compile(pattern, re.I)
    except re.error as e:
        raise MarketError(f"{what}: bad regex {pattern!r}: {e}") from e


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if 0 < f < float("inf") else None  # NaN, inf and 0 ("no budget") count as missing


def clean(s) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(s or "")))).strip()


def order_date(v) -> datetime.date | None:
    """ISO date/datetime, DD.MM.YYYY, or a unix timestamp. Relative text ("2 часа назад") gives None."""
    if isinstance(v, (int, float)) and v > 1e9:
        try:
            return datetime.datetime.fromtimestamp(v / 1000 if v > 1e12 else v, datetime.timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
    s = str(v or "")
    if re.fullmatch(r"\d{10}(\d{3})?", s):
        return order_date(int(s))
    for rx, fmt in ((r"\d{4}-\d{2}-\d{2}", "%Y-%m-%d"), (r"\d{2}\.\d{2}\.\d{4}", "%d.%m.%Y")):
        m = re.search(rx, s)
        if m:
            try:
                return datetime.datetime.strptime(m.group(0), fmt).date()
            except ValueError:
                return None
    return None


def text_of(o: dict) -> str:
    return f"{o.get('title') or ''} {o.get('description') or ''} {o.get('category') or ''}".lower()


# --- orders --------------------------------------------------------------------------------------------------------
def normalize(r: dict, source: str, day: str) -> dict:
    budget, bmax = _num(r.get("budget")), _num(r.get("budget_max"))
    offers = r.get("offers")
    oid = r.get("url") or f"{source}:{r.get('source_id')}"
    return {
        "id": oid, "source": source, "url": r.get("url"), "channel": r.get("channel"),
        "title": clean(r.get("title"))[:300], "description": clean(r.get("description"))[:4000],
        "category": clean(r.get("category")) or None,
        "budget": budget, "budget_max": bmax, "value": budget or bmax,  # the stated minimum, else the stated maximum
        "currency": (str(r["currency"]).upper() if r.get("currency") else None),
        "offers": int(offers) if isinstance(offers, (int, float)) or str(offers or "").isdigit() else None,
        "type": r.get("type") or "order", "created": r.get("created"),
        "date": (d.isoformat() if (d := order_date(r.get("created"))) else None),
        "first_seen": day, "last_seen": day,
    }


def load_orders(camp: Campaign, log=None) -> tuple[list[dict], dict]:
    """Every demand row across all snapshot dates, once per id (the latest snapshot wins), filtered by [market]."""
    log = log or (lambda m: None)
    cfg = camp.config["market"]
    named = sources.configured(camp)
    by_id: dict[str, dict] = {}
    for name in sources.collected_sources(camp):
        try:
            mod = sources.load(name, camp.root, workspace_ok=name in named)
        except KeyError as e:
            log(f"[market] raw/{name} skipped: {e}")
            continue
        if mod.KIND != "demand":
            continue
        for p in camp.raw_files(name):  # sorted, so later dates overwrite earlier ones
            day = p.relative_to(camp.dir / "raw" / name).parts[0]
            for r in read_jsonl(p):
                o = normalize(r, name, day)
                prev = by_id.get(o["id"])
                if prev:
                    o["first_seen"] = min(prev["first_seen"], day)
                by_id[o["id"]] = o
    max_age = int(cfg.get("max_age_days") or 0)
    cutoff = (datetime.date.today() - datetime.timedelta(days=max_age)).isoformat() if max_age else None
    excluded = set(cfg.get("exclude_types") or [])
    out, dropped = [], {"older": 0, "excluded_type": 0}
    for o in by_id.values():
        if o["type"] in excluded:
            dropped["excluded_type"] += 1
        elif cutoff and o["date"] and o["date"] < cutoff:
            dropped["older"] += 1
        else:
            out.append(o)
    return out, dropped


def product_rules(cfg: dict) -> list[tuple[str, re.Pattern]]:
    rules = []
    for r in cfg.get("products") or []:
        if not r.get("name") or not r.get("matches"):
            raise MarketError(f"[[market.products]] needs name and matches: {r}")
        rules.append((r["name"], _rx(r["matches"], f"product {r['name']!r}")))
    if cfg.get("default_products", True):
        rules += [(n, re.compile(p, re.I)) for n, p in DEFAULT_PRODUCTS]
    return rules


def label(orders: list[dict], rules) -> None:
    for o in orders:
        t = text_of(o)
        o["product"] = next((n for n, rx in rules if rx.search(t)), "other")


def main_currency(orders: list[dict], cfg: dict) -> str | None:
    if cfg.get("currency"):
        return cfg["currency"].upper()
    c = collections.Counter(o["currency"] for o in orders if o["value"] and o["currency"])
    return c.most_common(1)[0][0] if c else None


def convert(orders: list[dict], currency: str | None, rates: dict) -> dict:
    """amount = the order's value in the main currency: as is, or × [market] rates[cur]; else None (left out of
    budget stats). Returns the count of budgets left out per currency."""
    rates = {k.upper(): float(v) for k, v in (rates or {}).items()}
    left: collections.Counter = collections.Counter()
    for o in orders:
        cur = o["currency"]
        if not o["value"]:
            o["amount"] = None
        elif cur == currency:
            o["amount"] = o["value"]
        elif cur in rates:
            o["amount"] = round(o["value"] * rates[cur], 2)
        else:
            o["amount"] = None
            left[cur or "unknown"] += 1
    return dict(left)


def _q(vals: list[float], q: float) -> float:
    return vals[min(len(vals) - 1, int(len(vals) * q))]


def stats(orders: list[dict]) -> dict:
    """Budget quantiles in the main currency (see convert; vacancy salaries never count) and median offers."""
    vals = sorted(o["amount"] for o in orders if o.get("amount") and o["type"] != "vacancy")
    offers = [o["offers"] for o in orders if o["offers"] is not None]
    return {"orders": len(orders), "with_budget": len(vals),
            "median_budget": statistics.median(vals) if vals else None,
            "p25_budget": _q(vals, .25) if vals else None, "p75_budget": _q(vals, .75) if vals else None,
            "median_offers": statistics.median(offers) if offers else None}


def products(orders: list[dict]) -> dict:
    groups: dict[str, list[dict]] = collections.defaultdict(list)
    for o in orders:
        groups[o["product"]].append(o)
    n = len(orders) or 1
    return {name: {**stats(g), "share_pct": round(100 * len(g) / n, 1),
                   "sources": dict(collections.Counter(o["source"] for o in g))}
            for name, g in sorted(groups.items(), key=lambda kv: -len(kv[1]))}


def match(orders: list[dict], rx: re.Pattern, product=None) -> list[dict]:
    prods = {product} if isinstance(product, str) else set(product or [])
    return [o for o in orders if (not prods or o.get("product") in prods) and rx.search(text_of(o))]


def clusters(orders: list[dict], cfg: dict) -> dict:
    out = {}
    n = len(orders) or 1
    for c in cfg.get("clusters") or []:
        if not c.get("name") or not c.get("matches"):
            raise MarketError(f"[[market.clusters]] needs name and matches: {c}")
        hit = match(orders, _rx(c["matches"], f"cluster {c['name']!r}"), c.get("product"))
        out[c["name"]] = {**stats(hit), "share_pct": round(100 * len(hit) / n, 1), "note": c.get("note"),
                          "matches": c["matches"], "urls": [o["url"] for o in hit],
                          "titles": [o["title"][:100] for o in hit]}
    return out


# --- supply --------------------------------------------------------------------------------------------------------
def pct(k: int, n: int) -> float:
    return round(100 * k / n, 1) if n else 0.0


def site_issue(lead: dict, issues: list[str]) -> bool:
    site = lead.get("site") or {}
    sig = {s.get("type") for s in lead.get("signals") or []}
    return any((i == "unreachable" and site.get("reachable") is False) or i in sig for i in issues)


def supply_metrics(leads: list[dict], issues: list[str]) -> dict:
    """Shares over one group of leads. gap_pct = no own site + (of the rest) a crawled site with an issue."""
    n = len(leads)
    socials = lambda l: l.get("socials") or {}  # noqa: E731
    own = [l for l in leads if l.get("website")]
    crawled = [l for l in own if (l.get("site") or {}).get("checked")]
    bad = sum(1 for l in crawled if site_issue(l, issues))
    no_own = pct(n - len(own), n)
    issue_pct = pct(bad, len(crawled)) if crawled else None
    tech = collections.Counter(t for l in crawled for t in set((l.get("site") or {}).get("tech") or []))
    ratings = [float(l["rating"]) for l in leads if l.get("rating")]
    reviews = [int(l["reviews"]) for l in leads if l.get("reviews") is not None]
    return {
        "n": n, "own_site_pct": pct(len(own), n), "no_own_site_pct": no_own,
        "social_only_pct": pct(sum(1 for l in leads if not l.get("website") and any(socials(l).values())), n),
        "messenger_pct": pct(sum(1 for l in leads if any(socials(l).get(k) for k in MESSENGERS)), n),
        "phone_pct": pct(sum(1 for l in leads if l.get("phones")), n),
        "email_pct": pct(sum(1 for l in leads if l.get("emails")), n),
        "sites_crawled": len(crawled), "site_issue_pct": issue_pct,
        "gap_pct": round(no_own + (issue_pct or 0) * (1 - no_own / 100), 1),
        "median_rating": round(statistics.median(ratings), 2) if ratings else None,
        "median_reviews": statistics.median(reviews) if reviews else None,
        "top_tech": [[t, pct(k, len(crawled))] for t, k in tech.most_common(8)],
    }


def segments(leads: list[dict], cfg: dict) -> dict:
    issues = list(cfg.get("site_issues") or [])
    groups: dict[str, list[dict]] = collections.defaultdict(list)
    for l in leads:
        groups[l.get("segment") or "(none)"].append(l)
    out = {}
    for seg, g in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        cities: dict[str, list[dict]] = collections.defaultdict(list)
        for l in g:
            cities[l.get("city") or "(none)"].append(l)
        out[seg] = {**supply_metrics(g, issues),
                    "cities": {c: supply_metrics(x, issues) for c, x in sorted(cities.items(), key=lambda kv: -len(kv[1]))}}
    return out


# --- score ---------------------------------------------------------------------------------------------------------
SEG_KEYS = {"name", "demand", "supply", "product", "control", "note"}


def score(orders: list[dict], leads: list[dict], cfg: dict) -> dict:
    """[[market.segments]] ranked by weighted, max-normalized demand, gap and reach (minus competition)."""
    w = cfg.get("score") or {}
    weights = {k: float(w.get(k, d)) for k, d in (("demand", .4), ("gap", .3), ("reach", .3), ("competition", 0))}
    gap_m, reach_m = w.get("gap_metric", "gap_pct"), w.get("reach_metric", "messenger_pct")
    issues = list(cfg.get("site_issues") or [])
    numeric = sorted(k for k, v in supply_metrics([], issues).items() if k != "top_tech")
    if gap_m not in numeric or reach_m not in numeric:
        raise MarketError(f"[market.score] gap_metric and reach_metric must be one of {numeric}")
    table = []
    for s in cfg.get("segments") or []:
        unknown = set(s) - SEG_KEYS
        if unknown or not s.get("name") or not s.get("demand"):
            raise MarketError(f"[[market.segments]] needs name and demand (allowed keys {sorted(SEG_KEYS)}): {s}")
        hits = match(orders, _rx(s["demand"], f"segment {s['name']!r} demand"), s.get("product"))
        if s.get("supply"):
            rx = _rx(s["supply"], f"segment {s['name']!r} supply")
            group = [l for l in leads if rx.search(" ".join([l.get("segment") or ""] + list(l.get("categories") or [])))]
        else:
            group = [l for l in leads if (l.get("segment") or "").lower() == s["name"].lower()]
        m = supply_metrics(group, issues) if group else None
        st = stats(hits)
        table.append({
            "segment": s["name"], "control": bool(s.get("control")), "note": s.get("note"),
            "demand_orders": len(hits), "median_budget": st["median_budget"], "with_budget": st["with_budget"],
            "median_offers": st["median_offers"], "businesses": len(group),
            "gap": m[gap_m] if m else None, "reach": m[reach_m] if m else None,
            "supply": m, "order_urls": [o["url"] for o in hits],
        })
    ranked = [t for t in table if not t["control"]]

    def mx(k):
        return max((t[k] or 0 for t in ranked), default=0) or 1
    top = {"demand": mx("demand_orders"), "gap": mx("gap"), "reach": mx("reach"), "competition": mx("median_offers")}
    for t in table:
        parts = {"demand": (t["demand_orders"] or 0) / top["demand"], "gap": (t["gap"] or 0) / top["gap"],
                 "reach": (t["reach"] or 0) / top["reach"], "competition": -(t["median_offers"] or 0) / top["competition"]}
        t["components"] = {k: round(v, 3) for k, v in parts.items()}
        t["score"] = round(sum(weights[k] * v for k, v in parts.items()), 3)
    table.sort(key=lambda t: (t["control"], -t["score"]))
    formula = (f"score = {weights['demand']}·orders/max + {weights['gap']}·{gap_m}/max + {weights['reach']}·{reach_m}/max"
               + (f" − {weights['competition']}·median_offers/max" if weights["competition"] else "")
               + "   (max over non-control segments; a segment without supply data gets 0 for gap and reach)")
    return {"formula": formula, "weights": weights, "gap_metric": gap_m, "reach_metric": reach_m, "segments": table}


# --- commands ------------------------------------------------------------------------------------------------------
def market_dir(camp: Campaign) -> pathlib.Path:
    return camp.dir / "market"


def prepare(camp: Campaign, log=None) -> tuple[list[dict], dict, str | None]:
    """Orders loaded, labeled and converted. dropped also counts budgets left out for lack of a rate."""
    cfg = camp.config["market"]
    orders, dropped = load_orders(camp, log)
    label(orders, product_rules(cfg))
    cur = main_currency(orders, cfg)
    dropped["no_rate"] = convert(orders, cur, cfg.get("rates") or {})
    return orders, dropped, cur


def scan(camp: Campaign, log=None) -> dict:
    cfg = camp.config["market"]
    orders, dropped, cur = prepare(camp, log)
    leads = list(read_jsonl(camp.leads_path))
    d = market_dir(camp)
    res = {
        "dir": str(d), "generated": datetime.date.today().isoformat(), "currency": cur,
        "rates": cfg.get("rates") or {}, "orders": len(orders),
        "dropped": dropped, "by_source": dict(collections.Counter(o["source"] for o in orders)),
        "snapshots": sorted({o["last_seen"] for o in orders}),
        "products": products(orders), "clusters": clusters(orders, cfg),
        "segments": segments(leads, cfg) if leads else {}, "leads": len(leads),
        "scores": score(orders, leads, cfg) if cfg.get("segments") else None,
    }
    write_jsonl(d / "orders.jsonl", sorted(orders, key=lambda o: (o["source"], o["id"])))
    for name in ("products", "clusters", "segments", "scores"):
        write_json(d / f"{name}.json", {"generated": res["generated"], "currency": cur, "rates": res["rates"],
                                        name: res[name]})
    return res


def select(orders: list[dict], cfg: dict, product=None, cluster=None, pattern=None, source=None,
           min_budget=None) -> list[dict]:
    if cluster:
        c = next((c for c in cfg.get("clusters") or [] if c.get("name") == cluster), None)
        if not c:
            raise MarketError(f"no [[market.clusters]] named {cluster!r}")
        orders = match(orders, _rx(c["matches"], f"cluster {cluster!r}"), c.get("product"))
    if product:
        orders = [o for o in orders if o["product"] in product]
    if pattern:
        rx = _rx(pattern, "--match")
        orders = [o for o in orders if rx.search(text_of(o))]
    if source:
        orders = [o for o in orders if o["source"] in source]
    if min_budget:
        orders = [o for o in orders if (o["amount"] or 0) >= min_budget]
    return orders


def terms(orders: list[dict], n: int = 40) -> dict:
    """Most common words and word pairs, counted once per order: a cheap map of what's being bought."""
    words, pairs = collections.Counter(), collections.Counter()
    for o in orders:
        toks = [t for t in re.findall(r"[^\W\d_]{3,}", f"{o['title']} {o['description']}".lower()) if t not in STOP]
        words.update(set(t for t in toks if len(t) >= 4))
        pairs.update(set(f"{a} {b}" for a, b in zip(toks, toks[1:]) if a != b))
    return {"orders": len(orders), "words": words.most_common(n), "pairs": [p for p in pairs.most_common(n) if p[1] > 1]}
