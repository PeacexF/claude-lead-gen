"""Companies from OpenCorporates (140+ jurisdictions), keyed: OPENCORPORATES_API_TOKEN.

Company search by jurisdiction, words in the name, industry code and incorporation date, which makes "newly
incorporated in <country>" a source anywhere OpenCorporates has a registry feed. The API has no free self-serve tier
(paid plans, or free access for public-benefit projects on request): https://opencorporates.com/pricing/.
Built from the API reference (v0.4); 401 means the token was refused, 403 is OpenCorporates' rate limit.

The token travels as the `api_token` URL parameter (the API takes it no other way). The Fetcher keeps it out of the
cache and of error messages (`secret_params`).

spec: {type="opencorporates", jurisdictions=["gb", "pt", "us_de"], query="", industry_codes=["eu_nace_2-6201"],
       incorporated_from="2026-07-01", incorporated_to="", limit=200}
  jurisdictions: OpenCorporates codes ("gb", "fr", "us_ca"...). industry_codes: "<scheme>-<code>" as the API lists them.
Like Companies House, registries have no websites or phones: use the contact-discovery skill to find them.
"""
from __future__ import annotations

import json
import os
import urllib.parse

from ..core.http import Blocked

NAME = "opencorporates"
KIND = "businesses"
REGIONS = "global (company registries)"
ENV = ["OPENCORPORATES_API_TOKEN"]
ABOUT = "Companies by jurisdiction + incorporation date + industry code (new-company signal). Paid key."

API = "https://api.opencorporates.com/v0.4"
SECRET = ("api_token",)


def units(spec: dict) -> list[dict]:
    base = {"query": spec.get("query", ""), "industry": ",".join(spec.get("industry_codes") or []),
            "from": spec.get("incorporated_from", ""), "to": spec.get("incorporated_to", ""),
            "limit": int(spec.get("limit", 200))}
    return [{**base, "jurisdiction": j} for j in spec.get("jurisdictions") or [""]]


def unit_key(u: dict) -> str:
    q = "".join(c if c.isalnum() else "-" for c in u["query"])[:40].strip("-")
    return f"{u['jurisdiction'] or 'all'}__{q or 'any'}__{u['industry'].replace(',', '-') or 'any'}__{u['from']}_{u['to']}"


def fetcher(camp):
    return camp.fetcher(delay=1.0)


def get(fetcher, path: str, params: dict) -> dict:
    """GET an API path with the token; raises on refusals without ever printing the token."""
    url = f"{API}/{path}?" + urllib.parse.urlencode({**params, "api_token": os.environ["OPENCORPORATES_API_TOKEN"]})
    status, _, text = fetcher.request(url, secret_params=SECRET)
    if status in (401, 403, 429) or status >= 500:
        fetcher.forget(url, secret_params=SECRET)  # refusals must not be replayed from the cache
    if status == 401:
        raise Blocked("opencorporates: token refused (401); check OPENCORPORATES_API_TOKEN")
    if status in (403, 429):
        raise Blocked(f"opencorporates: rate limited ({status})")
    if status == 404:
        return {}
    if status >= 400:
        raise RuntimeError(f"opencorporates {status} at {API}/{path}")
    return json.loads(text)


def country_of(jurisdiction: str) -> str | None:
    """"gb" -> "GB", "us_de" -> "US"."""
    return jurisdiction.split("_", 1)[0].upper() if jurisdiction else None


def row(c: dict, unit: dict) -> dict:
    jur, num = c.get("jurisdiction_code") or "", c.get("company_number") or ""
    addr = c.get("registered_address") or {}
    ids = {"opencorporates": f"{jur}/{num}"}
    if jur == "gb":
        ids["company_number"] = num  # lets the companies_house registry step read the same company
    signals = []
    if unit.get("from") and c.get("incorporation_date"):
        signals.append({"type": "new_registration", "value": c["incorporation_date"], "source": c.get("opencorporates_url"),
                        "date": c["incorporation_date"]})
    return {
        "source_id": f"{jur}/{num}", "url": c.get("opencorporates_url"), "name": c.get("name"),
        "address": c.get("registered_address_in_full"), "city": addr.get("locality"),
        "country": country_of(jur),
        "categories": [f"{(i.get('industry_code') or {}).get('code_scheme_id')}:{(i.get('industry_code') or {}).get('code')}"
                       for i in c.get("industry_codes") or [] if (i.get("industry_code") or {}).get("code")],
        "segment": unit.get("query") or unit.get("industry") or None,
        "legal": {"name": c.get("name"), "registry_ids": ids}, "signals": signals,
        "incorporated": c.get("incorporation_date"), "company_type": c.get("company_type"),
        "status": c.get("current_status"),
    }


def collect_unit(ctx, unit: dict) -> list[dict]:
    q = {"per_page": 100, "order": "incorporation_date" if unit["from"] or unit["to"] else "score", "inactive": "false"}
    if unit["query"]:
        q["q"] = unit["query"]
    if unit["jurisdiction"]:
        q["jurisdiction_code"] = unit["jurisdiction"]
    if unit["industry"]:
        q["industry_codes"] = unit["industry"]
    if unit["from"] or unit["to"]:
        q["incorporation_date"] = f"{unit['from']}:{unit['to']}"
    rows, page = [], 1
    while len(rows) < unit["limit"] and page <= 100:  # the API serves at most 100 pages
        res = get(ctx.fetcher, "companies/search", {**q, "page": page}).get("results") or {}
        items = [x.get("company") or {} for x in res.get("companies") or []]
        rows += [row(c, unit) for c in items]
        if not items or page >= int(res.get("total_pages") or 0):
            break
        page += 1
    return rows[: unit["limit"]]
