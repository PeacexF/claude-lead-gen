"""OpenStreetMap businesses via Overpass, any country, no key.

Locations are free text geocoded with Nominatim ("Lisbon, Portugal", "Austin, TX"). Queries are presets
(see PRESETS), raw tag filters ("office=lawyer", "shop~^(bakery|pastry)$"), or plain words matched against
the business name ("pilates").
Coverage varies by country: OSM is strong in Europe, decent in big cities elsewhere; contact fields
(website/phone/email) are present for a minority of POIs, so pair with site enrichment.
Policy: Nominatim max 1 req/s with an identifying UA; Overpass is shared, so keep areas and limits sane.

spec: {type="osm", queries=[...], locations=[...], limit=500}
"""
from __future__ import annotations

import json
import re
import urllib.parse

from ..core.http import Blocked, Fetcher, UA_BOT

NAME = "osm"
KIND = "businesses"
REGIONS = "global"
ENV: list[str] = []
ABOUT = "OpenStreetMap POIs via Overpass (name, site, phone, email, address, socials, VAT). Free, any country."

OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
            "https://overpass.private.coffee/api/interpreter"]
NOMINATIM = "https://nominatim.openstreetmap.org/search"

# query word → list of tag filters (OR)
PRESETS: dict[str, list[str]] = {
    "dentist": ['amenity=dentist', 'healthcare=dentist'],
    "doctor": ['amenity=doctors', 'healthcare=doctor'],
    "clinic": ['amenity=clinic', 'healthcare=clinic'],
    "pharmacy": ['amenity=pharmacy'],
    "veterinary": ['amenity=veterinary'],
    "physiotherapist": ['healthcare=physiotherapist'],
    "psychologist": ['healthcare=psychotherapist', 'healthcare:speciality=psychology'],
    "optician": ['shop=optician'],
    "lawyer": ['office=lawyer'],
    "notary": ['office=notary'],
    "accountant": ['office=accountant', 'office=tax_advisor'],
    "real estate": ['office=estate_agent', 'shop=estate_agent'],
    "insurance": ['office=insurance'],
    "architect": ['office=architect'],
    "it company": ['office=it', 'office=company][company=it'],
    "marketing agency": ['office=advertising_agency', 'office=marketing'],
    "consulting": ['office=consulting'],
    "coworking": ['amenity=coworking_space', 'office=coworking'],
    "employment agency": ['office=employment_agency'],
    "travel agency": ['shop=travel_agency', 'office=travel_agent'],
    "restaurant": ['amenity=restaurant'],
    "cafe": ['amenity=cafe'],
    "bar": ['amenity=bar', 'amenity=pub'],
    "bakery": ['shop=bakery'],
    "hotel": ['tourism=hotel', 'tourism=guest_house', 'tourism=hostel', 'tourism=apartment'],
    "hair salon": ['shop=hairdresser'],
    "beauty salon": ['shop=beauty', 'shop=cosmetics'],
    "barber": ['shop=hairdresser][hairdresser=barber', 'shop=barber'],
    "massage": ['shop=massage'],
    "tattoo": ['shop=tattoo'],
    "gym": ['leisure=fitness_centre', 'leisure=sports_centre'],
    "yoga": ['leisure=fitness_centre][sport=yoga', 'sport=yoga'],
    "dance school": ['leisure=dance', 'amenity=dancing_school'],
    "language school": ['amenity=language_school'],
    "driving school": ['amenity=driving_school'],
    "school": ['amenity=school'],
    "kindergarten": ['amenity=kindergarten'],
    "car repair": ['shop=car_repair'],
    "car dealer": ['shop=car'],
    "car wash": ['amenity=car_wash'],
    "tyres": ['shop=tyres'],
    "plumber": ['craft=plumber'],
    "electrician": ['craft=electrician'],
    "carpenter": ['craft=carpenter'],
    "roofer": ['craft=roofer'],
    "hvac": ['craft=hvac'],
    "builder": ['craft=builder', 'office=construction_company'],
    "construction": ['office=construction_company', 'craft=builder'],
    "photographer": ['craft=photographer', 'shop=photo'],
    "printing": ['shop=copyshop', 'craft=printer'],
    "florist": ['shop=florist'],
    "furniture": ['shop=furniture'],
    "kitchen": ['shop=kitchen'],
    "hardware": ['shop=hardware', 'shop=doityourself'],
    "jewelry": ['shop=jewelry'],
    "clothes": ['shop=clothes', 'shop=boutique'],
    "shoes": ['shop=shoes'],
    "electronics": ['shop=electronics', 'shop=mobile_phone', 'shop=computer'],
    "bicycle": ['shop=bicycle'],
    "pet shop": ['shop=pet'],
    "pet grooming": ['shop=pet_grooming'],
    "laundry": ['shop=laundry', 'shop=dry_cleaning'],
    "funeral": ['shop=funeral_directors'],
    "storage": ['shop=storage_rental'],
    "wedding": ['shop=wedding'],
    "winery": ['craft=winery', 'shop=wine'],
    "brewery": ['craft=brewery'],
    "marina": ['leisure=marina'],
    "camping": ['tourism=camp_site'],
    "museum": ['tourism=museum'],
}


def units(spec: dict) -> list[dict]:
    return [{"query": q, "location": loc, "limit": int(spec.get("limit", 500))}
            for loc in spec.get("locations") or [] for q in spec.get("queries") or []]


def unit_key(u: dict) -> str:
    return f"{u['location']}__{u['query']}"


def fetcher(camp) -> Fetcher:
    return camp.fetcher(ua=UA_BOT, delay=1.0, host_delays={"nominatim.openstreetmap.org": 1.2}, timeout=180)


