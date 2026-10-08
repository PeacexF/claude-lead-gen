"""Companies hiring, from Hacker News "Ask HN: Who is hiring?" threads (Algolia API, no key).

Each top-level comment is one company's job post, usually "Company | Role | Location | REMOTE | url".
A hiring company is a buying signal for recruiting, dev shops, tooling, and anything that scales a team.

spec: {type="hn_hiring", months=1, keywords=["python","fintech"], locations=["remote","berlin"]}
keywords / locations: every listed group must match (any word within a group), case-insensitive. Empty = all.
"""
from __future__ import annotations

import html as htmllib
import re

from ..core import schema
from ..core.http import UA_BOT

NAME = "hn_hiring"
KIND = "businesses"
REGIONS = "global (tech)"
ENV: list[str] = []
ABOUT = "Companies posting in HN 'Who is hiring?' threads, filtered by keywords/location. Hiring signal. Free."

SEARCH = "https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&hitsPerPage=40"
ITEM = "https://hn.algolia.com/api/v1/items/{id}"


def units(spec: dict) -> list[dict]:
    return [{"months": int(spec.get("months", 1)), "keywords": spec.get("keywords") or [],
             "locations": spec.get("locations") or []}]


def unit_key(u: dict) -> str:
    return f"last{u['months']}__{'-'.join(u['keywords'])[:40]}__{'-'.join(u['locations'])[:40]}"


def fetcher(camp):
    return camp.fetcher(ua=UA_BOT, delay=1.0)


def text_of(h: str) -> str:
    h = re.sub(r"<p>", "\n", h or "")
    return htmllib.unescape(re.sub(r"<[^>]+>", "", h))


def parse_post(raw_html: str) -> dict:
    t = text_of(raw_html)
    first = t.strip().split("\n", 1)[0]
    parts = [p.strip() for p in first.split("|")]
    links = [htmllib.unescape(u) for u in re.findall(r'href="([^"]+)"', raw_html or "")]
    company = re.sub(r"\s*\(.*?\)\s*$", "", re.sub(r"\s*https?://\S+", "", parts[0])) if parts else ""
    urls_in_head = re.findall(r"https?://[^\s|)]+", first)
    return {"company": company[:120], "headline": first[:300], "parts": parts, "text": t[:3000],
            "links": list(dict.fromkeys(urls_in_head + links)), "head_links": urls_in_head,
            "job_boards": schema.job_boards(" ".join([*urls_in_head, *links]))}


NOT_SITE = re.compile(r"ycombinator\.com|workatastartup\.com|wellfound\.com|lever\.co|greenhouse\.io|ashbyhq|workable|"
                      r"bamboohr|recruitee|personio|teamtailor\.com|smartrecruiters|myworkdayjobs|breezy\.hr|jobvite|"
                      r"rippling-ats|dover\.(com|io)|github\.com|docs\.google|forms\.gle|notion\.(so|site)|calendly\.com",
                      re.I)


def looks_like(host: str, company: str) -> bool:
    """Does a host plausibly belong to the company? (curaihealth.com ~ "Curai"; mercurynews.com !~ "Paramark")"""
    nm = schema.norm_name(company)
    compact = nm.replace(" ", "")
    labels = [x for x in host.lower().split(".")[:-1] if len(x) >= 3 and x != "www"]
    words = [w for w in nm.split() if len(w) >= 4]
    return bool(compact) and any(compact in x or (len(x) >= 4 and x in compact) or any(w in x for w in words)
                                 for x in labels)


def company_site(p: dict) -> str | None:
    """The company's own site: a link in the headline ("Company | Role | ... | url"), or one whose host looks like the
    company name. Posts also link articles, products and docs, which must not become the lead's domain (the merge key)."""
    for u in p["links"]:
        h = schema.host(u)
        if not h or NOT_SITE.search(u) or not schema.is_own_site(u):
            continue
        if u in p["head_links"] or looks_like(h, p["company"]):
            return "https://" + re.sub(r"^(careers|jobs)\.(?=[^.]+\.)", "", h) + "/"  # careers.acme.com → acme.com
    return None


def matches(t: str, groups: list) -> bool:
    low = t.lower()
    for g in groups:
        words = g if isinstance(g, list) else [g]
        if not any(w.lower() in low for w in words):
            return False
    return True


def collect_unit(ctx, unit: dict) -> list[dict]:
    hits = ctx.fetcher.json(SEARCH, ttl=6 * 3600)["hits"]
    threads = [h for h in hits if h["title"].lower().startswith("ask hn: who is hiring")][: unit["months"]]
    rows = []
    for th in threads:
        item = ctx.fetcher.json(ITEM.format(id=th["objectID"]), ttl=6 * 3600)
        for c in item.get("children") or []:
            if not c.get("text"):
                continue
            p = parse_post(c["text"])
            if not p["company"]:
                continue
            if unit["keywords"] and not matches(p["text"], [unit["keywords"]] if isinstance(unit["keywords"][0], str) else unit["keywords"]):
                continue
            if unit["locations"] and not matches(p["headline"], [unit["locations"]]):
                continue
            post_url = f"https://news.ycombinator.com/item?id={c['id']}"
            rows.append({
                "source_id": c["id"], "url": post_url, "name": p["company"],
                "sites": [x for x in [company_site(p)] if x],
                "job_boards": p["job_boards"],
                "emails": re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", p["text"])[:3],
                "segment": "hn_hiring", "categories": ["hiring"],
                "signals": [{"type": "hiring", "value": p["headline"], "source": post_url, "date": (c.get("created_at") or "")[:10]}],
                "hn_thread": th["title"],
            })
    return rows
