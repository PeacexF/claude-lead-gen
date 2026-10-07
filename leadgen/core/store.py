"""JSONL read/write and the flat CSV export of leads."""
from __future__ import annotations

import csv
import json
import os
import pathlib
import tempfile
from typing import Iterable, Iterator


def read_jsonl(path: pathlib.Path) -> Iterator[dict]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def write_jsonl(path: pathlib.Path, rows: Iterable[dict]) -> int:
    """Atomic write (temp file + rename) so a crash never leaves a half-written leads file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    os.replace(tmp, path)
    return n


def append_jsonl(path: pathlib.Path, rows: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    return n


CSV_COLUMNS = ["id", "tier", "score", "status", "name", "website", "domain", "country", "city", "address",
               "categories", "segment", "email", "emails", "phone", "phones", "linkedin", "facebook", "instagram", "x",
               "telegram", "whatsapp", "vk", "people", "legal_name", "registry_ids", "rating", "reviews",
               "site_reachable", "site_https", "site_builder", "site_tech", "signals", "score_breakdown", "sources", "notes"]


def flatten(lead: dict) -> dict:
    socials = lead.get("socials") or {}
    site = lead.get("site") or {}
    emails = [e["value"] if isinstance(e, dict) else e for e in lead.get("emails") or []]
    first = lambda xs: xs[0] if xs else ""  # noqa: E731
    return {
        "id": lead.get("id"), "tier": lead.get("tier"), "score": lead.get("score"), "status": lead.get("status"),
        "name": lead.get("name"), "website": lead.get("website"), "domain": lead.get("domain"),
        "country": lead.get("country"), "city": lead.get("city"), "address": lead.get("address"),
        "categories": "; ".join(lead.get("categories") or []), "segment": lead.get("segment"),
        "email": first(emails), "emails": "; ".join(emails),
        "phone": first(lead.get("phones") or []), "phones": "; ".join(lead.get("phones") or []),
        **{k: first(socials.get(k) or []) for k in ("linkedin", "facebook", "instagram", "x", "telegram", "whatsapp", "vk")},
        "people": "; ".join(f"{p.get('name')} ({p.get('role') or '?'})" for p in lead.get("people") or []),
        "legal_name": (lead.get("legal") or {}).get("name"),
        "registry_ids": "; ".join(f"{k}={v}" for k, v in ((lead.get("legal") or {}).get("registry_ids") or {}).items()),
        "rating": lead.get("rating"), "reviews": lead.get("reviews"),
        "site_reachable": site.get("reachable"), "site_https": site.get("https"), "site_builder": site.get("builder"),
        "site_tech": "; ".join(site.get("tech") or []),
        "signals": "; ".join(f"{s.get('type')}:{s.get('value')}" for s in lead.get("signals") or []),
        "score_breakdown": "; ".join(f"{k}={v}" for k, v in (lead.get("score_breakdown") or {}).items()),
        "sources": "; ".join(sorted({s.get("source", "") for s in lead.get("sources") or []})),
        "notes": lead.get("notes"),
    }


FORMULA_START = ("=", "+", "-", "@", "\t", "\r", "\n", "＝", "＋", "－", "＠")


def csv_cell(v):
    """Neutralize spreadsheet formulas: scraped text like '=HYPERLINK(...)' must stay text in Excel/Sheets.

    Checks the value after leading whitespace too (' =1+1'), since some spreadsheet apps trim before parsing.
    """
    if isinstance(v, str) and (v.startswith(FORMULA_START) or v.lstrip().startswith(FORMULA_START)):
        return "'" + v
    return v


def csv_safe(row: dict) -> dict:
    return {k: csv_cell(v) for k, v in row.items()}


def write_csv(path: pathlib.Path, leads: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for lead in leads:
            w.writerow(csv_safe(flatten(lead)))
            n += 1
    return n
