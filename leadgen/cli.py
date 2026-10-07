"""leadgen CLI. See SPEC.md §4.3.

Progress goes to stderr. The result goes to stdout: readable text by default, one JSON object with --json (for Claude).
Every command is idempotent and resumable: re-running only does what's missing.

Exit codes: 0 ok · 1 error · 2 usage · 3 sending refused (send_mode off, compliance, expired batch...).
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys

from . import enrich, score, sources
from .core import merge as merging
from .core.campaign import Campaign, list_campaigns, workspace
from .core.store import read_jsonl, write_csv, write_jsonl
from .outreach import drafts as drafting
from .outreach import send as sending
from .outreach.suppression import Suppression

LEAD_STATUSES = ["new", "drafted", "sent", "replied", "won", "lost", "suppressed"]
KEY_ENV = ["GOOGLE_PLACES_API_KEY", "COMPANIES_HOUSE_API_KEY", "OPENCORPORATES_API_TOKEN", "HUNTER_API_KEY",
           "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"]


class CLIError(Exception):
    code = 1


class Refused(CLIError):
    code = 3


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def camp_of(args) -> Campaign:
    return Campaign(args.slug)


def leads_of(camp: Campaign) -> list[dict]:
    leads = list(read_jsonl(camp.leads_path))
    if not leads:
        raise CLIError(f"no leads yet in {camp.leads_path} (run: leadgen merge {camp.slug})")
    return leads


def csv_list(s: str | None) -> list[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def tier_key(lead: dict):
    t = lead.get("tier")
    return (score.TIER_ORDER.index(t) if t in score.TIER_ORDER else 9, -(lead.get("score") or 0), lead.get("id") or "")


# --- campaign lifecycle --------------------------------------------------------------------------------------------
def cmd_init(args):
    camp = Campaign.create(args.slug, name=args.name or "", offer=args.offer or "")
    res = {"campaign": camp.slug, "dir": str(camp.dir)}
    return res, (f"created {camp.dir}\nnext: fill brief.md and campaign.toml (sources, scoring, outreach), "
                 f"then: leadgen run {camp.slug}")


def cmd_sources(args):
    rows = []
    for m in sources.all_sources():
        why = sources.readiness(m)
        rows.append({"name": m.NAME, "kind": m.KIND, "regions": m.REGIONS, "env": list(m.ENV), "ready": why is None,
                     "why_not": why, "about": m.ABOUT, "workspace": None})
    for n in sources.workspace_names():  # listed, not imported: workspace code runs only when a campaign names it
        path = sources.workspace_dir() / f"{n}.py"
        rows.append({"name": n, "kind": "?", "regions": "workspace", "env": [], "ready": None, "why_not": None,
                     "about": "workspace adapter (loads when a campaign's [[sources]] names it)", "workspace": str(path)})
    width = max(len(r["name"]) for r in rows)
    state = {True: "ready", False: "NOT READY", None: "-"}
    lines = [f"{r['name']:<{width}}  {r['kind']:<10}  {state[r['ready']]:<9}  {r['regions']:<26}  "
             f"{r['about']}" + (f"\n{'':<{width}}  -> {r['why_not']}" if r["why_not"] else "")
             + (f"\n{'':<{width}}  workspace: {r['workspace']}" if r["workspace"] else "") for r in rows]
    return {"sources": rows}, "\n".join(lines)


def collect(camp: Campaign, only: list[str], refresh: bool) -> list[dict]:
    specs = camp.config.get("sources") or []
    for s in specs:
        if "type" not in s:
            raise CLIError(f"a [[sources]] block in {camp.dir / 'campaign.toml'} has no type")
        sources.load(s["type"], camp.root, workspace_ok=True)  # unknown type fails before anything runs
    unknown = set(only) - {s["type"] for s in specs}
    if unknown:
        raise CLIError(f"not configured in campaign.toml [[sources]]: {', '.join(sorted(unknown))}")
    if not specs:
        raise CLIError(f"no [[sources]] in {camp.dir / 'campaign.toml'}; `leadgen sources` lists them")
    return [sources.run_source(camp, s, refresh=refresh, log=log) for s in specs if not only or s["type"] in only]


def fmt_collect(stats: list[dict]) -> str:
    out = []
    for s in stats:
        if s.get("skipped"):
            out.append(f"{s['source']}: skipped ({s['skipped']})")
        else:
            out.append(f"{s['source']}: {s['units']} units fetched, {s['rows']} rows, {s['skipped_cached']} cached, "
                       f"{s['failed']} failed" + (f", BLOCKED: {s['blocked']}" if s["blocked"] else "")
                       + (f", LAYOUT CHANGED in {s['layout_changed']} units" if s.get("layout_changed") else ""))
    return "\n".join(out)


def cmd_collect(args):
    camp = camp_of(args)
    stats = collect(camp, csv_list(args.source), args.refresh)
    return {"collect": stats}, fmt_collect(stats)


def empty(v) -> bool:
    return v is None or v == "" or v == [] or v == {}


def cmd_inspect(args):
    """Fill rate per field and sample rows of the raw data: the live check for a new or changed adapter."""
    camp = camp_of(args)
    names = csv_list(args.source) or sources.collected_sources(camp)
    if not names:
        raise CLIError(f"no raw data in {camp.dir / 'raw'} (run: leadgen collect {camp.slug})")
    res, text = {}, []
    for name in names:
        rows = sources.raw_rows(camp, name)
        fields: dict[str, int] = {}
        for r in rows:
            for k, v in r.items():
                fields.setdefault(k, 0)
                fields[k] += not empty(v)
        fill = {k: round(n / len(rows), 3) if rows else 0 for k, n in sorted(fields.items(), key=lambda kv: -kv[1])}
        ids = [r.get("source_id") for r in rows if r.get("source_id") is not None]
        res[name] = {"rows": len(rows), "units": len({p.stem for p in camp.raw_files(name)}),
                     "duplicate_source_ids": len(ids) - len(set(ids)), "fill": fill, "sample": rows[: args.n]}
        r = res[name]
        text.append(f"== {name}: {r['rows']} rows in {r['units']} units"
                    + (f", {r['duplicate_source_ids']} duplicate source_id" if r["duplicate_source_ids"] else ""))
        text += [f"  {v:>6.0%}  {k}" for k, v in fill.items()]
        for row in r["sample"]:
            text.append("  sample: " + json.dumps({k: v for k, v in row.items() if not empty(v)}, ensure_ascii=False)[:400])
    return res, "\n".join(text)


def do_merge(camp: Campaign) -> dict:
    rows = sources.load_raw(camp, "businesses", log=log)
    existing = list(read_jsonl(camp.leads_path))
    leads = merging.merge(rows, existing, camp.config["campaign"].get("default_phone_cc") or None)
    write_jsonl(camp.leads_path, leads)
    return {"raw_rows": len(rows), "leads": len(leads), "before": len(existing)}


def cmd_merge(args):
    r = do_merge(camp_of(args))
    return r, f"{r['raw_rows']} raw rows -> {r['leads']} leads (was {r['before']})"


def fmt_enrich(r: dict) -> str:
    parts = [f"{s}: {v['done']} done, {v['failed']} failed" for s, v in r["stats"].items()]
    return "\n".join([f"enriched {r['leads']} leads ({', '.join(r['steps']) or 'no steps'})", *parts]
                     + ([f"blocked: {', '.join(r['blocked'])}"] if r["blocked"] else []))


def cmd_enrich(args):
    camp = camp_of(args)
    leads_of(camp)
    steps = csv_list(args.steps) if args.steps is not None else None
    bad = set(steps or []) - set(enrich.STEPS)
    if bad:
        raise CLIError(f"unknown steps {sorted(bad)}; known: {', '.join(enrich.STEPS)}")
    r = enrich.run(camp, steps, refresh=args.refresh, only=set(csv_list(args.only)) or None, limit=args.limit, log=log)
    return r, fmt_enrich(r)


def do_score(camp: Campaign) -> dict:
    leads = leads_of(camp)
    try:
        r = score.score_all(leads, camp.config)
    except (score.RuleError, ValueError) as e:  # ValueError: bad regex in a rule
        raise CLIError(f"scoring rules: {e}") from e
    write_jsonl(camp.leads_path, leads)
    return r


def fmt_score(r: dict) -> str:
    hits = "\n".join(f"  {n:>5}  {k}" for k, n in r["rule_hits"].items())
    tiers = "  ".join(f"{t}: {n}" for t, n in r["tiers"].items())
    return f"{r['formula']}\n\nrule hits:\n{hits}\n\n{r['leads']} leads  {tiers}"


def cmd_score(args):
    r = do_score(camp_of(args))
    return r, fmt_score(r)


def do_export(camp: Campaign, out: str | None = None, min_tier: str | None = None, has_email: bool = False,
              status: list[str] | None = None) -> dict:
    leads = leads_of(camp)
    if min_tier and min_tier not in score.TIER_ORDER:
        raise CLIError(f"--min-tier must be one of {score.TIER_ORDER}")
    keep = [l for l in leads
            if (not min_tier or score.tier_at_least(l.get("tier"), min_tier))
            and (not has_email or l.get("emails"))
            and (not status or l.get("status") in status)]
    path = pathlib.Path(out) if out else camp.dir / "leads.csv"
    n = write_csv(path, sorted(keep, key=tier_key))
    return {"path": str(path), "rows": n, "of": len(leads)}


def cmd_export(args):
    r = do_export(camp_of(args), args.out, args.min_tier, args.has_email, csv_list(args.status))
    return r, f"wrote {r['rows']} of {r['of']} leads to {r['path']}"


def cmd_run(args):
    camp = camp_of(args)
    res, text = {}, []
    if not args.no_collect:
        res["collect"] = collect(camp, csv_list(args.source), args.refresh)
        text.append(fmt_collect(res["collect"]))
    res["merge"] = do_merge(camp)
    text.append(f"merge: {res['merge']['raw_rows']} raw rows -> {res['merge']['leads']} leads")
    if not res["merge"]["leads"]:
        return res, "\n".join(text + ["no leads; check [[sources]] in campaign.toml and the collect output above"])
    steps = csv_list(args.steps) if args.steps is not None else None
    res["enrich"] = enrich.run(camp, steps, log=log)
    text.append(fmt_enrich(res["enrich"]))
    res["score"] = do_score(camp)
    text.append(fmt_score(res["score"]))
    res["export"] = do_export(camp)
    text.append(f"export: {res['export']['rows']} leads -> {res['export']['path']}")
    return res, "\n\n".join(text)


def cmd_status(args):
    camp = camp_of(args)
    raw = {}
    for p in camp.raw_files():
        src = p.relative_to(camp.dir / "raw").parts[0]
        r = raw.setdefault(src, {"files": 0, "rows": 0, "latest": ""})
        r["files"] += 1
        with p.open(encoding="utf-8") as fh:
            r["rows"] += sum(1 for line in fh if line.strip())
        r["latest"] = max(r["latest"], p.parent.name)
    leads = list(read_jsonl(camp.leads_path))
    count = lambda pred: sum(1 for l in leads if pred(l))  # noqa: E731
    enriched = {"site": count(lambda l: (l.get("site") or {}).get("checked")),
                "dns": count(lambda l: (l.get("dns") or {}).get("checked")),
                "jobs": count(lambda l: (l.get("jobs") or {}).get("checked")),
                "registry": count(lambda l: l.get("registry"))}
    ds = drafting.Drafts(camp.outreach_dir / "drafts.jsonl").rows.values()
    sent = list(read_jsonl(camp.outreach_dir / "sent.jsonl"))
    today = sending.now().date().isoformat()
    res = {
        "campaign": camp.slug, "dir": str(camp.dir), "raw": raw, "leads": len(leads),
        "with_website": count(lambda l: l.get("website")), "with_email": count(lambda l: l.get("emails")),
        "with_phone": count(lambda l: l.get("phones")), "enriched": enriched,
        "scored": count(lambda l: l.get("tier")),
        "tiers": {t: count(lambda l, t=t: l.get("tier") == t) for t in score.TIER_ORDER},
        "status": {s: count(lambda l, s=s: (l.get("status") or "new") == s) for s in LEAD_STATUSES},
        "drafts": {s: sum(1 for d in ds if d.get("status") == s) for s in ("draft", "sent", "skipped")},
        "sent": {"total": len(sent), "today": sum(1 for s in sent if (s.get("sent_at") or "")[:10] == today)},
        "send_mode": camp.config["outreach"].get("send_mode") or "off",
    }
    lines = [f"campaign {camp.slug}  ({camp.dir})", "raw:"]
    lines += [f"  {k:<14} {v['files']} files, {v['rows']} rows, latest {v['latest']}" for k, v in sorted(raw.items())] or ["  (none)"]
    lines += [f"leads: {res['leads']}  (website {res['with_website']}, email {res['with_email']}, phone {res['with_phone']})",
              "enriched: " + ", ".join(f"{k} {v}" for k, v in enriched.items()),
              f"scored: {res['scored']}  " + "  ".join(f"{t}: {n}" for t, n in res["tiers"].items()),
              "status: " + (", ".join(f"{k} {v}" for k, v in res["status"].items() if v) or "(no leads)"),
              "drafts: " + ", ".join(f"{k} {v}" for k, v in res["drafts"].items()),
              f"sent: {res['sent']['total']} total, {res['sent']['today']} today  (send_mode {res['send_mode']})"]
    return res, "\n".join(lines)


def cmd_mark(args):
    camp = camp_of(args)
    leads = leads_of(camp)
    by_id = {l["id"]: l for l in leads}
    if args.lead not in by_id:
        raise CLIError(f"no lead {args.lead!r} in {camp.leads_path}")
    lead = by_id[args.lead]
    old = lead.get("status") or "new"
    lead["status"] = args.status
    if args.note:
        lead["notes"] = ((lead.get("notes") or "") + f"\n[{args.status}] {args.note}").strip()
    write_jsonl(camp.leads_path, leads)
    res = {"lead": args.lead, "from": old, "to": args.status, "suppressed": []}
    if args.status == "suppressed":  # do-not-contact must hold across campaigns, so it goes on the global list too
        values = [lead["domain"]] if lead.get("domain") else (
            [e["value"] for e in lead.get("emails") or []] + list(lead.get("phones") or []))
        res["suppressed"] = Suppression(camp.suppression_path()).add(values, f"lead {args.lead} in {camp.slug}")
    return res, f"{args.lead}: {old} -> {args.status}" + (
        f"; added to suppression.txt: {', '.join(res['suppressed'])}" if res["suppressed"] else "")


# --- outreach ------------------------------------------------------------------------------------------------------
def read_drafts_input(path: str | None) -> list[dict]:
    raw = sys.stdin.read() if path in (None, "-") else pathlib.Path(path).read_text(encoding="utf-8")
    raw = raw.strip()
    if not raw:
        raise CLIError("no drafts on input (JSON object, JSON list, or JSONL)")
    if raw[0] == "[":
        return json.loads(raw)
    try:
        one = json.loads(raw)
        return [one]
    except json.JSONDecodeError:
        return [json.loads(line) for line in raw.splitlines() if line.strip()]


def cmd_drafts(args):
    camp = camp_of(args)
    store = drafting.Drafts(camp.outreach_dir / "drafts.jsonl")
    if args.action == "add":
        leads = leads_of(camp)
        by_id = {l["id"]: l for l in leads}
        try:
            r = store.add(read_drafts_input(args.file), by_id)
        except (drafting.DraftError, json.JSONDecodeError) as e:
            raise CLIError(f"drafts not added (all-or-nothing): {e}") from e
        changed = 0
        for d in store.rows.values():
            lead = by_id.get(d["lead_id"])
            if lead and d.get("status") == "draft" and (lead.get("status") or "new") == "new":
                lead["status"] = "drafted"
                changed += 1
        if changed:
            write_jsonl(camp.leads_path, leads)
        return r, f"added {r['added']}, replaced {r['replaced']}" + (
            f", kept {len(r['kept_sent'])} already sent" if r["kept_sent"] else "")
    rows = sorted(store.rows.values(), key=lambda r: (r["lead_id"], r["step"], r["channel"]))
    if args.action == "list":
        status = csv_list(args.status)
        rows = [r for r in rows if (not status or r.get("status") in status) and (not args.lead or r["lead_id"] == args.lead)]
        brief = [{k: r.get(k) for k in ("id", "lead_id", "step", "channel", "to", "subject", "status")} for r in rows]
        text = "\n".join(f"{r['status']:<7} {r['id']:<40} {r.get('subject') or r['body'][:50]!s}" for r in rows) or "(no drafts)"
        return {"drafts": brief}, text
    # show: one draft id, or every draft of a lead
    pick = [r for r in rows if r["id"] == args.id or r["lead_id"] == args.id]
    if not pick:
        raise CLIError(f"no draft or lead {args.id!r} in {store.path}")
    leads = {l["id"]: l for l in read_jsonl(camp.leads_path)}
    out, text = [], []
    for r in pick:
        link = drafting.deeplink(r, leads.get(r["lead_id"]))
        out.append({**r, "deeplink": link})
        text.append("\n".join([f"== {r['id']}  [{r['status']}]", f"to: {r.get('to') or '(best address at send time)'}",
                               *([f"subject: {r['subject']}"] if r.get("subject") else []), "", r["body"], "",
                               "evidence:", *[f"  - {e['fact']}  <{e['source']}>" for e in r.get("evidence") or []],
                               *([f"link: {link}"] if link else [])]))
    return {"drafts": out}, "\n\n".join(text)


def fmt_send(r: dict, slug: str) -> str:
    lines = [f"send_mode: {r['mode']}" + ("  (dry run)" if r["dry_run"] else "")]
    if r["sent"]:
        lines.append(f"sent {len(r['sent'])}:")
        lines += [f"  {s['to']}  {s['subject']}" for s in r["sent"]]
    elif r["ready"]:
        lines.append(f"ready {len(r['ready'])}:")
        lines += [f"  {x['to']:<34} step {x['step']}  {x['subject']}" for x in r["ready"]]
    else:
        lines.append("nothing ready to send")
    if r["skipped"]:
        reasons: dict[str, int] = {}
        for s in r["skipped"]:
            reasons[s["reason"]] = reasons.get(s["reason"], 0) + 1
        lines.append("skipped: " + "; ".join(f"{k} ({n})" for k, n in sorted(reasons.items(), key=lambda kv: -kv[1])))
    if r["batch"] and not r["sent"] and not r["dry_run"]:
        lines.append(f"\nbatch {r['batch']} saved. Review it, then send with: leadgen send {slug} --approve {r['batch']}")
    return "\n".join(lines)


def cmd_send(args):
    camp = camp_of(args)
    try:
        r = sending.run(camp, dry_run=args.dry_run, approve=args.approve, log=log)
    except sending.SendRefused as e:
        raise Refused(str(e)) from e
    return r, fmt_send(r, camp.slug)


def cmd_suppress(args):
    sup = Suppression(workspace() / "suppression.txt")
    if not args.values:
        return {"path": str(sup.path), "entries": sorted(sup.entries)}, "\n".join(sorted(sup.entries)) or "(empty)"
    new = sup.add(args.values, args.reason or "")
    return {"path": str(sup.path), "added": new}, f"added {len(new)} to {sup.path}" + (f": {', '.join(new)}" if new else "")


# --- setup / health ------------------------------------------------------------------------------------------------
def cmd_doctor(args):
    from .sources import twogis
    checks = []

    def add(name, ok, detail="", optional=False):
        # an optional tool that's missing is informational (None), not a failure
        checks.append({"check": name, "ok": True if ok else (None if optional else False), "detail": detail})

    add("python >= 3.11", sys.version_info >= (3, 11), sys.version.split()[0])
    try:
        socket.create_connection(("1.1.1.1", 443), timeout=4).close()
        add("network", True, "reached 1.1.1.1:443")
    except OSError as e:
        add("network", False, str(e))
    ws = workspace()
    add("workspace", os.access(ws, os.W_OK), f"{ws}  campaigns: {', '.join(list_campaigns(ws)) or 'none'}")
    for e in KEY_ENV:
        checks.append({"check": f"env {e}", "ok": None, "detail": "set" if os.environ.get(e) else "not set (optional)"})
    add("npx (Playwright MCP)", shutil.which("npx"), shutil.which("npx") or "install Node.js for the browser MCP",
        optional=True)
    add("parser-2gis (twogis source)", twogis.ready() is None, twogis.ready() or str(twogis.parser_bin()), optional=True)
    chrome = next((p for p in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",)
                   if pathlib.Path(p).exists()), None) or shutil.which("google-chrome") or shutil.which("chromium")
    add("Chrome (twogis source)", chrome, chrome or "not found", optional=True)
    mark = {True: "ok  ", False: "FAIL", None: "-   "}
    return {"checks": checks}, "\n".join(f"{mark[c['ok']]} {c['check']:<30} {c['detail']}" for c in checks)


def cmd_setup(args):
    """Install parser-2gis (patched) outside the plugin dir, so plugin updates don't wipe it."""
    from .sources import twogis
    if args.tool != "2gis":
        raise CLIError(f"unknown tool {args.tool!r}; known: 2gis")
    for need in ("git", "uv"):
        if not shutil.which(need):
            raise CLIError(f"{need} not found on PATH (uv: https://github.com/astral-sh/uv)")
    patch = pathlib.Path(__file__).resolve().parents[1] / "tools" / "parser-2gis-headless.patch"
    dest = twogis.tools_dir() / "parser-2gis"
    dest.parent.mkdir(parents=True, exist_ok=True)

    def run(cmd, cwd=None, check=True):
        log("$ " + " ".join(cmd))
        return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)

    try:
        if not dest.exists():
            run(["git", "clone", "--depth", "1", "https://github.com/interlark/parser-2gis", str(dest)])
        if run(["git", "apply", "--check", str(patch)], cwd=dest, check=False).returncode == 0:
            run(["git", "apply", str(patch)], cwd=dest)
        else:
            log("patch already applied (or upstream changed; check parser-2gis if collection fails)")
        run(["uv", "venv", "-p", "3.11", ".venv", "-q"], cwd=dest)
        run(["uv", "pip", "install", "-p", ".venv/bin/python", "-e", ".", "-q"], cwd=dest)
    except subprocess.CalledProcessError as e:
        raise CLIError(f"{' '.join(e.cmd)} failed: {(e.stderr or e.stdout or '').strip()[-500:]}") from e
    ok = twogis.ready() is None
    if not ok:
        raise CLIError(f"install finished but {twogis.parser_bin()} is missing")
    return {"installed": str(twogis.parser_bin())}, f"ok: {twogis.parser_bin()}"


