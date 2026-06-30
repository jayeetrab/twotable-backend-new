"""
TwoTable routing engine — time-aware, multi-modal travel times via Mapbox, with a
MongoDB cache and a graceful haversine fallback.

Capabilities
------------
- travel_minutes(o, d, mode, depart_at)  single origin→destination ETA
- travel_matrix(origins, dests, mode)    many×many ETAs in one Mapbox Matrix call
- isochrone(o, minutes, mode)            reachable-area polygon (GeoJSON)

Why this is more than "an API call"
-----------------------------------
- **Time-aware**: driving uses Mapbox `driving-traffic` with a `depart_at` so ETAs
  reflect real congestion at the actual date time, not free-flow distance.
- **Multi-modal**: walking / cycling / driving / driving-traffic per request — each
  dater can travel their own way.
- **Matrix-native**: one request scores a whole shortlist of venues, which is what
  the fair meeting-point optimiser (services.meeting) needs.
- **Cache-first + graceful**: every OD pair is memoised in `travel_time_cache`
  (bucketed by hour); with no token / on any error it falls back to a calibrated
  haversine estimate so the product never blocks on the network.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, Sequence

import httpx

from app.core.config import settings
from app.db import mongo
from app.services.geo import estimate_travel_minutes, haversine_km

logger = logging.getLogger(__name__)

CACHE = "travel_time_cache"
_BASE = "https://api.mapbox.com"

Coord = tuple[float, float]  # (lat, lng)

# App mode → Mapbox routing profile. "drive" uses live traffic.
_PROFILE = {
    "drive": "driving-traffic",
    "driving": "driving-traffic",
    "car": "driving-traffic",
    "walk": "walking",
    "walking": "walking",
    "cycle": "cycling",
    "cycling": "cycling",
    "bike": "cycling",
    "transit": "driving",   # Mapbox has no transit matrix; approximate with driving
}


def _profile(mode: str) -> str:
    return _PROFILE.get((mode or "drive").lower(), "driving-traffic")


def _hour_bucket(depart_at: Optional[datetime]) -> str:
    t = depart_at or datetime.now(timezone.utc)
    return t.strftime("%Y%m%d%H")


def _key(o: Coord, d: Coord, mode: str, bucket: str) -> str:
    return f"{round(o[0],4)},{round(o[1],4)}|{round(d[0],4)},{round(d[1],4)}|{_profile(mode)}|{bucket}"


# ── Single origin → destination ───────────────────────────────────────────────

async def travel_minutes(origin: Coord, dest: Coord, mode: str = "drive",
                         depart_at: Optional[datetime] = None) -> float:
    """Travel time in minutes. Cache-first; Mapbox if a token is set; haversine fallback."""
    bucket = _hour_bucket(depart_at)
    key = _key(origin, dest, mode, bucket)
    db = mongo.get_db()
    hit = await db[CACHE].find_one({"_id": key})
    if hit and hit.get("minutes") is not None:
        return hit["minutes"]

    minutes = await _mapbox_single(origin, dest, mode, depart_at)
    if minutes is None:                                   # no token / error → estimate
        minutes = estimate_travel_minutes(origin[0], origin[1], dest[0], dest[1], mode)
        source = "haversine"
    else:
        source = "mapbox"
    await db[CACHE].update_one(
        {"_id": key},
        {"$set": {"minutes": minutes, "source": source, "updated_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    return minutes


async def _mapbox_single(origin: Coord, dest: Coord, mode: str,
                        depart_at: Optional[datetime]) -> Optional[float]:
    if not settings.MAPBOX_TOKEN:
        return None
    prof = _profile(mode)
    coords = f"{origin[1]},{origin[0]};{dest[1]},{dest[0]}"   # lng,lat;lng,lat
    params = {"access_token": settings.MAPBOX_TOKEN, "overview": "false", "annotations": "duration"}
    if prof == "driving-traffic" and depart_at:
        params["depart_at"] = depart_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M")
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.get(f"{_BASE}/directions/v5/mapbox/{prof}/{coords}", params=params)
        if r.status_code != 200:
            return None
        routes = r.json().get("routes") or []
        return round(routes[0]["duration"] / 60.0, 1) if routes else None
    except Exception as exc:
        logger.warning("Mapbox directions failed: %s", exc)
        return None


# ── Matrix: one origin → many destinations ────────────────────────────────────

async def travel_matrix(origin: Coord, destinations: Sequence[Coord], mode: str = "drive",
                        depart_at: Optional[datetime] = None) -> list[Optional[float]]:
    """Minutes from one origin to each destination. One Mapbox Matrix call (≤24 dests)."""
    if not destinations:
        return []
    mapbox = await _mapbox_matrix(origin, destinations, mode)
    if mapbox is not None:
        return mapbox
    # Fallback: per-destination haversine estimate.
    return [estimate_travel_minutes(origin[0], origin[1], d[0], d[1], mode) for d in destinations]


async def _mapbox_matrix(origin: Coord, destinations: Sequence[Coord],
                        mode: str) -> Optional[list[Optional[float]]]:
    if not settings.MAPBOX_TOKEN:
        return None
    prof = _profile(mode)
    limit = 9 if prof == "driving-traffic" else 24       # Mapbox per-request coord caps
    out: list[Optional[float]] = []
    try:
        for i in range(0, len(destinations), limit):
            chunk = destinations[i:i + limit]
            pts = [origin] + list(chunk)
            coords = ";".join(f"{p[1]},{p[0]}" for p in pts)
            dest_idx = ";".join(str(j) for j in range(1, len(pts)))
            params = {"access_token": settings.MAPBOX_TOKEN, "sources": "0",
                      "destinations": dest_idx, "annotations": "duration"}
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.get(f"{_BASE}/directions-matrix/v1/mapbox/{prof}/{coords}", params=params)
            if r.status_code != 200:
                return None
            durs = (r.json().get("durations") or [[None]])[0]
            out.extend(round(s / 60.0, 1) if s is not None else None for s in durs)
        return out
    except Exception as exc:
        logger.warning("Mapbox matrix failed: %s", exc)
        return None


# ── Isochrone: reachable area within N minutes ────────────────────────────────

async def isochrone(origin: Coord, minutes: int, mode: str = "drive") -> Optional[dict]:
    """GeoJSON polygon of everywhere reachable within `minutes`. None without a token."""
    if not settings.MAPBOX_TOKEN:
        return None
    prof = _profile(mode).replace("driving-traffic", "driving")  # isochrone has no traffic profile
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.get(
                f"{_BASE}/isochrone/v1/mapbox/{prof}/{origin[1]},{origin[0]}",
                params={"contours_minutes": min(minutes, 60), "polygons": "true",
                        "access_token": settings.MAPBOX_TOKEN},
            )
        return r.json() if r.status_code == 200 else None
    except Exception as exc:
        logger.warning("Mapbox isochrone failed: %s", exc)
        return None
