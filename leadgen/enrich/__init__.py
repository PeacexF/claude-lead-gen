"""Enrichment runner: site crawl → DNS/MX → job boards → registries, in parallel across leads.

Steps per lead run in that order (DNS checks the emails the crawl found; jobs use the board links it found).
A lead is skipped for a step it already has (site.checked, dns.checked, jobs.checked, registry.<name>) unless
refresh is set, so an interrupted run resumes where it stopped. leads.jsonl is checkpointed as results come in.
A Blocked error turns that step off for the rest of the run.
"""
from __future__ import annotations

import copy
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..core import schema
from ..core.campaign import Campaign
from ..core.http import Blocked, UA_BOT
from ..core.store import read_jsonl, write_jsonl
from . import dns, jobs, registry, site

STEPS = ["site", "dns", "jobs", "registry"]
CHECKPOINT_EVERY = 25


def configured_steps(cfg: dict) -> list[str]:
    e = cfg["enrich"]
    return [s for s in STEPS if (e.get(s) if s != "registry" else bool(e.get("registry")))]


def needs(lead: dict, step: str, cfg: dict, refresh: bool = False) -> bool:
    if step == "site":
        return bool(lead.get("website")) and (refresh or not (lead.get("site") or {}).get("checked"))
    if step == "dns":
        return bool(lead.get("domain") or lead.get("emails")) and (refresh or not (lead.get("dns") or {}).get("checked"))
    if step == "jobs":
        return bool(lead.get("domain") or lead.get("name")) and (refresh or not (lead.get("jobs") or {}).get("checked"))
    if step == "registry":
        done = lead.get("registry") or {}
        return any(refresh or n not in done for n in cfg["enrich"].get("registry") or [] if not registry.missing_env(n))
    raise KeyError(step)


class Runner:
    def __init__(self, camp: Campaign, steps: list[str], refresh: bool = False, log=None):
        self.camp, self.cfg, self.refresh = camp, camp.config, refresh
        self.steps = steps
        self.log = log or (lambda m: print(m, file=sys.stderr))
        self.off: set[str] = set()
        self.lock = threading.Lock()
        delay = float(self.cfg["http"].get("delay", 1.0))
        self.fetchers = {
            "site": camp.fetcher(public_only=True, delay=delay, timeout=20),
            "dns": camp.fetcher(ua=UA_BOT, delay=0.05, timeout=15),
            "jobs": camp.fetcher(ua=UA_BOT, delay=0.3, timeout=20),
            "registry": camp.fetcher(delay=2.0, timeout=30),
        }
        self.stats = {s: {"done": 0, "failed": 0} for s in steps}

    def _disable(self, step: str, why: str) -> None:
        with self.lock:
            if step not in self.off:
                self.off.add(step)
                self.log(f"[enrich:{step}] blocked ({why}); skipping this step for the rest of the run")

    def one(self, lead: dict) -> dict:
        lead = copy.deepcopy(lead)
        for step in self.steps:
            if step in self.off or not needs(lead, step, self.cfg, self.refresh):
                continue
            try:
                if step == "site":
                    site.apply(lead, site.crawl(self.fetchers["site"], lead["website"],
                                                int(self.cfg["enrich"].get("max_inner_pages", 4))))
                elif step == "dns":
                    dns.enrich(self.fetchers["dns"], lead)
                elif step == "jobs":
                    jobs.enrich(self.fetchers["jobs"], lead)
                elif step == "registry":
                    registry.enrich(self.fetchers["registry"], lead, self.cfg["enrich"].get("registry") or [])
                with self.lock:
                    self.stats[step]["done"] += 1
            except Blocked as e:
                self._disable(step, str(e))
            except Exception as e:  # one bad lead must not stop the run
                with self.lock:
                    self.stats[step]["failed"] += 1
                self.log(f"[enrich:{step}] {lead.get('id')}: {type(e).__name__}: {e}"[:300])
        if "site" in self.steps and not lead.get("website"):
            schema.add_signal(lead, "no_website", "no own website in any source", "sources")
        return lead

    def run(self, leads: list[dict], only: set[str] | None = None, limit: int | None = None) -> list[dict]:
        todo = [i for i, l in enumerate(leads)
                if (not only or l["id"] in only) and (any(needs(l, s, self.cfg, self.refresh) for s in self.steps)
                                                      or ("site" in self.steps and not l.get("website")))]
        if limit:
            todo = todo[:limit]
        self.log(f"[enrich] {len(todo)} of {len(leads)} leads need {', '.join(self.steps)}")
        workers = max(1, int(self.cfg["enrich"].get("workers", 8)))
        t0, n = time.monotonic(), 0
        with ThreadPoolExecutor(workers) as pool:
            futs = {pool.submit(self.one, leads[i]): i for i in todo}
            for fut in as_completed(futs):
                leads[futs[fut]] = fut.result()
                n += 1
                if n % CHECKPOINT_EVERY == 0:
                    write_jsonl(self.camp.leads_path, leads)
                    self.log(f"[enrich] {n}/{len(todo)} ({time.monotonic() - t0:.0f}s)")
        write_jsonl(self.camp.leads_path, leads)
        return leads


def run(camp: Campaign, steps: list[str] | None = None, refresh: bool = False, only: set[str] | None = None,
        limit: int | None = None, log=None) -> dict:
    steps = [s for s in (steps or configured_steps(camp.config)) if s in STEPS]
    leads = list(read_jsonl(camp.leads_path))
    if not leads:
        raise FileNotFoundError(f"no leads yet in {camp.leads_path} (run: leadgen merge {camp.slug})")
    r = Runner(camp, steps, refresh, log)
    r.run(leads, only, limit)
    return {"steps": steps, "leads": len(leads), "stats": r.stats, "blocked": sorted(r.off)}
