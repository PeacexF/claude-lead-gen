"""Lead record helpers: normalization of domains, phones, emails, and the "own website" test.

A lead is a plain dict (see SPEC.md §4.2). Sources emit partial records; merge.py folds them into leads.
"""
from __future__ import annotations

import datetime
import hashlib
import re
import urllib.parse

# Links that are not the business's own website: social networks, link-in-bio, directories, marketplaces, booking hosts.
NOT_OWN = re.compile(
    r"(^|\.)("
    r"vk\.com|vk\.ru|vk\.link|ok\.ru|instagram\.com|facebook\.com|fb\.com|fb\.me|m\.me|messenger\.com|linkedin\.com|"
    r"twitter\.com|x\.com|t\.me|telegram\.me|wa\.me|whatsapp\.com|api\.whatsapp\.com|youtube\.com|youtu\.be|tiktok\.com|"
    r"pinterest\.[a-z.]+|threads\.net|snapchat\.com|"
    r"taplink\.(cc|ws|at)|linktr\.ee|linktree\.com|beacons\.ai|bio\.link|mssg\.me|hipolink\.[a-z]+|lnk\.bio|"
    r"avito\.ru|profi\.ru|yandex\.[a-z]+|2gis\.[a-z]+|zoon\.ru|yell\.ru|flamp\.ru|hh\.ru|ozon\.ru|wildberries\.ru|rutube\.ru|dzen\.ru|"
    r"dikidi\.(net|ru)|yclients\.com|max\.ru|"
    r"google\.[a-z.]+|goo\.gl|g\.page|business\.site|sites\.google\.com|maps\.app\.goo\.gl|"
    r"yelp\.[a-z.]+|tripadvisor\.[a-z.]+|booking\.com|airbnb\.[a-z.]+|thefork\.[a-z.]+|opentable\.[a-z.]+|"
    r"treatwell\.[a-z.]+|fresha\.com|booksy\.com|doctolib\.[a-z]+|zocdoc\.com|trustpilot\.com|"
    r"etsy\.com|amazon\.[a-z.]+|ebay\.[a-z.]+|clients\.site|bit\.ly|tinyurl\.com"
    r")$", re.I)

# Public ATS job boards; a link to one names the company's board token.
JOB_BOARD = re.compile(
    r"https?://(?:(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?(?P<greenhouse>[\w-]+)|"
    r"jobs\.(?:eu\.)?lever\.co/(?P<lever>[\w-]+)|jobs\.ashbyhq\.com/(?P<ashby>[\w.-]+)|"
    r"apply\.workable\.com/(?P<workable>[\w-]+)|(?P<recruitee>[\w-]+)\.recruitee\.com|"
    r"(?P<personio>[\w-]+)\.jobs\.personio\.(?:de|com)|(?P<bamboohr>[\w-]+)\.bamboohr\.com/(?:careers|jobs))", re.I)


def job_boards(text: str) -> list[dict]:
    """ATS board links in a page or post → [{ats, token, url}], deduped."""
    boards = []
    for m in JOB_BOARD.finditer(text or ""):
        ats, token = next((k, v) for k, v in m.groupdict().items() if v)
        if token.lower() not in ("embed", "js", "api", "www") and (ats, token.lower()) not in {(b["ats"], b["token"]) for b in boards}:
            boards.append({"ats": ats, "token": token.lower(), "url": m.group(0)})
    return boards


SOCIAL_PATTERNS = {
    "linkedin": r"https?://([a-z]{2,3}\.)?linkedin\.com/(company|in|school)/[^/?#\s\"'<>]+",
    "facebook": r"https?://(www\.|m\.)?(facebook|fb)\.com/(?!sharer|share|plugins|dialog|tr\b|2008)[^?#\s\"'<>]+",
    "instagram": r"https?://(www\.)?instagram\.com/(?!p/|explore|accounts)[^/?#\s\"'<>]+",
    "x": r"https?://(www\.)?(twitter|x)\.com/(?!intent|share|home|search)[A-Za-z0-9_]{1,15}",
    "youtube": r"https?://(www\.)?youtube\.com/(@|c/|channel/|user/)[^?#\s\"'<>]+",
    "tiktok": r"https?://(www\.)?tiktok\.com/@[^/?#\s\"'<>]+",
    "telegram": r"https?://(t\.me|telegram\.me)/(?!share|joinchat/?$)[^?#\s\"'<>]+",
    "whatsapp": r"https?://(wa\.me|api\.whatsapp\.com|chat\.whatsapp\.com)/[^#\s\"'<>]*",
    "vk": r"https?://(m\.)?vk\.(com|ru)/(?!share|widget)[^?#\s\"'<>]+",
    "max": r"https?://max\.ru/[^?#\s\"'<>]+",
}
SOCIAL_KEYS = list(SOCIAL_PATTERNS)

