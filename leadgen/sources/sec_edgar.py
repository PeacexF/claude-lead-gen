"""US companies from SEC EDGAR filings, no key. Form D by default: private companies that just raised money.

EDGAR full-text search (efts.sec.gov) finds filings by form, date range, business state and words in the text; each
company (CIK) found is then read once:
- Form D (`primary_doc.xml`): issuer address and phone, executive officers / directors / promoters, industry group,
  revenue range, offering and sold amounts, year of incorporation → a `funding` signal and `people`.
- Any other form: the company's submissions record (data.sec.gov): business address, phone, SIC description, website
  when the filer gave one.

EDGAR has no websites for most filers, so these leads usually need the website-finding steps of the
contact-discovery skill before the site crawl can run.

The SEC requires a User-Agent that names you and gives a contact email ("Jane Doe jane@example.com"):
set SEC_EDGAR_UA. Fair access is 10 requests/second; the adapter stays well below it.

spec: {type="sec_edgar", forms=["D"], query="", states=["TX", "CA"], days=30, limit=200, amendments=false,
       skip_industries=["Pooled Investment Fund"]}
  query: EDGAR full-text search words ("software", "\"dental practice\""); empty = every filing of the form.
  states: business-address states (two-letter codes); empty = all. filed_from / filed_to (YYYY-MM-DD) override days.
  skip_industries: Form D industry groups left out. Funds raise money too, but they don't buy services; [] keeps all.
"""
from __future__ import annotations

import datetime
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET

NAME = "sec_edgar"
KIND = "businesses"
REGIONS = "US"
ENV = ["SEC_EDGAR_UA"]
ABOUT = "US companies from SEC filings; Form D = just raised money (amounts, executives, phone). Free, contact UA."

EFTS = "https://efts.sec.gov/LATEST/search-index"
ARCHIVES = "https://www.sec.gov/Archives/edgar/data/{cik}/{adsh}/{file}"
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik10}.json"
COMPANY = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"
PAGE = 100  # EFTS returns 100 hits per request


def _dates(spec: dict) -> tuple[str, str]:
    to = spec.get("filed_to") or datetime.date.today().isoformat()
    frm = spec.get("filed_from") or (datetime.date.fromisoformat(to) - datetime.timedelta(days=int(spec.get("days", 30)))).isoformat()
    return frm, to


def units(spec: dict) -> list[dict]:
    frm, to = _dates(spec)
    base = {"forms": ",".join(spec.get("forms") or ["D"]), "query": spec.get("query", ""), "from": frm, "to": to,
            "limit": int(spec.get("limit", 200)), "amendments": bool(spec.get("amendments", False)),
            "skip": list(spec.get("skip_industries", ["Pooled Investment Fund"]))}
    return [{**base, "state": s} for s in spec.get("states") or [""]]


def unit_key(u: dict) -> str:
    q = re.sub(r"\W+", "-", u["query"]).strip("-")[:40]
    return f"{u['state'] or 'US'}__{u['forms'].replace(',', '-').replace('/', '')}__{q or 'all'}__{u['from']}_{u['to']}"


def fetcher(camp):
    return camp.fetcher(ua=os.environ["SEC_EDGAR_UA"], delay=0.25)


# --- parsing (pure) ------------------------------------------------------------------------------------------------
def search_url(unit: dict, offset: int = 0) -> str:
    q = {"forms": unit["forms"], "dateRange": "custom", "startdt": unit["from"], "enddt": unit["to"]}
    if unit["query"]:
        q["q"] = unit["query"]
    if unit["state"]:
        q.update({"locationType": "located", "locationCodes": unit["state"]})
    if offset:
        q["from"] = offset
    return EFTS + "?" + urllib.parse.urlencode(q)


def filings(data: dict, amendments: bool = False) -> list[dict]:
    """EFTS hits → one entry per filing: cik, adsh, file, form, filed, place."""
    out = []
    for h in (data.get("hits") or {}).get("hits") or []:
        s = h.get("_source") or {}
        if not amendments and str(s.get("form", "")).endswith("/A"):
            continue
        adsh, _, file = str(h.get("_id", "")).partition(":")
        ciks = s.get("ciks") or []
        if not (adsh and ciks):
            continue
        out.append({"cik": str(int(ciks[0])), "adsh": adsh, "file": file, "form": s.get("form"),
                    "filed": s.get("file_date"), "place": (s.get("biz_locations") or [None])[0],
                    "name": re.sub(r"\s*\(CIK \d+\)\s*$", "", (s.get("display_names") or [""])[0]).strip()})
    return out


def _t(el, path: str) -> str | None:
    x = el.find(path) if el is not None else None
    return x.text.strip() if x is not None and x.text and x.text.strip() else None


def _money(v: str | None) -> str | None:
    return None if v is None else (f"${int(v):,}" if v.isdigit() else v)


def _phone(raw: str | None, us: bool = True) -> list[str]:
    """EDGAR phones are bare digits; a 10-digit US number gets +1 so merge reads it as international."""
    d = re.sub(r"\D", "", raw or "")
    return [f"+1{d}" if us and len(d) == 10 else raw] if d else []


def _place(street: str | None, city: str | None, state: str | None, zipc: str | None) -> str | None:
    return ", ".join(x for x in (street, city, " ".join(y for y in (state, zipc) if y)) if x) or None


