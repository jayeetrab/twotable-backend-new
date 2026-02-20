from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.models.geocoding_cache import GeocodingCache


# ── Provider implementations ─────────────────────────────────────────────────

async def _geocode_tomtom(query: str) -> Optional[Tuple[float, float, str]]:
    """TomTom Search API — Fuzzy Search endpoint."""
    url = f"https://api.tomtom.com/search/2/geocode/{httpx.URL(query)}.json"
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.tomtom.com/search/2/search/{query}.json",
            params={
                "key": settings.GEOCODING_API_KEY,
                "limit": 1,
                "typeahead": "false",
            },
        )
    if resp.status_code != 200:
        return None
    data = resp.json()
    results = data.get("results", [])
    if not results:
        return None
    top = results[0]
    pos = top["position"]
    address = top.get("address", {}).get("freeformAddress", query)
    return pos["lat"], pos["lon"], address


async def _geocode_opencage(query: str) -> Optional[Tuple[float, float, str]]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.opencagedata.com/geocode/v1/json",
            params={"q": query, "key": settings.GEOCODING_API_KEY, "limit": 1, "no_annotations": 1},
        )
    if resp.status_code != 200:
        return None
    data = resp.json()
    if not data["results"]:
        return None
    r = data["results"][0]
    return r["geometry"]["lat"], r["geometry"]["lng"], r["formatted"]


async def _geocode_mapbox(query: str) -> Optional[Tuple[float, float, str]]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.mapbox.com/geocoding/v5/mapbox.places/{query}.json",
            params={"access_token": settings.GEOCODING_API_KEY, "limit": 1},
        )
    if resp.status_code != 200:
        return None
    data = resp.json()
    if not data["features"]:
        return None
    f = data["features"][0]
    lng, lat = f["geometry"]["coordinates"]
    return lat, lng, f["place_name"]


# ── Public interface ──────────────────────────────────────────────────────────

async def geocode(
    query: str,
    db: AsyncSession,
) -> Optional[Tuple[float, float, str]]:
    """
    Geocode a query string → (lat, lng, formatted_address).
    Cache-first: only calls the API on a miss or expired entry.
    """
    provider = settings.GEOCODING_PROVIDER
    ttl = timedelta(days=settings.GEOCODING_CACHE_TTL_DAYS)

    # Cache lookup
    result = await db.execute(
        select(GeocodingCache).where(
            GeocodingCache.raw_query == query,
            GeocodingCache.provider == provider,
        )
    )
    cached = result.scalar_one_or_none()

    if cached:
        age = datetime.now(timezone.utc) - cached.created_at
        if age < ttl:
            return cached.lat, cached.lng, cached.formatted_address or ""
        await db.delete(cached)
        await db.commit()

    # API call
    coords: Optional[Tuple[float, float, str]] = None
    if provider == "tomtom":
        coords = await _geocode_tomtom(query)
    elif provider == "opencage":
        coords = await _geocode_opencage(query)
    elif provider == "mapbox":
        coords = await _geocode_mapbox(query)
    else:
        raise ValueError(f"Unknown geocoding provider: {provider}")

    if not coords:
        return None

    lat, lng, formatted = coords

    # Write to cache
    db.add(GeocodingCache(
        raw_query=query,
        provider=provider,
        lat=lat,
        lng=lng,
        formatted_address=formatted,
    ))
    await db.commit()

    return lat, lng, formatted
