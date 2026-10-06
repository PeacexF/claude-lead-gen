"""Workspace + campaign layout and config loading.

Workspace root = $LEADGEN_HOME or the current directory. Each campaign is campaigns/<slug>/ with a campaign.toml
(see templates/campaign.toml). Raw snapshots go to campaigns/<slug>/raw/<source>/<YYYY-MM-DD>/.
"""
from __future__ import annotations

import datetime
import os
import pathlib
import re
import shutil
import tomllib

from .http import Fetcher, UA_BROWSER

PLUGIN_ROOT = pathlib.Path(__file__).resolve().parents[2]
TEMPLATES = PLUGIN_ROOT / "templates"

DEFAULTS: dict = {
    "campaign": {"name": "", "offer": "", "language": "en", "country": "", "default_phone_cc": ""},
    "sources": [],
    "enrich": {"site": True, "max_inner_pages": 4, "dns": True, "jobs": False, "registry": [], "workers": 8},
    "scoring": {"rules": [], "tiers": {"A": 60, "B": 40, "C": 20}},
    "outreach": {"send_mode": "off", "daily_cap": 30, "per_domain_cap": 1, "channels": ["email"],
                 "compliance": "", "sender_name": "", "sender_company": "", "sender_address": "",
                 "unsubscribe_text": "", "min_tier": "B"},
    "http": {"delay": 1.0, "cache": True},
}


def workspace() -> pathlib.Path:
    return pathlib.Path(os.environ.get("LEADGEN_HOME") or os.getcwd()).resolve()


def today() -> str:
    return datetime.date.today().isoformat()


def slugify(s: str) -> str:
    s = re.sub(r"[^\w-]+", "-", s.strip().lower(), flags=re.U).strip("-")
    return s or "campaign"


def deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


class Campaign:
    def __init__(self, slug: str, root: pathlib.Path | None = None):
        self.root = root or workspace()
        self.slug = slug
        self.dir = self.root / "campaigns" / slug
        if not self.dir.exists():
            raise FileNotFoundError(f"campaign not found: {self.dir} (create it with: leadgen init {slug})")
        cfg_path = self.dir / "campaign.toml"
        user = tomllib.loads(cfg_path.read_text()) if cfg_path.exists() else {}
        self.config = deep_merge(DEFAULTS, user)

    # --- paths -----------------------------------------------------------
    @property
    def leads_path(self) -> pathlib.Path:
        return self.dir / "leads.jsonl"

    @property
    def outreach_dir(self) -> pathlib.Path:
        d = self.dir / "outreach"
        d.mkdir(exist_ok=True)
        return d

    def raw_dir(self, source: str, day: str | None = None) -> pathlib.Path:
        d = self.dir / "raw" / source / (day or today())
        d.mkdir(parents=True, exist_ok=True)
        return d

    def raw_files(self, source: str | None = None, pattern: str = "*.jsonl") -> list[pathlib.Path]:
        base = self.dir / "raw"
        glob = f"{source}/*/**/{pattern}" if source else f"*/*/**/{pattern}"
        return sorted(base.glob(glob))

    def fetcher(self, **kw) -> Fetcher:
        http = self.config["http"]
        cache = (self.root / ".leadgen-cache") if http.get("cache", True) else None
        args = {"cache_dir": cache, "delay": float(http.get("delay", 1.0)), "ua": UA_BROWSER,
                "lang": self.config["campaign"].get("language") or "en"}
        args.update(kw)
        return Fetcher(**args)

    def suppression_path(self) -> pathlib.Path:
        return self.root / "suppression.txt"

    # --- creation --------------------------------------------------------
    @classmethod
    def create(cls, slug: str, root: pathlib.Path | None = None, name: str = "", offer: str = "") -> "Campaign":
        root = root or workspace()
        slug = slugify(slug)
        d = root / "campaigns" / slug
        if d.exists():
            raise FileExistsError(f"campaign exists: {d}")
        (d / "raw").mkdir(parents=True)
        for sub in ("dossiers", "outreach", "reports"):
            (d / sub).mkdir()
        cfg = (TEMPLATES / "campaign.toml").read_text()
        cfg = cfg.replace('name = ""', f'name = "{name or slug}"', 1).replace('offer = ""', f'offer = "{offer}"', 1)
        (d / "campaign.toml").write_text(cfg)
        shutil.copy(TEMPLATES / "brief.md", d / "brief.md")
        gi = root / ".gitignore"
        lines = gi.read_text().splitlines() if gi.exists() else []
        need = [p for p in ("campaigns/", "suppression.txt", ".leadgen-cache/") if p not in lines]
        if need:
            with gi.open("a") as fh:
                fh.write(("\n" if lines and lines[-1] else "") + "# leadgen: personal data, keep out of git\n"
                         + "\n".join(need) + "\n")
        return cls(slug, root)


def list_campaigns(root: pathlib.Path | None = None) -> list[str]:
    base = (root or workspace()) / "campaigns"
    return sorted(p.name for p in base.iterdir() if (p / "campaign.toml").exists()) if base.exists() else []