# --- parser --------------------------------------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="print the result as JSON")
    p = argparse.ArgumentParser(prog="leadgen", parents=[common],
                                description="Lead generation CLI: collect -> merge -> enrich -> score -> export -> drafts -> send.")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="command")

    def cmd(name, fn, help, slug=True):
        sp = sub.add_parser(name, parents=[common], help=help, description=help)
        if slug:
            sp.add_argument("slug", help="campaign slug (campaigns/<slug>/)")
        sp.set_defaults(fn=fn)
        return sp

    sp = cmd("init", cmd_init, "create a campaign from templates")
    sp.add_argument("--name")
    sp.add_argument("--offer", help="one line: what you sell and the outcome")
    cmd("sources", cmd_sources, "list source adapters and whether they're ready", slug=False)
    sp = cmd("collect", cmd_collect, "run the configured sources into raw/")
    sp.add_argument("--source", help="only these source types (comma-separated)")
    sp.add_argument("--refresh", action="store_true", help="re-fetch units already collected")
    sp = cmd("inspect", cmd_inspect, "fill rate per field + sample rows of collected raw data (check a parser)")
    sp.add_argument("--source", help="only these sources (comma-separated)")
    sp.add_argument("--n", type=int, default=3, help="sample rows per source")
    cmd("merge", cmd_merge, "normalize + dedupe raw records into leads.jsonl")
    sp = cmd("enrich", cmd_enrich, "crawl sites, check MX, job boards, registries")
    sp.add_argument("--steps", help=f"comma-separated subset of {','.join(enrich.STEPS)} (default: from campaign.toml)")
    sp.add_argument("--refresh", action="store_true", help="redo steps already done")
    sp.add_argument("--only", help="only these lead ids (comma-separated)")
    sp.add_argument("--limit", type=int, help="at most this many leads")
    cmd("score", cmd_score, "apply scoring rules; print the formula and tier counts")
    sp = cmd("export", cmd_export, "write leads.csv (sorted by tier, score)")
    sp.add_argument("--out", help="path (default: campaigns/<slug>/leads.csv)")
    sp.add_argument("--min-tier", choices=score.TIER_ORDER)
    sp.add_argument("--has-email", action="store_true")
    sp.add_argument("--status", help="only these lead statuses (comma-separated)")
    sp = cmd("run", cmd_run, "collect -> merge -> enrich -> score -> export")
    sp.add_argument("--source", help="collect only these source types")
    sp.add_argument("--no-collect", action="store_true", help="start from the raw data already collected")
    sp.add_argument("--steps", help="enrichment steps (default: from campaign.toml; empty string = none)")
    sp.add_argument("--refresh", action="store_true", help="re-fetch units already collected")
    cmd("status", cmd_status, "counts per stage, tier, and outreach status")
    sp = cmd("mark", cmd_mark, "set a lead's status (suppressed also adds it to suppression.txt)")
    sp.add_argument("lead", help="lead id")
    sp.add_argument("status", choices=LEAD_STATUSES)
    sp.add_argument("--note", help="appended to the lead's notes")

    sp = cmd("drafts", cmd_drafts, "store and inspect outreach drafts")
    dsub = sp.add_subparsers(dest="action", required=True, metavar="action")
    da = dsub.add_parser("add", parents=[common], help="add drafts from a file or stdin (JSON, JSON list, or JSONL)")
    da.add_argument("file", nargs="?", help="path, or - / omitted for stdin")
    dl = dsub.add_parser("list", parents=[common], help="list drafts")
    dl.add_argument("--status", help="draft,sent,skipped (comma-separated)")
    dl.add_argument("--lead", help="only this lead id")
    ds = dsub.add_parser("show", parents=[common], help="show a draft (or all drafts of a lead) with its evidence")
    ds.add_argument("id", help="draft id (<lead>:<step>:<channel>) or lead id")

    sp = cmd("send", cmd_send, "gated email sending (send_mode off|confirm|auto)")
    g = sp.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="show what would go out; never sends")
    g.add_argument("--approve", metavar="BATCH", help="send a previewed batch (confirm mode)")
    sp = cmd("suppress", cmd_suppress, "add emails/domains/phones to the global do-not-contact list (no values: list it)",
             slug=False)
    sp.add_argument("values", nargs="*")
    sp.add_argument("--reason")
    cmd("doctor", cmd_doctor, "check Python, network, optional tools and keys", slug=False)
    sp = cmd("setup", cmd_setup, "install optional tools (2gis: patched parser-2gis)", slug=False)
    sp.add_argument("tool", choices=["2gis"])
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    as_json = getattr(args, "json", False)
    try:
        res, text = args.fn(args)
    except (CLIError, FileNotFoundError, FileExistsError, KeyError) as e:
        msg = e.args[0] if isinstance(e, KeyError) and e.args else str(e)
        code = getattr(e, "code", 1)
        if as_json:
            print(json.dumps({"error": msg, "code": code}, ensure_ascii=False))
        print(f"leadgen: {msg}", file=sys.stderr)
        return code
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str) if as_json else text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
