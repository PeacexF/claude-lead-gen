"""2GIS businesses (RU, CIS, plus UAE/Cyprus/Chile... wherever 2GIS runs), no key, no browser. Ported from pdn-lead.

Plain GETs. A search page (`/<city>/search/<query>[/page/N]`) carries 12 branches in its server-rendered state
(`var initialState = JSON.parse('<JS string>')`), with name, address, rubrics, rating and the result total, but no
contacts. The firm page (`/<city>/firm/<id>`) carries the branch's site, phones, emails and messengers. A branch of an
organisation whose firm page was already read in this run reuses its sites instead of another firm page: contacts are
per branch, but the lead is per site.

2GIS sends browsers it thinks are outdated to /museum, so the User-Agent must name a current Chrome
(`core.http.UA_BROWSER`); that redirect raises LayoutChanged with that hint. A page without state is a captcha or a
block: the source stops (Blocked); re-run later and finished units are kept.

spec: {type="twogis", queries=["стоматология"], locations=["kazan"], limit=50, domain="2gis.ru"}
locations: 2GIS city codes as in 2gis.ru/<code> (moscow, spb, kazan, dubai, astana, ...).
"""
from __future__ import annotations

import json
import re
import urllib.parse

from ..core.http import Blocked
from . import LayoutChanged

NAME = "twogis"
KIND = "businesses"
REGIONS = "RU/CIS (+2GIS countries)"
ENV: list[str] = []
ABOUT = "2GIS directory: phones, emails, sites, TG/WA/VK, rating, reviews. Free, plain HTTP."

PER_PAGE = 12
SOCIALS = {"telegram": "telegram", "whatsapp": "whatsapp", "vkontakte": "vk", "instagram": "instagram",
           "facebook": "facebook", "youtube": "youtube", "twitter": "x"}
TRACKING = re.compile(r"^(utm_.*|yclid|gclid|from)$")

_org_sites: dict[str, list[str]] = {}  # organisation id -> sites from its firm page, shared across units in a run


def units(spec: dict) -> list[dict]:
    return [{"query": q, "location": loc, "limit": int(spec.get("limit", 50)), "domain": spec.get("domain", "2gis.ru")}
            for loc in spec.get("locations") or [] for q in spec.get("queries") or []]


def unit_key(u: dict) -> str:
    return f"{u['location']}__{u['query']}"


def fetcher(camp):
    return camp.fetcher(delay=1.0, lang="ru")


# --- parsing (pure) ------------------------------------------------------------------------------------------------
_STATE = re.compile(r"var initialState = JSON\.parse\('(.*?)'\);", re.S)
_JS_ESC = re.compile(r"\\(u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|.)", re.S)
_JS_SIMPLE = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}


def js_unquote(s: str) -> str:
    """Decode the escapes of a single-quoted JavaScript string literal (surrogate pairs joined)."""
    def rep(m):
        e = m.group(1)
        if e[0] in "ux" and len(e) > 1:
            return chr(int(e[1:], 16))
        return _JS_SIMPLE.get(e, e)  # \\ \' \" \/ and anything else stand for themselves
    return _JS_ESC.sub(rep, s).encode("utf-16", "surrogatepass").decode("utf-16", "replace")


def state(html: str) -> dict:
    m = _STATE.search(html)
    if not m:
        if "captcha" in html.lower() or len(html) < 50_000:
            raise Blocked("2gis: no initialState on the page (captcha or block)")
        raise LayoutChanged("2gis: full page without `var initialState = JSON.parse(...)`")
    return json.loads(js_unquote(m.group(1)))


def profiles(st: dict) -> dict[str, dict]:
    """Entity profiles by bare id ("70000001052205260_abc" -> "70000001052205260")."""
    prof = ((st.get("data") or {}).get("entity") or {}).get("profile") or {}
    return {k.split("_", 1)[0]: v["data"] for k, v in prof.items() if isinstance((v or {}).get("data"), dict)}


def total(st: dict) -> int | None:
    for v in (((st.get("data") or {}).get("search") or {}).get("profile") or {}).values():
        t = (v.get("data") or {}).get("total")
        if isinstance(t, int):
            return t
    return None


