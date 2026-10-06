"""Source adapters.

Each adapter module defines:
    NAME     key used in campaign.toml ([[sources]] type = NAME)
    KIND     "businesses" (rows become leads) or "demand" (orders/posts for market research)
    REGIONS  human-readable coverage, e.g. "global", "RU/CIS"
    ENV      env vars it needs (empty = free, no key)
    ABOUT    one line for `leadgen sources`
    units(spec) -> list[dict]            one unit = one cached raw file (e.g. one query × one location)
    unit_key(unit) -> str                file stem for that unit
    collect_unit(ctx, unit) -> list[dict] rows (partial lead records, or demand records)
    ready() -> str | None                optional; None = ready, else why not (missing setup)
    SNAPSHOT = True                      optional; re-collect once per day (live feeds) instead of once ever

The runner writes raw/<source>/<date>/<unit_key>.jsonl and skips units already collected (any date) unless
--refresh, so re-runs only fetch what's missing. A Blocked error stops that source for this run.
"""
from __future__ import annotations

import importlib
import json
import os
import re
import sys
import traceback
from dataclasses import dataclass, field

from ..core.campaign import Campaign, today
from ..core.http import Blocked, Fetcher
from ..core.store import read_jsonl, write_jsonl

MODULES = ["osm", "google_places", "companies_house", "hn_hiring", "file", "yandex_maps", "twogis", "telegram",
           "kwork", "kwork_gigs", "flru", "pchel", "workspace_ru"]


def load(name: str):
    if name not in MODULES:
        raise KeyError(f"unknown source {name!r}; known: {', '.join(MODULES)}")
    return importlib.import_module(f"{__name__}.{name}")


def all_sources():
    return [load(n) for n in MODULES]


def readiness(mod) -> str | None:
    missing = [e for e in getattr(mod, "ENV", []) if not os.environ.get(e)]
    if missing:
        return "missing env: " + ", ".join(missing)
    fn = getattr(mod, "ready", None)
    return fn() if fn else None


def safe_key(s: str) -> str:
    return re.sub(r"[^\w.-]+", "_", s, flags=re.U).strip("_")[:120] or "all"


@dataclass
class Ctx:
    campaign: Campaign
    fetcher: Fetcher
    spec: dict
    log: callable = field(default=lambda msg: print(msg, file=sys.stderr))

    @property
    def config(self) -> dict:
        return self.campaign.config


def already_collected(camp: Campaign, source: str, key: str, today_only: bool = False) -> bool:
    """Business lists are collected once (any date). Snapshot sources (live order feeds) once per day."""
    return any(p.stem == key and (not today_only or p.parent.name == today()) for p in camp.raw_files(source))


def run_source(camp: Campaign, spec: dict, refresh: bool = False, log=None) -> dict:
    log = log or (lambda m: print(m, file=sys.stderr))
    name = spec["type"]
    mod = load(name)
    why = readiness(mod)
    if why:
        log(f"[{name}] skipped: {why}")
        return {"source": name, "skipped": why}
    fetcher = getattr(mod, "fetcher", None)
    ctx = Ctx(camp, fetcher(camp) if fetcher else camp.fetcher(), spec, log)
    stats = {"source": name, "units": 0, "skipped_cached": 0, "rows": 0, "failed": 0, "blocked": None}
    for unit in mod.units(spec):
        key = safe_key(mod.unit_key(unit))
        if not refresh and already_collected(camp, name, key, getattr(mod, "SNAPSHOT", False)):
            stats["skipped_cached"] += 1
            continue
        try:
            rows = mod.collect_unit(ctx, unit)
        except Blocked as e:
            stats["blocked"] = str(e)
            log(f"[{name}] blocked ({e}); stopping this source. Re-run later; finished units are kept.")
            break
        except Exception as e:  # one bad unit must not stop the run
            stats["failed"] += 1
            log(f"[{name}] {key}: FAILED {type(e).__name__}: {e}")
            if os.environ.get("LEADGEN_DEBUG"):
                traceback.print_exc()
            continue
        stamp = today()
        for r in rows:
            r.setdefault("source", name)
            r.setdefault("collected", stamp)
        write_jsonl(camp.raw_dir(name) / f"{key}.jsonl", rows)
        stats["units"] += 1
        stats["rows"] += len(rows)
        log(f"[{name}] {key}: {len(rows)}")
    return stats


def load_raw(camp: Campaign, kind: str = "businesses") -> list[dict]:
    """All raw rows of the given kind; for a unit collected on several dates, the newest snapshot wins."""
    rows = []
    for mod in all_sources():
        if mod.KIND != kind:
            continue
        latest: dict[str, object] = {}
        for p in camp.raw_files(mod.NAME):
            latest[p.stem] = p  # raw_files is sorted, so later dates overwrite
        for p in latest.values():
            rows.extend(read_jsonl(p))
    return rows


def dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1)
