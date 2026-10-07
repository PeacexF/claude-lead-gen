#!/usr/bin/env python3
"""PreToolUse guard (SPEC.md §5.4). Stdin: the hook JSON. Stdout: a decision, or nothing (normal permission flow).

Send gate. Sending needs a human in the loop unless the user chose send_mode = "auto" themselves.
  Bash `leadgen send` (also bin/leadgen, python -m leadgen[.cli]):
    --dry-run, alone on the command line                  no opinion (nothing can be sent)
    plain send, alone, send_mode off | confirm | auto     no opinion (off refuses; confirm only previews; auto = user's choice)
    --approve <batch> (or any abbreviation of it)         ASK: this sends a previewed batch
    send chained with other commands                      ASK: the chain could change send_mode first
    campaign or send_mode unreadable / unknown            ASK
  Bash, raw-text fallback for indirection the parser can't see ($(...), sh -c, eval, python -c, ...):
    mentions leadgen and "appro" anywhere (flags built from strings, $A, printf...)  ASK
    any command that may write campaign.toml (not plainly read-only, or redirects)   ASK
  Edit / Write of campaign.toml that sets send_mode = "auto"                          ASK
  Edit / Write of any file whose new text mentions leadgen + send + appro (a script to run later)  ASK
PII guard. Campaign data is personal data and stays out of git.
  `git add` of campaigns/, suppression.txt, *.leads.*, leadgen_sources/*_fixtures/ (any case)   DENY
  `git add -f` on a broad path (., -A, globs, :(magic) pathspecs, a directory, --pathspec-from-file)  DENY
  `git add` in the same command that touches ignore rules (.gitignore, info/exclude, excludesFile)  DENY
  Edit / Write of .gitignore that drops a campaigns/ suppression.txt *.leads.* entry               ASK

Threat model. This is a guardrail against mistakes and casual workarounds, not a sandbox. Shell is too expressive
for a hook to parse completely (encoded commands, copied campaign directories, scripts assembled at run time), and
an agent that has SMTP credentials in its environment can reach the mail server without leadgen at all. The hard
boundary for "a human approves every send" is: keep SMTP_* out of the Claude Code session and run
`leadgen send <slug> --approve <id>` yourself, in your own terminal. The guard never answers "allow", so a matched
safe segment can't approve anything chained with it. The CLI enforces the rest itself: send_mode, preview batches
with content hashes, caps, suppression.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shlex
import sys

PII = re.compile(r"(^|[/:])(campaigns(/|$)|suppression\.txt$|[^/]*\.leads\.[^/]*$|leadgen_sources/[^/]*_fixtures(/|$))",
                 re.I)  # case-insensitive: macOS and Windows file systems are
IGNORE_ENTRIES = ("campaigns/", "suppression.txt", ".leads.")
SEPARATORS = re.compile(r"&&|\|\||[;|\n&]")
APPROVE_FLAG = re.compile(r"(?<![\w-])--a(p(p(r(o(v(e)?)?)?)?)?)?(?![\w-])", re.I)  # argparse-style prefixes
READ_ONLY = {"cat", "grep", "rg", "head", "tail", "less", "more", "wc", "ls", "diff", "stat", "file", "bat"}


def tokens(segment: str) -> list[str]:
    try:
        tok = shlex.split(segment, comments=True)
    except ValueError:
        tok = segment.split()
    return [t.lstrip("({`").rstrip(")}`") for t in tok if t.strip("(){}`")]  # (subshell), { group; }


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


def check_send(args: list[str], root: pathlib.Path, chained: bool) -> tuple[str, str] | None:
    approve_at = [i for i, a in enumerate(args) if APPROVE_FLAG.fullmatch(a.split("=", 1)[0])]
    if approve_at:
        i = approve_at[0]
        batch = args[i].split("=", 1)[1] if "=" in args[i] else (args[i + 1] if i + 1 < len(args) else "?")
        return "ask", (f"leadgen: this sends approved outreach batch {batch} by email. "
                       "Approve only if you reviewed the preview.")
    if "--dry-run" in args and not chained:
        return None
    if chained:
        return "ask", ("leadgen send is chained with other commands, which could change the campaign first; "
                       "run it on its own to skip this prompt")
    slug = next((a for a in args if not a.startswith("-")), None)
    if not slug:
        return "ask", "leadgen send without a campaign slug; can't check its send_mode"
    mode = send_mode(root, slug)
    if mode is None:
        return "ask", f"leadgen send: can't read campaigns/{slug}/campaign.toml under {root}; can't check send_mode"
    if mode not in ("off", "confirm", "auto"):
        return "ask", f"leadgen send: unknown send_mode {mode!r} in campaign {slug}"
    return None


def check_git_add(tok: list[str], here: pathlib.Path, raw: str) -> tuple[str, str] | None:
    i = next((k for k, t in enumerate(tok) if t == "add" and "git" in [os.path.basename(x) for x in tok[:k]]), None)
    if i is None:
        return None
    args = tok[i + 1:]
    paths = [a for a in args if not a.startswith("-")]
    hit = [p for p in paths if PII.search(p)]
    if hit:
        return "deny", (f"leadgen PII guard: {', '.join(hit)} holds personal data (leads, contacts, do-not-contact list) "
                        "and stays out of git.")
    if re.search(r"\.gitignore|info/exclude|excludesfile", raw, re.I):
        return "deny", "leadgen PII guard: don't change ignore rules and `git add` in one command; do them separately."
    force = any(a in ("-f", "--force") or re.fullmatch(r"-[a-zA-Z]*f[a-zA-Z]*", a) for a in args)
    broad = any(a == "--all" or a.startswith("--pathspec-from-file") or re.fullmatch(r"-[a-zA-Z]*A[a-zA-Z]*", a)
                for a in args) or any(p in (".", "*") or p.endswith("/") or p.startswith(":") or re.search(r"[*?\[]", p) or (here / p).is_dir()
                           for p in paths)
    if force and broad:
        return "deny", ("leadgen PII guard: `git add -f` on a broad path would add gitignored campaign data. "
                        "Force-add specific files instead.")
    return None


def read_only(cmd: str) -> bool:
    """Every segment starts with a reading command and nothing redirects output."""
    if ">" in cmd or "$(" in cmd or "`" in cmd:
        return False
    segs = [tokens(s) for s in SEPARATORS.split(cmd)]
    return all(seg[0] in READ_ONLY for seg in segs if seg)


def raw_fallback(cmd: str) -> tuple[str, str] | None:
    """Catch what tokenizing can't see: $(...), sh -c '...', eval, python -c, xargs, write-then-move."""
    if "leadgen" in cmd and (APPROVE_FLAG.search(cmd) or re.search(r"appro", cmd, re.I)):
        return "ask", "this command may send an approved leadgen outreach batch (found leadgen + approve)"
    if "campaign.toml" in cmd and not read_only(cmd):
        return "ask", ("this command may change a campaign.toml, which holds send_mode (who approves sending); "
                       "edit it with the Edit tool instead")
    return None


