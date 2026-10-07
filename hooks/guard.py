#!/usr/bin/env python3
"""PreToolUse guard for Bash commands (SPEC.md §5.4). Stdin: the hook JSON. Stdout: a decision, or nothing.

Send gate — `leadgen send` (also `bin/leadgen send`, `python -m leadgen[.cli] send`):
  --dry-run                      no opinion (nothing can be sent)
  --approve <batch>              ASK: this sends a previewed batch
  plain send, send_mode confirm  no opinion (writes a preview batch, sends nothing)
  plain send, send_mode off      no opinion (the CLI refuses)
  plain send, send_mode auto     no opinion (the user chose automatic sending in campaign.toml)
  campaign or mode unreadable    ASK
PII guard — `git add`:
  campaigns/, suppression.txt, *.leads.*, leadgen_sources/*_fixtures/   DENY (personal data; gitignored on purpose)
  -f / --force with a broad path (., -A, *, a directory)        DENY (would pull ignored campaign data in)

The guard never answers "allow": that would also approve whatever else is chained in the same command line.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shlex
import sys

PII = re.compile(r"(^|/)(campaigns(/|$)|suppression\.txt$|[^/]*\.leads\.[^/]*$|leadgen_sources/[^/]*_fixtures(/|$))")
SEPARATORS = re.compile(r"&&|\|\||[;|\n&]")


def tokens(segment: str) -> list[str]:
    try:
        return shlex.split(segment, comments=True)
    except ValueError:
        return segment.split()


def strip_env(tok: list[str]) -> tuple[dict, list[str]]:
    """Leading VAR=value assignments (and `env`) → (env, rest)."""
    env = {}
    while tok and (re.fullmatch(r"[A-Za-z_]\w*=.*", tok[0]) or tok[0] == "env"):
        if tok[0] != "env":
            k, v = tok[0].split("=", 1)
            env[k] = v
        tok = tok[1:]
    return env, tok


def send_args(tok: list[str]) -> list[str] | None:
    """Arguments after `send` when this is a leadgen send call, else None."""
    for i, t in enumerate(tok):
        is_cli = os.path.basename(t) == "leadgen" or (t == "-m" and i + 1 < len(tok) and tok[i + 1] in ("leadgen", "leadgen.cli"))
        if not is_cli:
            continue
        rest = tok[i + (2 if t == "-m" else 1):]
        while rest and rest[0].startswith("-"):  # global flags before the command (--json)
            rest = rest[1:]
        if rest and rest[0] == "send":
            return rest[1:]
    return None


def send_mode(root: pathlib.Path, slug: str) -> str | None:
    cfg = root / "campaigns" / slug / "campaign.toml"
    try:
        text = cfg.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        import tomllib
        return ((tomllib.loads(text).get("outreach") or {}).get("send_mode")) or "off"
    except ImportError:  # python < 3.11: read the one key by hand
        sect = re.search(r"^\[outreach\](.*?)(^\[|\Z)", text, re.S | re.M)
        m = re.search(r'^\s*send_mode\s*=\s*"([^"]*)"', sect.group(1), re.M) if sect else None
        return (m.group(1) if m else "off") if sect else "off"
    except Exception:
        return None


def check_send(args: list[str], root: pathlib.Path) -> tuple[str, str] | None:
    if "--dry-run" in args:
        return None
    approve = next((a.split("=", 1)[1] if "=" in a else (args[i + 1] if i + 1 < len(args) else "?")
                    for i, a in enumerate(args) if a == "--approve" or a.startswith("--approve=")), None)
    skip = {i + 1 for i, a in enumerate(args) if a == "--approve"}
    slug = next((a for i, a in enumerate(args) if not a.startswith("-") and i not in skip), None)
    if approve:
        return "ask", (f"leadgen: this sends approved outreach batch {approve} for campaign {slug or '?'} by email. "
                       "Approve only if you reviewed the preview.")
    if not slug:
        return "ask", "leadgen send without a campaign slug; can't check its send_mode"
    mode = send_mode(root, slug)
    if mode is None:
        return "ask", f"leadgen send: can't read campaigns/{slug}/campaign.toml under {root}; can't check send_mode"
    if mode not in ("off", "confirm", "auto"):
        return "ask", f"leadgen send: unknown send_mode {mode!r} in campaign {slug}"
    return None


def check_git_add(tok: list[str], here: pathlib.Path) -> tuple[str, str] | None:
    i = next((k for k, t in enumerate(tok) if t == "add" and "git" in [os.path.basename(x) for x in tok[:k]]), None)
    if i is None:
        return None
    args = tok[i + 1:]
    paths = [a for a in args if not a.startswith("-")]
    hit = [p for p in paths if PII.search(p)]
    if hit:
        return "deny", (f"leadgen PII guard: {', '.join(hit)} holds personal data (leads, contacts, do-not-contact list) "
                        "and stays out of git.")
    force = any(a in ("-f", "--force") or re.fullmatch(r"-[a-zA-Z]*f[a-zA-Z]*", a) for a in args)
    broad = any(a == "--all" or re.fullmatch(r"-[a-zA-Z]*A[a-zA-Z]*", a) for a in args) or any(
        p in (".", "*") or p.endswith("/") or "*" in p or (here / p).is_dir() for p in paths)
    if force and broad:
        return "deny", ("leadgen PII guard: `git add -f` on a broad path would add gitignored campaign data. "
                        "Force-add specific files instead.")
    return None


def decide(command: str, cwd: str) -> tuple[str, str] | None:
    """Strictest decision over all segments of the command: deny > ask > none."""
    here = pathlib.Path(cwd or ".")
    found = []
    for seg in SEPARATORS.split(command or ""):
        env, tok = strip_env(tokens(seg))
        if not tok:
            continue
        if tok[0] == "cd" and len(tok) > 1:
            here = (here / os.path.expanduser(tok[1])).resolve()
            continue
        root = pathlib.Path(env.get("LEADGEN_HOME") or os.environ.get("LEADGEN_HOME") or here)
        args = send_args(tok)
        r = check_send(args, root) if args is not None else check_git_add(tok, here)
        if r:
            found.append(r)
    for level in ("deny", "ask"):
        for r in found:
            if r[0] == level:
                return r
    return None


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    if event.get("tool_name") != "Bash":
        return 0
    r = decide((event.get("tool_input") or {}).get("command") or "", event.get("cwd") or os.getcwd())
    if r:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": r[0],
                                                 "permissionDecisionReason": r[1]}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
