"""Open roles from public ATS job boards (Greenhouse, Lever, Ashby), no key → hiring signal.

Board tokens come from links, which are certain: the ones the site crawl found (site.job_boards) and the ones a source
saw in the company's own post (job_boards, e.g. an HN "Who is hiring?" comment). Then, only for leads with a domain,
from guesses built from the domain and company name (e.g. acme.com → "acme"). A guessed board is only accepted when it
demonstrably belongs to the company: Greenhouse's company name on the postings matches, or the postings mention the
company's domain or name. Otherwise a common token like "apex" would attach some other company's jobs to the lead.
A lead without a domain gets no guesses: a board found from the name alone would always "prove" that same name.
"""
from __future__ import annotations

import datetime
import json
import re
import urllib.parse

from ..core import schema

APIS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{t}/jobs",  # no content=true: big boards exceed the cap
    "lever": "https://api.lever.co/v0/postings/{t}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{t}",
}
TTL = 3 * 86400  # roles change; re-check every few days


def guesses(lead: dict) -> list[str]:
    out = []
    if lead.get("domain"):
        label = lead["domain"].split(".")[0]
        out += [label, label.replace("-", "")]
    nm = schema.norm_name(lead.get("name"))
    if nm:
        out += [nm.replace(" ", ""), nm.replace(" ", "-")]
    return [t for t in dict.fromkeys(out) if re.fullmatch(r"[a-z0-9][a-z0-9-]{1,60}", t)]


def _get(fetcher, url: str):
    status, _, text = fetcher.request(url, ttl=TTL)
    if status == 404:
        return None
    if status >= 400:
        raise RuntimeError(f"HTTP {status}")
    return json.loads(text)


def fetch_board(fetcher, ats: str, token: str) -> list[dict] | None:
    """Normalized open roles, or None when the board doesn't exist."""
    data = _get(fetcher, APIS[ats].format(t=urllib.parse.quote(token)))
    if data is None:
        return None
    if ats == "greenhouse":
        jobs = [{"title": j.get("title"), "location": (j.get("location") or {}).get("name"), "url": j.get("absolute_url"),
                 "posted": (j.get("first_published") or j.get("updated_at") or "")[:10], "company": j.get("company_name"),
                 "text": ""} for j in data.get("jobs") or []]
    elif ats == "lever":
        jobs = [{"title": j.get("text"), "location": (j.get("categories") or {}).get("location"), "url": j.get("hostedUrl"),
                 "posted": datetime.datetime.fromtimestamp(j["createdAt"] / 1000, datetime.UTC).date().isoformat()
                 if j.get("createdAt") else None, "team": (j.get("categories") or {}).get("team"),
                 "text": (j.get("descriptionPlain") or "")[:1500]} for j in data if isinstance(j, dict)]
    else:
        jobs = [{"title": j.get("title"), "location": j.get("location"), "url": j.get("jobUrl"),
                 "posted": (j.get("publishedAt") or "")[:10], "team": j.get("department"),
                 "text": (j.get("descriptionPlain") or "")[:1500]} for j in data.get("jobs") or [] if j.get("isListed", True)]
    return jobs


def belongs(jobs: list[dict], lead: dict) -> bool:
    nm = schema.norm_name(lead.get("name"))
    dom = lead.get("domain") or ""
    if nm and any(schema.norm_name(j.get("company")) == nm for j in jobs[:5]):
        return True
    blob = " ".join(f"{j.get('text')} {j.get('company') or ''} {j.get('url') or ''}" for j in jobs[:10]).lower()
    return bool((dom and dom in blob) or (nm and len(nm) >= 4 and re.search(r"\b" + re.escape(nm) + r"\b", schema.norm_name(blob))))


def enrich(fetcher, lead: dict) -> dict:
    found = []
    for how, links in (("site", (lead.get("site") or {}).get("job_boards")), ("source", lead.get("job_boards"))):
        found += [(b["ats"], b["token"], how) for b in links or [] if b["ats"] in APIS
                  and (b["ats"], b["token"]) not in {(a, t) for a, t, _ in found}]
    if lead.get("domain"):
        tried = {(a, t) for a, t, _ in found}
        found += [(a, t, "guess") for t in guesses(lead) for a in APIS if (a, t) not in tried]
    boards, errors = [], []
    for ats, token, how in found:
        try:
            jobs = fetch_board(fetcher, ats, token)
        except Exception as e:
            errors.append(f"{ats}/{token}: {type(e).__name__}")
            continue
        if jobs is None or not jobs:
            continue
        if how == "guess" and not belongs(jobs, lead):
            continue
        boards.append({"ats": ats, "token": token, "found_via": how, "open_roles": len(jobs),
                       "roles": [{k: j.get(k) for k in ("title", "location", "team", "url", "posted")} for j in jobs[:25]]})
        if len(boards) >= 2:
            break
    lead["jobs"] = {"boards": boards, "open_roles": sum(b["open_roles"] for b in boards), "errors": errors[:5],
                    "checked": datetime.date.today().isoformat()}
    if boards:
        b = boards[0]
        titles = ", ".join(list(dict.fromkeys(r["title"].strip() for r in b["roles"] if r.get("title")))[:5])
        schema.add_signal(lead, "hiring", f"{lead['jobs']['open_roles']} open roles ({b['ats']}): {titles}",
                          b["roles"][0].get("url") or b["ats"])
    return lead
