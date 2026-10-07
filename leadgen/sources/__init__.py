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
--refresh, so re-runs only fetch what's missing. A Blocked error stops that source for this run. LayoutChanged
(raised by an adapter's parser when the page/API structure it expects is gone) fails the unit loudly instead of
returning 0 rows; two in a row stop the source.

Workspace adapters: <workspace>/leadgen_sources/<name>.py with the same contract, for one-off sources that don't belong
in the plugin (see the parser-builder skill). They are code from the workspace, so they load only when the campaign's
campaign.toml names them in [[sources]] (never to list them, never for an unconfigured raw/ directory), and every load
is logged with its path. Built-in names win.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import pathlib
import re
import sys
import traceback
from dataclasses import dataclass, field

from ..core.campaign import Campaign, today, workspace
from ..core.http import Blocked, Fetcher
from ..core.store import read_jsonl, write_jsonl

MODULES = ["osm", "google_places", "companies_house", "hn_hiring", "file", "yandex_maps", "twogis", "telegram",
           "kwork", "kwork_gigs", "flru", "pchel", "workspace_ru"]


REQUIRED = ("NAME", "KIND", "REGIONS", "ABOUT", "units", "unit_key", "collect_unit")
_workspace_mods: dict[pathlib.Path, object] = {}


class LayoutChanged(Exception):
    """The structure a parser relies on is missing (markup, JSON shape, endpoint). Fix the adapter; don't retry."""


WORKSPACE_DIR = "leadgen_sources"  # distinctive on purpose: a generic sources/ folder in some repo must never run


def workspace_dir(root: pathlib.Path | None = None) -> pathlib.Path:
    return (root or workspace()) / WORKSPACE_DIR


def _load_file(path: pathlib.Path):
    path = path.resolve()
    if path in _workspace_mods:
        return _workspace_mods[path]
    spec = importlib.util.spec_from_file_location(f"leadgen_workspace_sources.{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    print(f"[sources] loading workspace adapter {path}", file=sys.stderr)
    spec.loader.exec_module(mod)
    missing = [a for a in REQUIRED if not hasattr(mod, a)]
    if missing:
        raise KeyError(f"workspace adapter {path} lacks {', '.join(missing)} (see templates/source.py)")
    if mod.NAME != path.stem:
        raise KeyError(f"workspace adapter {path}: NAME = {mod.NAME!r} must match the file name {path.stem!r}")
    if mod.KIND not in ("businesses", "demand"):
        raise KeyError(f"workspace adapter {path}: KIND must be 'businesses' or 'demand', got {mod.KIND!r}")
    mod.ENV = getattr(mod, "ENV", [])
    mod.WORKSPACE = str(path)
    _workspace_mods[path] = mod
    return mod


def load(name: str, root: pathlib.Path | None = None, workspace_ok: bool = False):
    """A built-in adapter, or (workspace_ok: the campaign config names it) a workspace adapter."""
    if name in MODULES:
        return importlib.import_module(f"{__name__}.{name}")
    path = workspace_dir(root) / f"{name}.py"
    if workspace_ok and re.fullmatch(r"[a-z][a-z0-9_]*", name) and path.is_file():
        return _load_file(path)
    raise KeyError(f"unknown source {name!r}; built in: {', '.join(MODULES)}; "
                   f"or write {path} and name it in [[sources]] (parser-builder skill)")


def configured(camp: Campaign) -> set[str]:
    return {s.get("type") for s in camp.config.get("sources") or [] if s.get("type")}


def workspace_names(root: pathlib.Path | None = None) -> list[str]:
    d = workspace_dir(root)
    return sorted(p.stem for p in d.glob("*.py") if re.fullmatch(r"[a-z][a-z0-9_]*", p.stem) and p.stem not in MODULES) \
        if d.is_dir() else []


def all_sources():
    """Built-in adapters. Workspace adapters are listed by name only (workspace_names), never imported to list them."""
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
    mod = load(name, camp.root, workspace_ok=True)  # spec comes from this campaign's [[sources]]
    why = readiness(mod)
    if why:
        log(f"[{name}] skipped: {why}")
        return {"source": name, "skipped": why}
    fetcher = getattr(mod, "fetcher", None)
    ctx = Ctx(camp, fetcher(camp) if fetcher else camp.fetcher(), spec, log)
    stats = {"source": name, "units": 0, "skipped_cached": 0, "rows": 0, "failed": 0, "blocked": None,
             "layout_changed": 0}
    layout_streak = 0
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
        except LayoutChanged as e:
            stats["failed"] += 1
            stats["layout_changed"] += 1
            layout_streak += 1
            log(f"[{name}] {key}: LAYOUT CHANGED: {e}. The adapter's parser needs fixing (parser-builder skill).")
            if layout_streak >= 2:
                log(f"[{name}] two units in a row hit a layout change; stopping this source.")
                break
            continue
        except Exception as e:  # one bad unit must not stop the run
            stats["failed"] += 1
            log(f"[{name}] {key}: FAILED {type(e).__name__}: {e}")
            if os.environ.get("LEADGEN_DEBUG"):
                traceback.print_exc()
            continue
        layout_streak = 0
        stamp = today()
        for r in rows:
            r.setdefault("source", name)
            r.setdefault("collected", stamp)
        write_jsonl(camp.raw_dir(name) / f"{key}.jsonl", rows)
        stats["units"] += 1
        stats["rows"] += len(rows)
        log(f"[{name}] {key}: {len(rows)}")
    return stats


def raw_rows(camp: Campaign, name: str) -> list[dict]:
    """One source's raw rows; for a unit collected on several dates, the newest snapshot wins."""
    latest: dict[str, pathlib.Path] = {}
    for p in camp.raw_files(name):
        latest[p.stem] = p  # raw_files is sorted, so later dates overwrite
    return [r for p in latest.values() for r in read_jsonl(p)]


def collected_sources(camp: Campaign) -> list[str]:
    base = camp.dir / "raw"
    return sorted(p.name for p in base.iterdir() if p.is_dir()) if base.is_dir() else []


def load_raw(camp: Campaign, kind: str = "businesses", log=None) -> list[dict]:
    """All raw rows of the given kind, from every source that has raw data in this campaign."""
    log = log or (lambda m: print(m, file=sys.stderr))
    rows, named = [], configured(camp)
    for name in collected_sources(camp):
        try:
            mod = load(name, camp.root, workspace_ok=name in named)
        except KeyError as e:
            log(f"[merge] raw/{name} skipped: {e}")
            continue
        if mod.KIND == kind:
            rows.extend(raw_rows(camp, name))
    return rows


def dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1)