EMAIL_RX = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[a-zа-я]{2,}", re.I)
EMAIL_JUNK = re.compile(r"\.(png|jpe?g|webp|svg|gif|css|js)$|example\.|sentry|wixpress|@domain\.|@email\.|"
                        r"@sentry|@2x|u003e|noreply|no-reply|donotreply|@mysite|@yoursite|@company\.com$|user@|name@|"
                        r"@test\.|\.local$", re.I)
GENERIC_LOCAL = re.compile(r"^(info|hello|hi|contact|contacts|office|admin|mail|sales|support|team|enquiries|enquiry|"
                           r"inquiries|booking|bookings|reception|kontakt|kontakte|post|general|help|service|marketing|"
                           r"press|media|jobs|careers|hr|billing|accounts|orders|shop|store|zakaz|info\d*)$", re.I)


def host(url: str | None) -> str | None:
    """Lowercase host without www., punycoded."""
    if not url:
        return None
    url = url.strip()
    if not re.match(r"^[a-z][a-z0-9+.-]*://", url, re.I):
        url = "http://" + url
    try:
        h = (urllib.parse.urlsplit(url).hostname or "").lower().strip(".")
    except ValueError:
        return None
    h = h.removeprefix("www.")
    if not h or "." not in h:
        return None
    try:
        return h.encode("idna").decode() if not h.isascii() else h
    except UnicodeError:
        return None


def is_own_site(url: str | None) -> bool:
    h = host(url)
    return bool(h) and not NOT_OWN.search(h)


def own_sites(urls) -> list[str]:
    return [u for u in (urls or []) if is_own_site(u)]


def phone_digits(phone: str | None, default_cc: str | None = None) -> str | None:
    """Digits with country code when inferable. RU/KZ 8XXXXXXXXXX → 7XXXXXXXXXX."""
    if not phone:
        return None
    d = re.sub(r"\D", "", phone)
    if phone.strip().startswith("00"):
        d = d[2:]
    if len(d) == 11 and d[0] == "8" and (default_cc in (None, "7")):
        d = "7" + d[1:]
    elif default_cc and len(d) <= 10 and not phone.strip().startswith("+"):
        d = default_cc + d.lstrip("0")
    return d if 7 <= len(d) <= 15 else None


def clean_email(e: str | None) -> str | None:
    if not e:
        return None
    e = e.strip().strip(".,;:()<>[]\"'").lower()
    e = re.sub(r"^mailto:", "", e).split("?")[0]
    if not EMAIL_RX.fullmatch(e) or EMAIL_JUNK.search(e):
        return None
    return e


def email_type(e: str) -> str:
    return "generic" if GENERIC_LOCAL.match(e.split("@")[0]) else "personal"


def norm_name(name: str | None) -> str:
    n = (name or "").lower()
    n = re.sub(r"[«»\"'“”„`]", "", n)
    n = re.sub(r"\b(ооо|ип|ао|зао|оао|llc|ltd|limited|inc|gmbh|lda|sa|sl|srl|bv|plc|co|corp|company)\b\.?", " ", n)
    return re.sub(r"[^\w]+", " ", n).strip()


def lead_id(rec: dict) -> str:
    """Stable id: domain of the own website, else a hash of name + city + first phone."""
    for u in [rec.get("website")] + list(rec.get("sites") or []):
        if is_own_site(u):
            return host(u)
    basis = "|".join([norm_name(rec.get("name")), (rec.get("city") or "").lower(),
                      (rec.get("phones") or [""])[0] or ""])
    return "h-" + hashlib.sha1(basis.encode()).hexdigest()[:12]


def empty_lead() -> dict:
    return {
        "id": None, "name": None, "names": [], "domain": None, "website": None, "country": None, "city": None,
        "address": None, "lat": None, "lon": None, "categories": [], "segment": None,
        "phones": [], "emails": [], "socials": {k: [] for k in SOCIAL_KEYS}, "people": [],
        "legal": {"name": None, "registry_ids": {}}, "rating": None, "reviews": None,
        "site": {}, "job_boards": [], "signals": [], "sources": [], "score": None, "score_breakdown": {}, "tier": None,
        "notes": "", "status": "new",
    }


def add_signal(lead: dict, typ: str, value, source: str | None, date: str | None = None) -> bool:
    """Append a signal unless one of the same type is already there. Returns True when added."""
    if any(s.get("type") == typ for s in lead.get("signals") or []):
        return False
    lead.setdefault("signals", []).append({"type": typ, "value": value, "source": source,
                                           "date": date or datetime.date.today().isoformat()})
    return True
