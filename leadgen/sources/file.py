"""Import your own list (CSV or JSONL): exports from CRMs, directories, trade-show lists, Apify runs, hand-made sheets.

Column names are matched case-insensitively against common aliases (name/company, website/url/domain,
phone, email, city, country, address, linkedin, ...). Unknown columns are kept under "extra".

spec: {type="file", paths=["imports/expo-2026.csv"], segment="expo"}
"""
from __future__ import annotations

import csv
import json
import pathlib
import re

NAME = "file"
KIND = "businesses"
REGIONS = "any"
ENV: list[str] = []
ABOUT = "Import a CSV/JSONL list you already have (CRM export, directory, Apify output)."

ALIASES = {
    "name": ["name", "company", "company name", "business", "business name", "organization", "organisation", "title"],
    "sites": ["website", "site", "url", "domain", "web", "homepage", "websiteuri"],
    "phones": ["phone", "telephone", "tel", "phone number", "mobile", "phonenumber"],
    "emails": ["email", "e-mail", "emails", "mail", "email address"],
    "city": ["city", "town", "locality"],
    "country": ["country", "country code"],
    "address": ["address", "street", "full address", "formatted address"],
    "categories": ["category", "categories", "industry", "type", "categoryname"],
    "linkedin": ["linkedin", "linkedin url", "company linkedin"],
    "facebook": ["facebook"], "instagram": ["instagram"], "telegram": ["telegram"], "whatsapp": ["whatsapp"],
    "rating": ["rating", "totalscore", "stars"], "reviews": ["reviews", "reviews count", "reviewscount", "review count"],
}
LIST_FIELDS = {"sites", "phones", "emails", "categories", "linkedin", "facebook", "instagram", "telegram", "whatsapp"}


def units(spec: dict) -> list[dict]:
    return [{"path": p, "segment": spec.get("segment")} for p in spec.get("paths") or []]


def unit_key(u: dict) -> str:
    return pathlib.Path(u["path"]).name


def _rows(path: pathlib.Path):
    if path.suffix.lower() in (".jsonl", ".ndjson"):
        return [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else data.get("items") or []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        sample = fh.read(4096)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        return list(csv.DictReader(fh, dialect=dialect))


def map_row(raw: dict, segment: str | None) -> dict:
    low = {re.sub(r"[_\s]+", " ", str(k)).strip().lower(): v for k, v in raw.items()}
    out, used = {}, set()
    for field, names in ALIASES.items():
        for n in names:
            if n in low and low[n] not in (None, "", []):
                v = low[n]
                if field in LIST_FIELDS:
                    vals = v if isinstance(v, list) else re.split(r"\s*[;,|]\s*", str(v))
                    out.setdefault(field, []).extend(x for x in vals if x)
                elif field in ("rating", "reviews"):
                    try:
                        out[field] = float(v) if field == "rating" else int(float(v))
                    except (TypeError, ValueError):
                        pass
                else:
                    out.setdefault(field, v)
                used.add(n)
    out["extra"] = {k: v for k, v in low.items() if k not in used and v not in (None, "")}
    out["segment"] = segment or out.get("segment")
    return out


def collect_unit(ctx, unit: dict) -> list[dict]:
    p = pathlib.Path(unit["path"])
    if not p.is_absolute():
        p = (ctx.campaign.dir / p) if (ctx.campaign.dir / p).exists() else (ctx.campaign.root / p)
    rows = [map_row(r, unit["segment"]) for r in _rows(p)]
    for i, r in enumerate(rows):
        r["source_id"] = f"{p.name}:{i + 1}"
        r["url"] = None
    return [r for r in rows if r.get("name") or r.get("sites")]