def decide(command: str, cwd: str) -> tuple[str, str] | None:
    """Strictest decision over the command: deny > ask > none."""
    here = pathlib.Path(cwd or ".")
    segs = [strip_env(tokens(s)) for s in SEPARATORS.split(command or "")]
    segs = [(env, tok) for env, tok in segs if tok]
    chained = len([t for _, t in segs if t[0] != "cd"]) > 1
    found = []
    for env, tok in segs:
        if tok[0] == "cd" and len(tok) > 1:
            here = (here / os.path.expanduser(tok[1])).resolve()
            continue
        root = pathlib.Path(env.get("LEADGEN_HOME") or os.environ.get("LEADGEN_HOME") or here)
        args = send_args(tok)
        r = check_send(args, root, chained) if args is not None else check_git_add(tok, here, command)
        if r:
            found.append(r)
    r = raw_fallback(command or "")
    if r:
        found.append(r)
    for level in ("deny", "ask"):
        for r in found:
            if r[0] == level:
                return r
    return None


def decide_edit(tool: str, inp: dict) -> tuple[str, str] | None:
    """Edit / Write / MultiEdit: protect send_mode and the ignore rules that keep campaign data out of git."""
    path = pathlib.Path(inp.get("file_path") or "")
    if tool == "Write":
        new, old = inp.get("content") or "", None
    else:
        edits = inp.get("edits") or [{"old_string": inp.get("old_string"), "new_string": inp.get("new_string")}]
        new = "\n".join(e.get("new_string") or "" for e in edits)
        old = "\n".join(e.get("old_string") or "" for e in edits)
    if path.name == "campaign.toml" and re.search(r"send_mode\s*=\s*['\"]auto['\"]", new):
        return "ask", (f"setting send_mode = \"auto\" in {path} lets leadgen send email without asking; "
                       "that's the user's decision")
    if "leadgen" in new and re.search(r"\bsend\b", new) and re.search(r"appro", new, re.I):
        return "ask", f"{path} would contain a leadgen send approval; running it later would send email"
    if path.name == ".gitignore":
        if old is None:
            try:
                old = path.read_text(encoding="utf-8")
            except OSError:
                old = ""
        dropped = [e for e in IGNORE_ENTRIES if e in old and e not in new]
        if dropped:
            return "ask", f"this removes {', '.join(dropped)} from {path}, which keeps campaign personal data out of git"
    return None


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    tool, inp = event.get("tool_name"), event.get("tool_input") or {}
    if tool == "Bash":
        r = decide(inp.get("command") or "", event.get("cwd") or os.getcwd())
    elif tool in ("Edit", "Write", "MultiEdit"):
        r = decide_edit(tool, inp)
    else:
        r = None
    if r:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": r[0],
                                                 "permissionDecisionReason": r[1]}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