def clean_url(raw: str) -> str:
    u = urllib.parse.urlsplit(raw)
    if u.hostname == "link.2gis.ru" and "?" in raw:  # click-tracking wrapper: the target follows the "?"
        return clean_url(raw.split("?", 1)[1])
    q = [(k, v) for k, v in urllib.parse.parse_qsl(u.query, keep_blank_values=True) if not TRACKING.match(k)]
    return u._replace(query=urllib.parse.urlencode(q), fragment="").geturl()


def row(d: dict, fid: str, loc: str, query: str, domain: str = "2gis.ru") -> dict:
    adm = {a.get("type"): a.get("name") for a in d.get("adm_div") or []}
    reviews = d.get("reviews") or {}
    point = d.get("point") or {}
    out = {
        "source_id": fid, "url": f"https://{domain}/{loc}/firm/{fid}", "name": d.get("name"),
        "city": adm.get("city") or loc, "country": adm.get("country"), "segment": query,
        "address": ", ".join(x for x in (adm.get("city"), d.get("address_name")) if x) or None,
        "categories": [r["name"] for r in d.get("rubrics") or [] if r.get("name")],
        "rating": reviews.get("general_rating"), "reviews": reviews.get("general_review_count"),
        "lat": point.get("lat"), "lon": point.get("lon"),
        "sites": [], "phones": [], "emails": [], **{k: [] for k in SOCIALS.values()},
    }
    for group in d.get("contact_groups") or []:
        for c in group.get("contacts") or []:
            t, val, link = c.get("type"), c.get("value") or "", c.get("url") or ""
            field, v = None, None
            if t == "website" and (link or val):
                field, v = "sites", clean_url(link or val)
            elif t == "phone" and val:
                field, v = "phones", val
            elif t == "email" and val:
                field, v = "emails", val
            elif t in SOCIALS and (link or val):
                field, v = SOCIALS[t], clean_url(link or val)
            if field and v not in out[field]:
                out[field].append(v)
    return {k: v for k, v in out.items() if v not in ([], None)}


def org_of(d: dict) -> str | None:
    return (d.get("org") or {}).get("id")


# --- collection ----------------------------------------------------------------------------------------------------
def page_state(ctx, url: str) -> dict:
    status, final, html = ctx.fetcher.request(url)
    try:
        if urllib.parse.urlsplit(final).path.startswith("/museum"):
            raise LayoutChanged("2gis sent its outdated-browser page (/museum): update UA_BROWSER in "
                                "leadgen/core/http.py to a current Chrome version")
        if status in (403, 429):
            raise Blocked(f"2gis {status} at {url}")
        if status >= 400:
            raise LayoutChanged(f"2gis {status} at {url}")
        return state(html)
    except (Blocked, LayoutChanged):
        ctx.fetcher.forget(url)  # don't keep the wall in the cache: the next run must ask again
        raise


def collect_unit(ctx, unit: dict) -> list[dict]:
    base = f"https://{unit['domain']}/{unit['location']}"
    search = f"{base}/search/{urllib.parse.quote(unit['query'])}"
    pages = max(1, -(-unit["limit"] // PER_PAGE))
    rows, seen = [], set()
    for p in range(1, pages + 1):
        st = page_state(ctx, search + (f"/page/{p}" if p > 1 else ""))
        found = profiles(st)
        branches = [(fid, d) for fid, d in sorted(found.items()) if d.get("type") == "branch" and fid not in seen]
        for fid, d in branches:
            if len(rows) >= unit["limit"]:
                break
            seen.add(fid)
            org = org_of(d)
            if org and org in _org_sites:  # a branch of an organisation already read: reuse its sites
                r = row(d, fid, unit["location"], unit["query"], unit["domain"])
                if _org_sites[org]:
                    r["sites"] = list(_org_sites[org])
                rows.append(r)
                continue
            firm = profiles(page_state(ctx, f"{base}/firm/{fid}")).get(fid)
            if firm is None:
                ctx.log(f"[twogis] firm {fid}: not in its page state; using the search entry")
                firm = d
            r = row(firm, fid, unit["location"], unit["query"], unit["domain"])
            if org:
                _org_sites[org] = r.get("sites") or []
            rows.append(r)
        n = total(st)
        if len(rows) >= unit["limit"] or len(found) < PER_PAGE or not branches or (n is not None and len(seen) >= n):
            break
    # entries without an admin city (some search-page profiles) got the location code: use the unit's city name
    name = next((r["city"] for r in rows if r.get("city") and r["city"] != unit["location"]), None)
    for r in rows:
        if name and r.get("city") == unit["location"]:
            r["city"] = name
    return rows
