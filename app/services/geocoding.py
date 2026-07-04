"""
Geocoding for TwoTable — Mapbox forward geocoding with a MongoDB cache.

`geocode("BS1 5TR")` → (lat, lng, "Bristol, England, United Kingdom").

Design
------
- Provider: Mapbox Geocoding v6 (set MAPBOX_TOKEN in .env). High-quality, global,
  great UK postcode coverage.
- Cache-first: every lookup is memoised in the `geocoding_cache` collection
  (keyed by the normalised query) so we never pay for or wait on a repeat call.
- Graceful: with no token, or on any network/API error, returns None and the
  callers fall back to city-string matching — the app keeps working offline.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, Tuple

import httpx

from app.core.config import settings
from app.db import mongo

logger = logging.getLogger(__name__)

CACHE = "geocoding_cache"
_MAPBOX_URL = "https://api.mapbox.com/search/geocode/v6/forward"
_POSTCODES_IO = "https://api.postcodes.io"

LatLngName = Tuple[float, float, str]

# City-centre fallback for launch cities, used when a user gives only a city name (no
# postcode) and there's no Mapbox token. Keeps distance-matching + travel times working.
_UK_CITY_CENTRES: dict[str, LatLngName] = {
    "bristol": (51.4545, -2.5879, "Bristol, England"),
    "bath": (51.3811, -2.3590, "Bath, England"),
    "london": (51.5074, -0.1278, "London, England"),
    "manchester": (53.4808, -2.2426, "Manchester, England"),
    "birmingham": (52.4862, -1.8904, "Birmingham, England"),
    "leeds": (53.8008, -1.5491, "Leeds, England"),
    "cardiff": (51.4816, -3.1791, "Cardiff, Wales"),
}


def _norm(query: str) -> str:
    return " ".join((query or "").lower().split())


async def _from_cache(key: str) -> Optional[LatLngName]:
    doc = await mongo.get_db()[CACHE].find_one({"_id": key})
    if doc and doc.get("lat") is not None and doc.get("lng") is not None:
        return doc["lat"], doc["lng"], doc.get("name", "")
    return None


async def _to_cache(key: str, query: str, result: Optional[LatLngName]) -> None:
    lat, lng, name = result if result else (None, None, None)
    await mongo.get_db()[CACHE].update_one(
        {"_id": key},
        {"$set": {"query": query, "lat": lat, "lng": lng, "name": name,
                  "updated_at": datetime.now(timezone.utc)}},
        upsert=True,
    )


async def _mapbox(query: str, country: Optional[str]) -> Optional[LatLngName]:
    if not settings.MAPBOX_TOKEN:
        return None
    params = {"q": query, "access_token": settings.MAPBOX_TOKEN, "limit": 1}
    if country:
        params["country"] = country
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(_MAPBOX_URL, params=params)
        if resp.status_code != 200:
            logger.warning("Mapbox geocode %s → HTTP %s", query, resp.status_code)
            return None
        features = resp.json().get("features") or []
        if not features:
            return None
        f = features[0]
        lng, lat = f["geometry"]["coordinates"]          # GeoJSON is [lng, lat]
        props = f.get("properties", {})
        name = props.get("full_address") or props.get("name") or query
        return float(lat), float(lng), name
    except Exception as exc:                              # network, parse, timeout
        logger.warning("Mapbox geocode failed for %r — %s", query, exc)
        return None


async def _postcodes_io(query: str) -> Optional[LatLngName]:
    """Free, keyless UK geocoding (postcodes.io). Tries a full postcode, then an outcode
    (e.g. 'BS1'), then a plain city-centre lookup. No API key, great UK coverage — this is
    what makes routing + distance-matching work when no Mapbox token is set."""
    q = query.strip()
    slug = q.replace(" ", "").upper()
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            # 1) full postcode
            r = await client.get(f"{_POSTCODES_IO}/postcodes/{slug}")
            if r.status_code == 200:
                res = (r.json() or {}).get("result") or {}
                if res.get("latitude") is not None:
                    name = ", ".join(x for x in (res.get("admin_ward"), res.get("admin_district"),
                                                 res.get("country")) if x) or q
                    return float(res["latitude"]), float(res["longitude"]), name
            # 2) outcode (first half of a postcode)
            outcode = slug.split()[0] if " " in q else slug[: max(2, len(slug) - 3)]
            r = await client.get(f"{_POSTCODES_IO}/outcodes/{outcode}")
            if r.status_code == 200:
                res = (r.json() or {}).get("result") or {}
                if res.get("latitude") is not None:
                    name = ", ".join(x for x in (res.get("admin_district") or [None])[:1] if x) or q
                    return float(res["latitude"]), float(res["longitude"]), name or q
    except Exception as exc:                                  # network, parse, timeout
        logger.warning("postcodes.io lookup failed for %r — %s", query, exc)
    # 3) city-centre fallback for launch cities
    centre = _UK_CITY_CENTRES.get(_norm(query))
    return centre


async def geocode(query: str, country: Optional[str] = "gb") -> Optional[LatLngName]:
    """Forward-geocode a postcode / city / address. Cache-first, never raises.

    Provider order: cache → Mapbox (if a token is set) → postcodes.io (free, UK) →
    a built-in city-centre table. So real users still get coordinates on the free tier.
    """
    query = (query or "").strip()
    if not query:
        return None
    key = _norm(query)
    cached = await _from_cache(key)
    if cached:
        return cached
    result = await _mapbox(query, country)
    if not result:
        result = await _postcodes_io(query)
    if result:
        await _to_cache(key, query, result)
    return result


async def reverse(lat: float, lng: float) -> Optional[str]:
    """Reverse-geocode coordinates → a human place name. Cache-first, never raises."""
    key = f"rev:{round(lat,4)},{round(lng,4)}"
    cached = await mongo.get_db()[CACHE].find_one({"_id": key})
    if cached and cached.get("name"):
        return cached["name"]
    if not settings.MAPBOX_TOKEN:
        # Free UK reverse geocode: nearest postcode's district (no key needed).
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(f"{_POSTCODES_IO}/postcodes",
                                     params={"lon": lng, "lat": lat, "limit": 1})
            res = ((r.json() or {}).get("result") or []) if r.status_code == 200 else []
            if res:
                first = res[0]
                name = ", ".join(x for x in (first.get("admin_ward"),
                                             first.get("admin_district")) if x) or first.get("postcode")
                if name:
                    await mongo.get_db()[CACHE].update_one(
                        {"_id": key}, {"$set": {"lat": lat, "lng": lng, "name": name,
                                                "updated_at": datetime.now(timezone.utc)}}, upsert=True)
                return name
        except Exception as exc:
            logger.warning("postcodes.io reverse failed (%s,%s) — %s", lat, lng, exc)
        return None
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                "https://api.mapbox.com/search/geocode/v6/reverse",
                params={"longitude": lng, "latitude": lat, "limit": 1,
                        "access_token": settings.MAPBOX_TOKEN},
            )
        feats = resp.json().get("features") or [] if resp.status_code == 200 else []
        if not feats:
            return None
        name = feats[0].get("properties", {}).get("full_address") or feats[0].get("properties", {}).get("name")
        await mongo.get_db()[CACHE].update_one(
            {"_id": key}, {"$set": {"lat": lat, "lng": lng, "name": name,
                                    "updated_at": datetime.now(timezone.utc)}}, upsert=True)
        return name
    except Exception as exc:
        logger.warning("Mapbox reverse failed (%s,%s) — %s", lat, lng, exc)
        return None
