"""Official registry lookups by the legal identifiers the site crawl or a source found.

- rkn (RU, no key): Roskomnadzor registry of personal-data operators (pd.rkn.gov.ru), by ИНН. Any business that
  collects personal data must notify RKN first (152-ФЗ ст.22), so "not registered" is a compliance gap and a
  qualifier. Also gives the official operator name. Ported from claude-kit rkn_registry.py.
- companies_house (UK, COMPANIES_HOUSE_API_KEY, free): company profile (status, incorporation date, SIC codes,
  registered address) and current officers, by company number → people with roles, new_registration signal.

Results land in lead["registry"][<name>]; each lookup is cached by the Fetcher, so re-runs cost nothing.
"""
from __future__ import annotations

import base64
import datetime
import html as htmllib
import json
import os
import re
import urllib.parse

from ..core import schema
from ..core.http import Blocked

RKN_URL = "https://pd.rkn.gov.ru/operators-registry/operators-list/?act=search&name_full=&inn={inn}&regn="
CH_API = "https://api.company-information.service.gov.uk"
CH_WEB = "https://find-and-update.company-information.service.gov.uk/company/{n}"

REGISTRIES = {"rkn": {"env": [], "about": "RU personal-data operator registry by ИНН"},
              "companies_house": {"env": ["COMPANIES_HOUSE_API_KEY"], "about": "UK company profile + officers"}}


def _ids(lead: dict, key: str) -> list[str]:
    v = ((lead.get("legal") or {}).get("registry_ids") or {}).get(key)
    return [str(x) for x in (v if isinstance(v, list) else [v] if v else [])]


# --- RKN ------------------------------------------------------------------------------------------------------
def parse_rkn(h: str) -> list[dict]:
    if "ResList1" not in h:
        raise Blocked("rkn: unexpected page (no results table)")
    table = re.search(r'<table[^>]*id="ResList1".*?</table>', h, re.S)
    entries = []
    for row in re.findall(r"<tr class='clmn\d'>(.*?)</tr>", table.group(0) if table else "", re.S):
        cells = [re.sub(r"<[^>]+>", "", re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<br\s*/?>", "|", c)))).strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) < 5:
            continue
        name, *rest = [x.strip() for x in cells[1].split("|") if x.strip()]
        entries.append({"regn": cells[0].strip("| "), "name": name,
                         "kind": next((x for x in rest if not x.startswith("ИНН")), None),
                         "notified": cells[3], "processing_since": cells[4]})
    return entries


def rkn(fetcher, lead: dict) -> dict | None:
    inns = _ids(lead, "inn")[:2]
    if not inns:
        return None
    out = {"checked": datetime.date.today().isoformat(), "by_inn": {}}
    for inn in inns:
        url = RKN_URL.format(inn=inn)
        entries = parse_rkn(fetcher.text(url, ttl=30 * 86400))
        out["by_inn"][inn] = {"registered": bool(entries), "entries": entries, "url": url}
    out["registered"] = any(v["registered"] for v in out["by_inn"].values())
    first = next((v for v in out["by_inn"].values() if v["entries"]), None)
    if first:  # the registry's name for this ИНН beats one read off the site (that can be the bank in the requisites)
        lead.setdefault("legal", {"name": None, "registry_ids": {}})["name"] = first["entries"][0]["name"]
    if not out["registered"]:
        schema.add_signal(lead, "not_in_pd_registry", f"ИНН {', '.join(inns)} not in RKN operator registry",
                          RKN_URL.format(inn=inns[0]))
    return out


# --- Companies House ---------------------------------------------------------------------------------------------
def companies_house(fetcher, lead: dict) -> dict | None:
    nums = [n.upper().zfill(8) if n.isdigit() else n.upper() for n in _ids(lead, "company_number")][:1]
    if not nums:
        return None
    n = nums[0]
    auth = {"Authorization": "Basic " + base64.b64encode((os.environ["COMPANIES_HOUSE_API_KEY"] + ":").encode()).decode()}
    status, _, text = fetcher.request(f"{CH_API}/company/{urllib.parse.quote(n)}", headers=auth, ttl=30 * 86400)
    if status == 404:
        return {"checked": datetime.date.today().isoformat(), "company_number": n, "found": False}
    if status >= 400:
        raise RuntimeError(f"companies house {status}")
    prof = json.loads(text)
    _, _, otext = fetcher.request(f"{CH_API}/company/{urllib.parse.quote(n)}/officers?items_per_page=35", headers=auth,
                                  ttl=30 * 86400)
    try:
        officers = [o for o in json.loads(otext).get("items") or [] if not o.get("resigned_on")]
    except ValueError:
        officers = []
    a = prof.get("registered_office_address") or {}
    out = {
        "checked": datetime.date.today().isoformat(), "found": True, "company_number": n, "url": CH_WEB.format(n=n),
        "name": prof.get("company_name"), "status": prof.get("company_status"), "type": prof.get("type"),
        "incorporated": prof.get("date_of_creation"), "sic_codes": prof.get("sic_codes") or [],
        "address": ", ".join(x for x in (a.get("address_line_1"), a.get("locality"), a.get("postal_code")) if x),
        "officers": [{"name": o.get("name"), "role": o.get("officer_role"), "appointed": o.get("appointed_on")}
                     for o in officers[:10]],
    }
    legal = lead.setdefault("legal", {"name": None, "registry_ids": {}})
    legal["name"] = out["name"] or legal.get("name")  # official name by company number beats the site's
    have = {p.get("name") for p in lead.get("people") or []}
    for o in out["officers"]:
        if o["name"] and o["name"] not in have:
            lead.setdefault("people", []).append({"name": o["name"], "role": o["role"], "source": out["url"]})
    inc = out["incorporated"]
    if inc and inc >= (datetime.date.today() - datetime.timedelta(days=365)).isoformat():
        schema.add_signal(lead, "new_registration", inc, out["url"], inc)
    if out["status"] and out["status"] != "active":
        schema.add_signal(lead, "company_inactive", out["status"], out["url"])
    return out


LOOKUPS = {"rkn": rkn, "companies_house": companies_house}


def missing_env(name: str) -> list[str]:
    return [e for e in REGISTRIES[name]["env"] if not os.environ.get(e)]


def enrich(fetcher, lead: dict, names: list[str]) -> dict:
    reg = lead.setdefault("registry", {})
    for name in names:
        if missing_env(name):
            continue
        try:
            res = LOOKUPS[name](fetcher, lead)
        except Blocked:
            raise
        except Exception as e:
            res = {"checked": datetime.date.today().isoformat(), "error": f"{type(e).__name__}: {e}"[:200]}
        if res is not None:
            reg[name] = res
    return lead
