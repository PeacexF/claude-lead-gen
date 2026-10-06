"""UK companies from the Companies House advanced search. Free key: COMPANIES_HOUSE_API_KEY.

Finds active companies by SIC code and location, optionally incorporated within a date range, which makes
"newly registered" a buying signal (new firms need sites, accounting, insurance, software...).
Register a key at https://developer.company-information.service.gov.uk/ (free). 600 requests / 5 min.

spec: {type="companies_house", sic_codes=["62012","70229"], locations=["Manchester"],
       incorporated_from="2026-07-01", incorporated_to="", limit=500}
Note: Companies House has no websites or phones; enrich via the website-finding steps in the
contact-discovery skill.
"""
from __future__ import annotations

import base64
import os
import urllib.parse

NAME = "companies_house"
KIND = "businesses"
REGIONS = "UK"
ENV = ["COMPANIES_HOUSE_API_KEY"]
ABOUT = "UK companies by SIC code + location + incorporation date (new-company signal). Free key."

URL = "https://api.company-information.service.gov.uk/advanced-search/companies"


def units(spec: dict) -> list[dict]:
    locs = spec.get("locations") or [""]
    return [{"sic": ",".join(spec.get("sic_codes") or []), "location": loc, "from": spec.get("incorporated_from", ""),
             "to": spec.get("incorporated_to", ""), "limit": int(spec.get("limit", 500))} for loc in locs]


def unit_key(u: dict) -> str:
    return f"{u['location'] or 'UK'}__sic{u['sic'].replace(',', '-')}__{u['from']}_{u['to']}"


def fetcher(camp):
    return camp.fetcher(delay=0.6)


def collect_unit(ctx, unit: dict) -> list[dict]:
    auth = base64.b64encode((os.environ["COMPANIES_HOUSE_API_KEY"] + ":").encode()).decode()
    rows, start = [], 0
    while len(rows) < unit["limit"]:
        q = {"company_status": "active", "size": 100, "start_index": start}
        if unit["sic"]:
            q["sic_codes"] = unit["sic"]
        if unit["location"]:
            q["location"] = unit["location"]
        if unit["from"]:
            q["incorporated_from"] = unit["from"]
        if unit["to"]:
            q["incorporated_to"] = unit["to"]
        data = ctx.fetcher.json(URL + "?" + urllib.parse.urlencode(q), headers={"Authorization": "Basic " + auth})
        items = data.get("items") or []
        for c in items:
            a = c.get("registered_office_address") or {}
            num = c.get("company_number")
            signals = []
            if unit["from"]:
                signals.append({"type": "new_registration", "value": c.get("date_of_creation"),
                                "source": f"https://find-and-update.company-information.service.gov.uk/company/{num}",
                                "date": c.get("date_of_creation")})
            rows.append({
                "source_id": num, "url": f"https://find-and-update.company-information.service.gov.uk/company/{num}",
                "name": c.get("company_name"), "address": ", ".join(x for x in (a.get("address_line_1"), a.get("address_line_2"),
                                                                                  a.get("postal_code")) if x),
                "city": a.get("locality"), "country": "GB", "categories": [f"sic:{s}" for s in c.get("sic_codes") or []],
                "segment": unit["sic"], "legal": {"name": c.get("company_name"), "registry_ids": {"company_number": num}},
                "signals": signals, "incorporated": c.get("date_of_creation"), "company_type": c.get("company_type"),
            })
        start += len(items)
        if not items or start >= int(data.get("hits") or 0):
            break
    return rows[: unit["limit"]]
