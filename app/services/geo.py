"""Lightweight geo helpers — haversine distance + travel-time estimation.

The original SQL backend called TomTom for travel times and cached them in
Postgres. The MongoDB core build estimates travel time from straight-line
(haversine) distance and per-mode speeds, so it has zero external dependencies
and boots offline. Swap ``estimate_travel_minutes`` for a real routing call
later without touching callers.
"""
from __future__ import annotations

from math import asin, cos, radians, sin, sqrt
from typing import Optional

# Rough door-to-door speeds (km per minute), incl. typical urban overhead.
_SPEED_KM_PER_MIN = {
    "walk": 0.083,    # ~5 km/h
    "drive": 0.5,     # ~30 km/h urban
    "transit": 0.4,   # ~24 km/h incl. waiting
}
# Pre-filter radius inflation: straight-line under-estimates real travel.
_SAFETY_FACTOR = 1.8


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return R * 2 * asin(sqrt(a))


def max_radius_km(mode: str, max_minutes: int) -> float:
    return _SPEED_KM_PER_MIN.get(mode, 0.5) * max_minutes * _SAFETY_FACTOR


def estimate_travel_minutes(
    origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float, mode: str,
) -> float:
    dist = haversine_km(origin_lat, origin_lng, dest_lat, dest_lng)
    speed = _SPEED_KM_PER_MIN.get(mode, 0.5)
    # *1.3 corrects straight-line distance toward real road/route distance.
    return round((dist / speed) * 1.3, 1)


def within_radius(
    origin_lat: float, origin_lng: float,
    dest_lat: Optional[float], dest_lng: Optional[float],
    mode: str, max_travel_min: int,
) -> bool:
    if dest_lat is None or dest_lng is None:
        return False
    return haversine_km(origin_lat, origin_lng, dest_lat, dest_lng) <= max_radius_km(mode, max_travel_min)
