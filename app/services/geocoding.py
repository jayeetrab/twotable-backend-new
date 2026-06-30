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

LatLngName = Tuple[float, float, str]


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


async def geocode(query: str, country: Optional[str] = "gb") -> Optional[LatLngName]:
    """Forward-geocode a postcode / city / address. Cache-first, never raises."""
    query = (query or "").strip()
    if not query:
        return None
    key = _norm(query)
    cached = await _from_cache(key)
    if cached:
        return cached
    result = await _mapbox(query, country)
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
