"""2GIS businesses (RU, CIS, plus UAE/Cyprus/Chile... wherever 2GIS runs) via a patched parser-2gis. Ported from claude-kit.

Needs one-time setup: `leadgen setup 2gis` (clones interlark/parser-2gis, applies tools/parser-2gis-headless.patch,
creates a Python 3.11 venv with uv). Installed under $LEADGEN_TOOLS or ~/.local/share/leadgen/tools so plugin
updates don't wipe it. Needs Google Chrome.

Chrome runs visible but off-screen by default, because headless loses results on some queries. Set
headless=true in the spec to run fully headless.

spec: {type="twogis", queries=["стоматология"], locations=["kazan"], limit=50, domain="2gis.ru", headless=false}
locations: 2GIS city codes as in 2gis.ru/<code> (moscow, spb, kazan, dubai, astana, ...).
"""
from __future__ import annotations

import csv
import os
import pathlib
import subprocess
import tempfile
import urllib.parse

NAME = "twogis"
KIND = "businesses"
REGIONS = "RU/CIS (+2GIS countries)"
ENV: list[str] = []
ABOUT = "2GIS directory: phones, emails, sites, TG/WA/VK, rating, reviews. Needs `leadgen setup 2gis` + Chrome."


def tools_dir() -> pathlib.Path:
    return pathlib.Path(os.environ.get("LEADGEN_TOOLS") or pathlib.Path.home() / ".local/share/leadgen/tools")


def parser_bin() -> pathlib.Path:
    return tools_dir() / "parser-2gis/.venv/bin/parser-2gis"


def ready() -> str | None:
    return None if parser_bin().exists() else "parser-2gis not installed (run: leadgen setup 2gis)"


def units(spec: dict) -> list[dict]:
    return [{"query": q, "location": loc, "limit": int(spec.get("limit", 50)), "domain": spec.get("domain", "2gis.ru"),
             "headless": bool(spec.get("headless", False))}
            for loc in spec.get("locations") or [] for q in spec.get("queries") or []]


def unit_key(u: dict) -> str:
    return f"{u['location']}__{u['query']}"


def fetcher(camp):
    return camp.fetcher(delay=5.0)


def g(r: dict, k: str) -> list[str]:
    return [r[f"{k} {i}"] for i in (1, 2, 3) if r.get(f"{k} {i}")]


def from_csv_row(r: dict, city: str, query: str) -> dict:
    return {
        "source_id": (r.get("2GIS URL") or "").rsplit("/", 1)[-1] or None, "url": r.get("2GIS URL"),
        "name": r.get("Наименование"), "city": r.get("Город") or city, "segment": query,
        "address": ", ".join(x for x in (r.get("Город"), r.get("Адрес")) if x),
        "country": r.get("Страна"),
        "sites": g(r, "Веб-сайт"), "phones": g(r, "Телефон"), "emails": g(r, "E-mail"),
        "telegram": g(r, "Telegram"), "whatsapp": g(r, "WhatsApp"), "vk": g(r, "ВКонтакте"),
        "instagram": g(r, "Instagram"), "facebook": g(r, "Facebook"), "youtube": g(r, "YouTube"), "x": g(r, "Twitter"),
        "rating": float(r["Рейтинг"]) if r.get("Рейтинг") else None,
        "reviews": int(float(r["Количество отзывов"])) if r.get("Количество отзывов") else None,
        "categories": [c.strip() for c in (r.get("Рубрики") or "").split(";") if c.strip()],
        "lat": float(r["Широта"]) if r.get("Широта") else None, "lon": float(r["Долгота"]) if r.get("Долгота") else None,
    }


def parse_csv(path: pathlib.Path, city: str, query: str) -> list[dict]:
    with path.open(encoding="utf-8-sig") as fh:
        return [from_csv_row(r, city, query) for r in csv.DictReader(fh)]


def collect_unit(ctx, unit: dict) -> list[dict]:
    url = f"https://{unit['domain']}/{unit['location']}/search/{urllib.parse.quote(unit['query'])}"
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td) / "out.csv"
        cmd = [str(parser_bin()), "-i", url, "-o", str(out), "-f", "csv",
               "--chrome.headless", "yes" if unit["headless"] else "no", "--parser.max-records", str(unit["limit"]),
               "--writer.csv.add-comments", "no", "--writer.csv.remove-empty-columns", "no"]
        env = {**os.environ, "PARSER_2GIS_OFFSCREEN": "" if unit["headless"] else "1"}
        ctx.fetcher._wait("2gis")  # throttle between parser launches
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900, env=env)
        if not out.exists() or out.stat().st_size == 0:
            raise RuntimeError(f"parser-2gis produced no output: {(proc.stdout + proc.stderr)[-300:]}")
        return parse_csv(out, unit["location"], unit["query"])
