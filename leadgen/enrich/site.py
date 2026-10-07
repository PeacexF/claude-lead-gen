"""Static crawl of a business website: homepage + up to N contact/about/team/legal pages. Generalized from claude-kit.

Per site (plain GETs only, never submits forms, throttled per host):
- contacts: emails (mailto + text), phones (tel: links), socials (LinkedIn, Facebook, Instagram, X, YouTube, TikTok,
  Telegram, WhatsApp, VK, MAX)
- legal identity: RU ИНН (checksum) / ОГРН, UK company number, EU VAT ids, DE Handelsregister, legal-entity names
- people: name + role pairs from team pages when marked up plainly (best effort; verify before use)
- tech stack (see tech.py) and site health: https, cert ok, mobile viewport, form, privacy link, cookie notice,
  copyright year, page title/description
"""
from __future__ import annotations

import datetime
import html as htmllib
import re
import ssl
import urllib.error
import urllib.parse

from ..core import schema
from ..core.http import UnsafeURL
from . import tech

INNER_PATH = re.compile(
    r"contact|kontakt|contatt|contacto|contato|kontakty|svyaz|about|about-us|o-nas|o-kompan|uber-uns|ueber-uns|chi-siamo|"
    r"quienes|sobre|qui-sommes|a-propos|team|our-team|staff|people|leadership|management|equipe|equipo|"
    r"impressum|imprint|legal|mentions-legales|aviso-legal|note-legali|privacy|datenschutz|politik|konfid|rekvizit|"
    r"location|find-us|visit", re.I)
INNER_TEXT = re.compile(
    r"contact|kontakt|contatt|contacto|contato|about|team|staff|people|impressum|imprint|legal|privacy|"
    r"контакт|о компании|о нас|команда|реквизит|политик", re.I)
SKIP = re.compile(r"/(auth|login|signin|signup|register|cart|basket|checkout|order|account|my-account|wp-admin|feed)\b|"
                  r"\.(pdf|docx?|xlsx?|jpe?g|png|gif|webp|svg|zip|mp4)$", re.I)

INN = re.compile(r"ИНН[\s:\-№]*(\d{12}|\d{10})(?!\d)")
OGRN = re.compile(r"ОГРН(?:ИП)?[\s:\-№]*(\d{15}|\d{13})(?!\d)")
UK_CO = re.compile(r"(?:company|registration|registered|reg\.?)\s*(?:no\.?|number|num\.?)?\s*[:#]?\s*((?:SC|NI|OC|SO|NC)?\d{6,8})\b", re.I)
EU_VAT = re.compile(r"\b(?:VAT|USt-?IdNr\.?|TVA|IVA|NIF|BTW|MwSt|P\.?\s?IVA)[^A-Z0-9]{0,15}"
                    r"((?:AT|BE|BG|CY|CZ|DE|DK|EE|EL|ES|FI|FR|HR|HU|IE|IT|LT|LU|LV|MT|NL|PL|PT|RO|SE|SI|SK|GB|XI)\s?[0-9A-Z]{8,12})\b")
DE_HR = re.compile(r"\b(HR[AB]\s?\d{3,6}(?:\s?[A-Z])?)\b")
LEGAL_NAME = re.compile(
    r"((?:ООО|ОАО|АО|ЗАО|ПАО|АНО)\s*[«\"“][^»\"”]{2,60}[»\"”]|(?:ИП|Индивидуальный предприниматель)\s+[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+){0,2}|"
    r"\b[A-Z][\w&.,'\- ]{1,60}?\s(?:Ltd|Limited|LLC|L\.L\.C\.|Inc\.?|GmbH|UG|AG|S\.?L\.?|S\.?A\.?|Lda\.?|S\.?r\.?l\.?|B\.?V\.?|SAS|SARL|Sp\. z o\.o\.|Oy|AB|ApS|AS|plc)\b)")
ROLE = re.compile(r"\b(founder|co-?founder|owner|ceo|chief [a-z]+ officer|managing director|director|general manager|"
                  r"head of [a-z ]+|partner|principal|president|vp [a-z ]+|cto|cmo|coo|cfo|"
                  r"gesch[äa]ftsf[üu]hrer|inhaber|propriet[áa]rio|director[a]? general|g[ée]rant|"
                  r"генеральный директор|директор|основатель|владелец|руководитель)\b", re.I)
PERSON = re.compile(r"\b([A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ'\-]{1,20}(?:\s[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ'\-]{1,20}){1,2}|[А-ЯЁ][а-яё]{1,20}\s[А-ЯЁ][а-яё]{1,20}(?:\s[А-ЯЁ][а-яё]{1,20})?)\b")
COPYRIGHT = re.compile(r"(?:©|&copy;|copyright)[^0-9]{0,30}(?:\d{4}\s*[-–—]\s*)?(20\d\d|19\d\d)", re.I)


