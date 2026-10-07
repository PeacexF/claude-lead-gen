"""Global do-not-contact list: <workspace>/suppression.txt, shared by every campaign, gitignored.

One entry per line: an email (jane@acme.com), a domain (acme.com or @acme.com, which covers every address there),
or a phone number (any formatting; compared by digits). Lines starting with # are comments.
"""
from __future__ import annotations

import datetime
import pathlib
import re

from ..core import schema


def normalize(value: str) -> str | None:
    v = value.strip().lower()
    if not v or v.startswith("#"):
        return None
    if "@" in v and not v.startswith("@"):
        return schema.clean_email(v) or v
    if v.startswith("@"):
        v = v[1:]
    if re.fullmatch(r"[+\d\s().-]{7,}", v):
        return re.sub(r"\D", "", v)
    return schema.host(v) or v


class Suppression:
    def __init__(self, path: pathlib.Path):
        self.path = path
        self.entries: set[str] = set()
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                n = normalize(line.split("#", 1)[0])  # strip trailing "# date reason" comments
                if n:
                    self.entries.add(n)

    def add(self, values: list[str], reason: str = "") -> list[str]:
        new = [n for n in (normalize(v) for v in values) if n and n not in self.entries]
        if new:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            stamp = datetime.date.today().isoformat()
            with self.path.open("a", encoding="utf-8") as fh:
                for n in new:
                    fh.write(f"{n}  # {stamp}{' ' + reason if reason else ''}\n")
            self.entries.update(new)
        return new

    def email_blocked(self, email: str | None) -> bool:
        if not email:
            return False
        e = email.strip().lower()
        return e in self.entries or e.rsplit("@", 1)[-1] in self.entries

    def lead_blocked(self, lead: dict) -> bool:
        if lead.get("domain") and lead["domain"] in self.entries:
            return True
        if any(self.email_blocked(e.get("value") if isinstance(e, dict) else e) for e in lead.get("emails") or []):
            return True
        return any(re.sub(r"\D", "", p) in self.entries for p in lead.get("phones") or [])
