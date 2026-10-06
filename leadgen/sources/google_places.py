"""Google Maps businesses via the Places API (New) Text Search. Optional, needs GOOGLE_PLACES_API_KEY.

Best coverage for local businesses outside RU/CIS: website, phone, rating, review count, Maps URL.
Up to 60 results per query (3 pages of 20). Billing applies beyond Google's free monthly usage, so keep
limits small. Without a key, use the browser route in the lead-sourcing skill instead.

spec: {type="google_places", queries=["dentist"], locations=["Lisbon, Portugal"], limit=60, language="en"}
"""
from __future__ import annotations

import os

NAME = "google_places"
KIND = "businesses"
REGIONS = "global"
ENV = ["GOOGLE_PLACES_API_KEY"]
ABOUT = "Google Maps businesses via Places API (New): site, phone, rating, reviews. Needs GOOGLE_PLACES_API_KEY."

URL = "https://places.googleapis.com/v1/places:searchText"
FIELDS = ",".join(f"places.{x}" for x in (
    "id", "displayName", "formattedAddress", "addressComponents", "location", "types", "primaryTypeDisplayName",
    "nationalPhoneNumber", "internationalPhoneNumber", "websiteUri", "rating", "userRatingCount", "googleMapsUri",
    "businessStatus")) + ",nextPageToken"


def units(spec: dict) -> list[dict]:
    return [{"query": q, "location": loc, "limit": min(int(spec.get("limit", 60)), 60),
             "language": spec.get("language", "en")}
            for loc in spec.get("locations") or [] for q in spec.get("queries") or []]


def unit_key(u: dict) -> str:
    return f"{u['location']}__{u['query']}"


def fetcher(camp):
    return camp.fetcher(delay=0.5)


def collect_unit(ctx, unit: dict) -> list[dict]:
    headers = {"X-Goog-Api-Key": os.environ["GOOGLE_PLACES_API_KEY"], "X-Goog-FieldMask": FIELDS}
    rows, token = [], None
    while len(rows) < unit["limit"]:
        body = {"textQuery": f"{unit['query']} in {unit['location']}", "languageCode": unit["language"], "pageSize": 20}
        if token:
            body["pageToken"] = token
        # the key travels in a header, not the URL, so the cache key never contains it
        data = ctx.fetcher.post_json(URL, body, headers=headers)
        for p in data.get("places") or []:
            if p.get("businessStatus") == "CLOSED_PERMANENTLY":
                continue
            comps = {t: c.get("longText") for c in p.get("addressComponents") or [] for t in c.get("types") or []}
            short = {t: c.get("shortText") for c in p.get("addressComponents") or [] for t in c.get("types") or []}
            rows.append({
                "source_id": p["id"], "url": p.get("googleMapsUri"), "name": (p.get("displayName") or {}).get("text"),
                "sites": [p["websiteUri"]] if p.get("websiteUri") else [],
                "phones": [p.get("internationalPhoneNumber") or p.get("nationalPhoneNumber")] if (p.get("internationalPhoneNumber") or p.get("nationalPhoneNumber")) else [],
                "address": p.get("formattedAddress"), "city": comps.get("locality") or comps.get("postal_town"),
                "country": short.get("country"), "lat": (p.get("location") or {}).get("latitude"),
                "lon": (p.get("location") or {}).get("longitude"),
                "categories": [(p.get("primaryTypeDisplayName") or {}).get("text")] + (p.get("types") or [])[:4],
                "rating": p.get("rating"), "reviews": p.get("userRatingCount"), "segment": unit["query"],
            })
        token = data.get("nextPageToken")
        if not token:
            break
    return rows[: unit["limit"]]