def inn_ok(s: str) -> bool:
    d = [int(c) for c in s]
    chk = lambda ws: sum(w * x for w, x in zip(ws, d)) % 11 % 10  # noqa: E731
    if len(d) == 10:
        return chk([2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[9]
    return (len(d) == 12 and chk([7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[10]
            and chk([3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[11])


def text_of(html: str) -> str:
    t = re.sub(r"<(script|style|noscript|svg)[^>]*>.*?</\1>|<[^>]+>", " ", html, flags=re.S | re.I)
    return re.sub(r"\s+", " ", htmllib.unescape(t))


def anchors(html: str, base: str) -> list[tuple[str, str]]:
    out = []
    for m in re.finditer(r"<a\b([^>]*)>(.*?)</a>", html, re.S | re.I):
        href = re.search(r'href\s*=\s*["\']([^"\']+)["\']', m.group(1))
        if href:
            try:
                out.append((urllib.parse.urljoin(base, htmllib.unescape(href.group(1).strip())), text_of(m.group(2)).strip()[:120]))
            except ValueError:
                continue
    return out


def meta(html: str, name: str) -> str | None:
    m = re.search(rf'<meta[^>]+(?:name|property)=["\']{name}["\'][^>]*content=["\']([^"\']*)', html, re.I) or \
        re.search(rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:name|property)=["\']{name}["\']', html, re.I)
    return htmllib.unescape(m.group(1)).strip()[:300] if m else None


def people_from(text: str) -> list[dict]:
    """Name + role pairs that sit next to each other ('Jane Smith, Founder' / 'CEO: John Doe'). Best effort."""
    found = []
    for m in ROLE.finditer(text):
        window = text[max(0, m.start() - 60): m.end() + 60]
        names = [n for n in PERSON.findall(window) if not ROLE.search(n) and len(n.split()) <= 3]
        if names:
            # nearest name to the role mention
            pos = m.start() - max(0, m.start() - 60)
            best = min(names, key=lambda n: abs(window.find(n) - pos))
            found.append({"name": best.strip(), "role": m.group(1).strip(), "source": "site"})
    uniq = {}
    for p in found:
        uniq.setdefault(p["name"], p)
    return list(uniq.values())[:8]


def fetch(fetcher, url: str) -> tuple[str, str, bool]:
    """(final_url, html, cert_ok). Retries without cert verification so a broken cert is a finding, not a dead end."""
    try:
        status, final, html = fetcher.request(url, html_only=True, max_bytes=1_500_000, public_only=True)
        cert_ok = True
    except (ssl.SSLError, urllib.error.URLError) as e:
        is_ssl = isinstance(e, ssl.SSLError) or isinstance(getattr(e, "reason", None), ssl.SSLError)
        if isinstance(e, UnsafeURL) or not is_ssl:
            raise
        status, final, html = fetcher.request(url, html_only=True, max_bytes=1_500_000, insecure_fallback=True,
                                              public_only=True)
        cert_ok = False
    if status >= 400:
        raise urllib.error.HTTPError(url, status, f"HTTP {status}", {}, None)
    return final, html, cert_ok


def crawl(fetcher, site: str, max_inner: int = 4) -> dict:
    site = site if site.startswith("http") else "http://" + site
    res = {"url": site, "reachable": False, "checked": datetime.date.today().isoformat()}
    try:
        final, home, cert_ok = fetch(fetcher, site)
    except urllib.error.HTTPError as e:
        return {**res, "status": e.code, "error": "HTTPError"}
    except Exception as e:
        return {**res, "error": type(e).__name__}
    if not home:
        return {**res, "error": "not_html"}
    host = urllib.parse.urlsplit(final).hostname
    inner = []
    for h, t in anchors(home, final):
        try:
            u = urllib.parse.urlsplit(h)
        except ValueError:
            continue
        if (u.hostname or "").removeprefix("www.") != (host or "").removeprefix("www.") or not u.scheme.startswith("http"):
            continue
        if (INNER_PATH.search(u.path) or INNER_TEXT.search(t)) and not SKIP.search(u.path):
            clean = u._replace(fragment="", query="").geturl()
            if clean not in inner and clean.rstrip("/") != final.rstrip("/"):
                inner.append(clean)
    pages = [(final, home)]
    for u in inner[:max_inner]:
        try:
            fu, h, _ = fetch(fetcher, u)
            if h:
                pages.append((fu, h))
        except Exception:
            continue

    allhtml = "\n".join(h for _, h in pages)
    alltext = " ".join(text_of(h) for _, h in pages)
    hrefs = [htmllib.unescape(h) for h in re.findall(r'href\s*=\s*["\']([^"\']+)', allhtml, re.I)]
    low_home = home.lower()

    emails = []
    for e in [h[7:] for h in hrefs if h.lower().startswith("mailto:")] + schema.EMAIL_RX.findall(alltext):
        ce = schema.clean_email(urllib.parse.unquote(e))
        if ce and ce not in emails:
            emails.append(ce)
    phones = []
    for h in hrefs:
        if h.lower().startswith("tel:"):
            d = re.sub(r"[^\d+]", "", urllib.parse.unquote(h[4:]))
            if len(re.sub(r"\D", "", d)) >= 7 and d not in phones:
                phones.append(d)
    socials = {}
    for k, rx in schema.SOCIAL_PATTERNS.items():
        vals = list(dict.fromkeys(re.sub(r"[?#].*$", "", m.group(0)).rstrip("/") for m in re.finditer(rx, allhtml, re.I)))
        if vals:
            socials[k] = vals[:3]

    ids = {}
    inns = sorted({m for m in INN.findall(alltext) if inn_ok(m)})
    if inns:
        ids["inn"] = inns[0] if len(inns) == 1 else inns
    ogrn = sorted(set(OGRN.findall(alltext)))
    if ogrn:
        ids["ogrn"] = ogrn[0] if len(ogrn) == 1 else ogrn
    vat = sorted({re.sub(r"\s", "", v) for v in EU_VAT.findall(alltext)})
    if vat:
        ids["vat"] = vat[0] if len(vat) == 1 else vat
    uk = sorted(set(UK_CO.findall(alltext))) if re.search(r"england|wales|scotland|companies house|united kingdom|\buk\b", alltext, re.I) else []
    if uk:
        ids["company_number"] = uk[0] if len(uk) == 1 else uk
    hr = sorted(set(DE_HR.findall(alltext))) if re.search(r"amtsgericht|registergericht|handelsregister", alltext, re.I) else []
    if hr:
        ids["handelsregister"] = hr[0] if len(hr) == 1 else hr
    legal_names = list(dict.fromkeys(re.sub(r"\s+", " ", m).strip() for m in LEGAL_NAME.findall(alltext)))[:3]

    found_tech = sorted(set(tech.detect(allhtml)))
    years = [int(y) for y in COPYRIGHT.findall(low_home)]
    return {
        **res, "reachable": True, "final_url": final, "https": final.startswith("https"), "cert_ok": cert_ok,
        "title": htmllib.unescape(tm.group(1)).strip()[:200] if (tm := re.search(r"<title[^>]*>(.*?)</title>", home, re.S | re.I)) else None,
        "description": meta(home, "description") or meta(home, "og:description"),
        "lang": (re.search(r'<html[^>]+lang=["\']([\w-]+)', home, re.I) or [None, None])[1],
        "mobile": bool(re.search(r'<meta[^>]+name=["\']viewport', low_home)),
        "has_form": "<form" in allhtml.lower(),
        "privacy_link": bool(re.search(r"privacy|datenschutz|confidential|privacidad|privacidade|конфиденциальн|персональных данных", allhtml, re.I)),
        "cookie_notice": bool(re.search(r"cookie|куки", low_home)),
        "copyright_year": max(years) if years else None,
        "builder": tech.builder(found_tech), "tech": found_tech,
        "pages": [u for u, _ in pages],
        "emails": emails[:8], "phones": phones[:5], "socials": socials,
        "registry_ids": ids, "legal_names": legal_names, "people": people_from(" ".join(text_of(h) for _, h in pages[1:]) or alltext),
        "bytes": len(home),
    }


def apply(lead: dict, r: dict) -> dict:
    """Fold a crawl result into the lead (contacts appended, site block replaced)."""
    lead["site"] = {k: r.get(k) for k in ("url", "final_url", "reachable", "status", "error", "https", "cert_ok", "title",
                                          "description", "lang", "mobile", "has_form", "privacy_link", "cookie_notice",
                                          "copyright_year", "builder", "tech", "pages", "checked")}
    if not r.get("reachable"):
        return lead
    have = {e["value"] for e in lead.get("emails") or []}
    for e in r["emails"]:
        if e not in have:
            lead.setdefault("emails", []).append({"value": e, "source": "site", "type": schema.email_type(e), "verified": "none"})
    for p in r["phones"]:
        d = re.sub(r"\D", "", p)
        if d and d not in lead.get("phones", []):
            lead.setdefault("phones", []).append(d)
    for k, vals in r["socials"].items():
        cur = lead.setdefault("socials", {}).setdefault(k, [])
        cur.extend(v for v in vals if v not in cur)
    legal = lead.setdefault("legal", {"name": None, "registry_ids": {}})
    legal["registry_ids"] = {**r["registry_ids"], **(legal.get("registry_ids") or {})}
    if not legal.get("name") and r["legal_names"]:
        legal["name"] = r["legal_names"][0]
    names = {p.get("name") for p in lead.get("people") or []}
    lead.setdefault("people", []).extend(p for p in r["people"] if p["name"] not in names)
    # site-derived signals
    sig = {(s.get("type")) for s in lead.get("signals") or []}
    year = datetime.date.today().year
    def add(t, v):
        if t not in sig:
            lead.setdefault("signals", []).append({"type": t, "value": v, "source": r.get("final_url"), "date": r.get("checked")})
    if r.get("copyright_year") and r["copyright_year"] <= year - 3:
        add("outdated_site", f"copyright {r['copyright_year']}")
    if not r.get("https"):
        add("no_https", r.get("final_url"))
    if r.get("cert_ok") is False:
        add("broken_ssl", r.get("final_url"))
    if not r.get("mobile"):
        add("not_mobile_friendly", "no viewport meta")
    if r.get("has_form") and not r.get("privacy_link"):
        add("form_without_privacy_link", r.get("final_url"))
    return lead