def geocode(f: Fetcher, location: str) -> dict:
    url = NOMINATIM + "?" + urllib.parse.urlencode({"q": location, "format": "jsonv2", "limit": 1, "addressdetails": 1})
    hits = f.json(url)
    if not hits:
        raise ValueError(f"location not found: {location}")
    return hits[0]


def area_clause(g: dict) -> str:
    osm_id = int(g["osm_id"])
    if g["osm_type"] == "relation":
        return f"area(id:{3600000000 + osm_id})->.a;", "(area.a)"
    if g["osm_type"] == "way" and g.get("category") in ("boundary", "place"):
        return f"area(id:{2400000000 + osm_id})->.a;", "(area.a)"
    s, n, w, e = g["boundingbox"]
    return "", f"({s},{w},{n},{e})"


def filters(query: str) -> list[str]:
    q = query.strip()
    if q.lower() in PRESETS:
        return PRESETS[q.lower()]
    if re.match(r"^[\w:]+\s*[=~]", q):
        return [q.replace(" ", "")]
    # plain word: match names of anything that is a business-like POI
    name = q.replace('"', "")
    return [f'name~"{name}",i][{k}' for k in ("shop", "office", "amenity", "craft", "healthcare", "tourism", "leisure")]


def tagfilter(f: str) -> str:
    """'office=lawyer' → ["office"="lawyer"]; 'shop~^(a|b)$' → ["shop"~"^(a|b)$"]; supports ']['-joined parts."""
    parts = []
    for p in f.split("]["):
        if p.startswith("name~"):
            parts.append(f'["name"~{p[5:].split(",")[0]},i]')
            continue
        m = re.match(r"^([\w:]+)\s*([=~])\s*(.*)$", p)
        parts.append(f'["{m.group(1)}"{m.group(2)}"{m.group(3)}"]' if m else f'["{p}"]')
    return "".join(parts)


def overpass(f: Fetcher, ql: str) -> dict:
    last = None
    for ep in OVERPASS:
        try:
            status, _, text = f.request(ep, data=urllib.parse.urlencode({"data": ql}).encode(),
                                        headers={"Content-Type": "application/x-www-form-urlencoded"})
        except Blocked as e:
            last = e
            continue
        if status == 200 and text.lstrip().startswith("{"):
            return json.loads(text)
        last = RuntimeError(f"overpass {status}: {text[:200]}")
    raise last or RuntimeError("overpass failed")


def to_row(el: dict, g: dict, unit: dict) -> dict | None:
    t = el.get("tags") or {}
    name = t.get("name") or t.get("brand") or t.get("operator")
    if not name:
        return None
    get = lambda *ks: [t[k] for k in ks if t.get(k)]  # noqa: E731
    split = lambda vs: [x.strip() for v in vs for x in re.split(r"[;,]\s*(?=\+|\d|http|[\w.+-]+@)", v) if x.strip()]  # noqa: E731
    addr = ", ".join(x for x in [" ".join(get("addr:street", "addr:housenumber")), t.get("addr:postcode"),
                                 t.get("addr:city")] if x)
    country = ((g.get("address") or {}).get("country_code") or "").upper() or None
    lat = el.get("lat") or (el.get("center") or {}).get("lat")
    lon = el.get("lon") or (el.get("center") or {}).get("lon")
    cats = [f"{k}={t[k]}" for k in ("shop", "office", "amenity", "craft", "healthcare", "tourism", "leisure") if t.get(k)]
    legal = {}
    if t.get("ref:vatin"):
        legal = {"name": t.get("official_name"), "registry_ids": {"vat": t["ref:vatin"]}}
    elif t.get("official_name"):
        legal = {"name": t["official_name"], "registry_ids": {}}
    return {
        "source_id": f"{el['type']}/{el['id']}", "url": f"https://www.openstreetmap.org/{el['type']}/{el['id']}",
        "name": name, "sites": split(get("website", "contact:website", "url")),
        "phones": split(get("phone", "contact:phone", "mobile", "contact:mobile")),
        "emails": split(get("email", "contact:email")),
        "address": addr or None, "city": t.get("addr:city") or g.get("name"), "country": country,
        "lat": lat, "lon": lon, "categories": cats, "segment": unit["query"],
        "facebook": get("contact:facebook", "facebook"), "instagram": get("contact:instagram", "instagram"),
        "linkedin": get("contact:linkedin"), "telegram": get("contact:telegram"), "whatsapp": get("contact:whatsapp"),
        "vk": get("contact:vk"), "x": get("contact:twitter"), "youtube": get("contact:youtube"),
        "legal": legal or None,
        "osm_hours": t.get("opening_hours"),
    }


def collect_unit(ctx, unit: dict) -> list[dict]:
    f = ctx.fetcher
    g = geocode(f, unit["location"])
    pre, scope = area_clause(g)
    body = "".join(f"nwr{tagfilter(x)}{scope};" for x in filters(unit["query"]))
    ql = f"[out:json][timeout:170];{pre}({body});out center tags {unit['limit']};"
    data = overpass(f, ql)
    rows = [r for r in (to_row(el, g, unit) for el in data.get("elements") or []) if r]
    # some tags give social URLs as handles; normalize obvious ones
    for r in rows:
        for k, base in (("instagram", "https://instagram.com/"), ("facebook", "https://facebook.com/"),
                        ("telegram", "https://t.me/"), ("x", "https://x.com/")):
            r[k] = [v if v.startswith("http") else base + v.lstrip("@") for v in r[k]]
    return rows
