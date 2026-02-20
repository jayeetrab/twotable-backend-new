from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple
import hashlib

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.models.travel_time import TravelTimeCache


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_origin_hash(lat: float, lng: float) -> str:
    """Round to ~500m grid and hash — avoids re-fetching nearly identical origins."""
    rounded = f"{round(lat, 3)}:{round(lng, 3)}"
    return hashlib.sha256(rounded.encode()).hexdigest()[:16]


def get_time_bucket() -> str:
    now = datetime.now()
    hour = now.hour
    is_weekend = now.weekday() >= 5
    if is_weekend:
        if hour < 12:
            return "weekend_morning"
        elif hour < 18:
            return "weekend_afternoon"
        else:
            return "weekend_evening"
    else:
        return "weekday_evening" if hour >= 17 else "weekday_daytime"


# ── Provider implementations ─────────────────────────────────────────────────

async def _fetch_tomtom(
    origin: Tuple[float, float],
    destination: Tuple[float, float],
    mode: str,
) -> Optional[float]:
    """
    TomTom Routing API.
    Returns travel minutes or None.
    Supports drive / walk. Transit maps to drive for now.
    """
    travel_mode_map = {"drive": "car", "walk": "pedestrian", "transit": "car"}
    travel_mode = travel_mode_map.get(mode, "car")

    origin_str = f"{origin[0]},{origin[1]}"
    dest_str = f"{destination[0]},{destination[1]}"

    url = f"https://api.tomtom.com/routing/1/calculateRoute/{origin_str}:{dest_str}/json"

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, params={
            "key": settings.ROUTING_API_KEY,
            "travelMode": travel_mode,
            "traffic": "true",          # live traffic by default
            "routeType": "fastest",
        })

    if resp.status_code != 200:
        return None

    data = resp.json()
    try:
        seconds = data["routes"][0]["summary"]["travelTimeInSeconds"]
        return round(seconds / 60, 1)
    except (KeyError, IndexError):
        return None


async def _fetch_ors(
    origin: Tuple[float, float],
    destination: Tuple[float, float],
    mode: str,
) -> Optional[float]:
    profile_map = {"drive": "driving-car", "walk": "foot-walking", "transit": "driving-car"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"https://api.openrouteservice.org/v2/directions/{profile_map.get(mode, 'driving-car')}",
            json={"coordinates": [[origin[1], origin[0]], [destination[1], destination[0]]]},
            headers={"Authorization": settings.ROUTING_API_KEY},
        )
    if resp.status_code != 200:
        return None
    try:
        return round(resp.json()["routes"][0]["summary"]["duration"] / 60, 1)
    except (KeyError, IndexError):
        return None


async def _fetch_mapbox(
    origin: Tuple[float, float],
    destination: Tuple[float, float],
    mode: str,
) -> Optional[float]:
    profile_map = {"drive": "driving", "walk": "walking", "transit": "driving"}
    coords = f"{origin[1]},{origin[0]};{destination[1]},{destination[0]}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"https://api.mapbox.com/directions/v5/mapbox/{profile_map.get(mode, 'driving')}/{coords}",
            params={"access_token": settings.ROUTING_API_KEY, "overview": "false"},
        )
    if resp.status_code != 200:
        return None
    try:
        return round(resp.json()["routes"][0]["duration"] / 60, 1)
    except (KeyError, IndexError):
        return None


# ── Public interface ──────────────────────────────────────────────────────────

async def get_travel_time(
    origin: Tuple[float, float],
    destination: Tuple[float, float],
    venue_id: int,
    db: AsyncSession,
    mode: str = "drive",
) -> Optional[float]:
    """
    Returns travel time in minutes, origin → destination.
    Cache-first. Only calls the routing API on a miss or expired cache entry.
    """
    ttl = timedelta(hours=settings.TRAVEL_TIME_CACHE_TTL_HOURS)
    origin_hash = make_origin_hash(*origin)
    time_bucket = get_time_bucket()

    # Cache lookup
    result = await db.execute(
        select(TravelTimeCache).where(
            TravelTimeCache.origin_hash == origin_hash,
            TravelTimeCache.venue_id == venue_id,
            TravelTimeCache.mode == mode,
            TravelTimeCache.time_bucket == time_bucket,
        )
    )
    cached = result.scalar_one_or_none()

    if cached:
        age = datetime.now(timezone.utc) - cached.last_checked_at
        if age < ttl:
            return cached.travel_minutes
        await db.delete(cached)
        await db.commit()

    # API call
    provider = settings.ROUTING_PROVIDER
    if provider == "tomtom":
        minutes = await _fetch_tomtom(origin, destination, mode)
    elif provider == "openrouteservice":
        minutes = await _fetch_ors(origin, destination, mode)
    elif provider == "mapbox":
        minutes = await _fetch_mapbox(origin, destination, mode)
    else:
        raise ValueError(f"Unknown routing provider: {provider}")

    if minutes is None:
        return None

    # Write to cache
    db.add(TravelTimeCache(
        origin_hash=origin_hash,
        venue_id=venue_id,
        mode=mode,
        time_bucket=time_bucket,
        travel_minutes=minutes,
        last_checked_at=datetime.now(timezone.utc),
    ))
    await db.commit()

    return minutes