def parse_xml(xml: str) -> ET.Element:
    # stdlib only, so no defusedxml: ElementTree never fetches external entities, and refusing any DTD rules out
    # entity-expansion bombs. Form D documents have none.
    if re.search(r"<!(DOCTYPE|ENTITY)", xml, re.I):
        raise ValueError("XML with a DTD refused")
    return ET.fromstring(xml)


def form_d(xml: str, f: dict) -> dict:
    root = parse_xml(xml)
    iss = root.find("primaryIssuer")
    addr = iss.find("issuerAddress") if iss is not None else None
    off = root.find("offeringData")
    city = _t(addr, "city")
    filing = ARCHIVES.format(cik=f["cik"], adsh=f["adsh"].replace("-", ""), file=f["file"] or "primary_doc.xml")
    people = []
    for p in root.findall("relatedPersonsList/relatedPersonInfo"):
        name = " ".join(x for x in (_t(p, "relatedPersonName/firstName"), _t(p, "relatedPersonName/middleName"),
                                    _t(p, "relatedPersonName/lastName")) if x)
        roles = [r.text.strip() for r in p.findall("relatedPersonRelationshipList/relationship") if r.text]
        if name:
            people.append({"name": name, "role": ", ".join(roles) or None, "source": filing})
    total, sold = _t(off, "offeringSalesAmounts/totalOfferingAmount"), _t(off, "offeringSalesAmounts/totalAmountSold")
    first_sale = _t(off, "typeOfFiling/dateOfFirstSale/value")
    value = f"Form D {f['filed']}: {_money(sold) or '?'} sold of {_money(total) or '?'} offered" + \
            (f", first sale {first_sale}" if first_sale else "")
    industry = _t(off, "industryGroup/industryGroupType")
    name = _t(iss, "entityName") or f["name"]
    return {
        "source_id": f["cik"], "url": COMPANY.format(cik=f["cik"]), "name": name,
        "address": _place(_t(addr, "street1"), city, _t(addr, "stateOrCountry"), _t(addr, "zipCode")),
        "city": city.title() if city and city.isupper() else city, "country": "US",
        "phones": _phone(_t(iss, "issuerPhoneNumber"), (_t(addr, "stateOrCountry") or "").isalpha()),
        "categories": [c for c in [industry] if c], "segment": industry,
        "legal": {"name": name, "registry_ids": {"cik": f["cik"]}},
        "people": people,
        "signals": [{"type": "funding", "value": value, "source": filing, "date": f["filed"]}],
        "incorporated": _t(iss, "yearOfInc/value"), "entity_type": _t(iss, "entityType"),
        "jurisdiction": _t(iss, "jurisdictionOfInc"), "revenue_range": _t(off, "issuerSize/revenueRange"),
        "offering_total": total, "offering_sold": sold,
    }


def submissions(data: dict, f: dict) -> dict:
    a = (data.get("addresses") or {}).get("business") or {}
    city = a.get("city")
    name = data.get("name") or f["name"]
    return {
        "source_id": f["cik"], "url": COMPANY.format(cik=f["cik"]), "name": name,
        "address": _place(a.get("street1"), city, a.get("stateOrCountry"), a.get("zipCode")),
        "city": city.title() if city and city.isupper() else city,
        "country": "US" if not a.get("isForeignLocation") else a.get("countryCode"),
        "phones": _phone(data.get("phone"), not a.get("isForeignLocation")),
        "sites": [w for w in [data.get("website")] if w],
        "categories": [c for c in [data.get("sicDescription")] if c], "segment": data.get("sicDescription"),
        "legal": {"name": name, "registry_ids": {"cik": f["cik"]}},
        "signals": [{"type": "sec_filing", "value": f"{f['form']} filed {f['filed']}",
                     "source": ARCHIVES.format(cik=f["cik"], adsh=f["adsh"].replace("-", ""), file=f["file"]),
                     "date": f["filed"]}],
        "tickers": data.get("tickers") or [],
    }


# --- collection ----------------------------------------------------------------------------------------------------
def collect_unit(ctx, unit: dict) -> list[dict]:
    seen: dict[str, dict] = {}  # cik -> its latest filing (EFTS sorts newest first)
    offset = 0
    while len(seen) < unit["limit"]:
        data = ctx.fetcher.json(search_url(unit, offset))
        page = (data.get("hits") or {}).get("hits") or []
        for f in filings(data, unit["amendments"]):
            seen.setdefault(f["cik"], f)
        offset += len(page)
        total = int(((data.get("hits") or {}).get("total") or {}).get("value") or 0)
        if len(page) < PAGE or offset >= total:
            break
    rows = []
    for f in list(seen.values())[: unit["limit"]]:
        try:
            if f["form"] in ("D", "D/A") and f["file"].endswith(".xml"):
                xml = ctx.fetcher.text(ARCHIVES.format(cik=f["cik"], adsh=f["adsh"].replace("-", ""), file=f["file"]))
                r = form_d(xml, f)
                if r["segment"] in unit.get("skip", []):
                    continue
                rows.append(r)
            else:
                rows.append(submissions(ctx.fetcher.json(SUBMISSIONS.format(cik10=f["cik"].zfill(10))), f))
        except (ET.ParseError, ValueError, RuntimeError) as e:
            ctx.log(f"[sec_edgar] CIK {f['cik']} {f['adsh']}: {type(e).__name__}: {e}"[:200])
    return rows
