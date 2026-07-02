"""
Geo + routing APIs.

Covers every scenario the app needs around place + travel:
- geocode / reverse            address ↔ coordinates
- travel-time / matrix         time-aware, multi-modal ETAs (one or many destinations)
- isochrone                    reachable-area polygon
- fair-venues                  the headline: venues that are fair + convenient for BOTH
                               daters, and the match-aware variant that pulls both
                               people's home coordinates automatically.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.deps import get_current_user
from app.db import mongo
from app.services import geocoding, meeting, routing
from app.services.geo import haversine_km

router = APIRouter(prefix="/geo", tags=["geo"])


class Point(BaseModel):
    lat: float
    lng: float


# ── Geocoding ─────────────────────────────────────────────────────────────────

class GeocodeRequest(BaseModel):
    query: str
    country: Optional[str] = "gb"


@router.post("/geocode")
async def geocode(req: GeocodeRequest, _: dict = Depends(get_current_user)):
    res = await geocoding.geocode(req.query, req.country)
    if not res:
        raise HTTPException(404, "Could not geocode that location")
    lat, lng, name = res
    return {"lat": lat, "lng": lng, "name": name}


@router.post("/reverse")
async def reverse(p: Point, _: dict = Depends(get_current_user)):
    return {"name": await geocoding.reverse(p.lat, p.lng)}


# ── Travel times ──────────────────────────────────────────────────────────────

class TravelRequest(BaseModel):
    origin: Point
    dest: Point
    mode: str = "drive"
    depart_at: Optional[datetime] = None


@router.post("/travel-time")
async def travel_time(req: TravelRequest, _: dict = Depends(get_current_user)):
    minutes = await routing.travel_minutes(
        (req.origin.lat, req.origin.lng), (req.dest.lat, req.dest.lng),
        req.mode, req.depart_at)
    return {"minutes": minutes, "mode": req.mode}


class MatrixRequest(BaseModel):
    origin: Point
    destinations: list[Point]
    mode: str = "drive"
    depart_at: Optional[datetime] = None


@router.post("/matrix")
async def matrix(req: MatrixRequest, _: dict = Depends(get_current_user)):
    mins = await routing.travel_matrix(
        (req.origin.lat, req.origin.lng),
        [(d.lat, d.lng) for d in req.destinations], req.mode, req.depart_at)
    return {"minutes": mins, "mode": req.mode}


class IsochroneRequest(BaseModel):
    origin: Point
    minutes: int = 20
    mode: str = "drive"


@router.post("/isochrone")
async def isochrone(req: IsochroneRequest, _: dict = Depends(get_current_user)):
    geo = await routing.isochrone((req.origin.lat, req.origin.lng), req.minutes, req.mode)
    if geo is None:
        raise HTTPException(503, "Isochrone needs a Mapbox token")
    return geo


# ── Fair meeting venues (the differentiator) ──────────────────────────────────

async def _nearby_city_venues(city: str, mid: tuple[float, float], k: int = 24) -> list[dict]:
    """Active venues with coordinates in the city, the k nearest to the pair's midpoint."""
    docs = await mongo.get_db()[mongo.VENUES].find(
        {"city": {"$regex": city, "$options": "i"}, "is_active": True,
         "lat": {"$ne": None}, "lng": {"$ne": None}},
        {"name": 1, "cuisine": 1, "price_band": 1, "lat": 1, "lng": 1},
    ).to_list(length=500)
    docs.sort(key=lambda v: haversine_km(mid[0], mid[1], v["lat"], v["lng"]))
    return docs[:k]


class FairVenuesRequest(BaseModel):
    origin_a: Point
    origin_b: Point
    mode_a: str = "drive"
    mode_b: str = "drive"
    city: str = "Bristol"
    depart_at: Optional[datetime] = None
    max_minutes: int = 45
    limit: int = 10


@router.post("/fair-venues")
async def fair_venues(req: FairVenuesRequest, _: dict = Depends(get_current_user)):
    """Rank venues that are fair + convenient for two people travelling separately."""
    mid = ((req.origin_a.lat + req.origin_b.lat) / 2, (req.origin_a.lng + req.origin_b.lng) / 2)
    venues = await _nearby_city_venues(req.city, mid)
    ranked = await meeting.fair_meeting_venues(
        (req.origin_a.lat, req.origin_a.lng), req.mode_a,
        (req.origin_b.lat, req.origin_b.lng), req.mode_b,
        venues, req.depart_at, req.max_minutes, req.limit)
    return {"count": len(ranked), "venues": ranked}


@router.get("/travel-options/{venue_id}")
async def travel_options(
    venue_id: int,
    depart_at: Optional[datetime] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """How long it takes ME to reach this venue, per way of getting there.

    Returns walk / cycle / drive minutes from the signed-in user's saved location
    (traffic-aware when a Mapbox token is set; calibrated estimate otherwise).
    """
    db = mongo.get_db()
    venue = await db[mongo.VENUES].find_one({"_id": venue_id})
    if not venue or venue.get("lat") is None or venue.get("lng") is None:
        raise HTTPException(404, "Venue not found or has no coordinates")

    prof = await db[mongo.PROFILES].find_one({"user_id": current_user["_id"]}) or {}
    if prof.get("lat") is None or prof.get("lng") is None:
        raise HTTPException(422, "Set your location in your profile to see travel times.")

    origin = (prof["lat"], prof["lng"])
    dest = (venue["lat"], venue["lng"])
    modes = []
    for mode in ["walk", "cycle", "drive"]:
        minutes = await routing.travel_minutes(origin, dest, mode, depart_at)
        modes.append({"mode": mode, "minutes": round(minutes, 0)})
    from app.core.config import settings as _s
    return {"venue_id": venue_id, "venue_name": venue.get("name"),
            "modes": modes, "source": "mapbox" if _s.MAPBOX_TOKEN else "estimate"}


@router.get("/fair-venues/match/{user_id}")
async def fair_venues_for_match(
    user_id: int,
    mode: str = Query("drive"),
    depart_at: Optional[datetime] = Query(None),
    max_minutes: int = Query(45),
    current_user: dict = Depends(get_current_user),
):
    """Fair venues for the current user and a matched user — pulls both home coords."""
    db = mongo.get_db()
    me = await db[mongo.PROFILES].find_one({"user_id": current_user["_id"]}) or {}
    them = await db[mongo.PROFILES].find_one({"user_id": user_id}) or {}

    def coord(p):
        return (p.get("lat"), p.get("lng")) if p.get("lat") is not None and p.get("lng") is not None else None

    a, b = coord(me), coord(them)
    if not a or not b:
        raise HTTPException(422, "Both people need a saved location (set during onboarding).")

    city = me.get("city") or them.get("city") or "Bristol"
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    venues = await _nearby_city_venues(city, mid)
    ranked = await meeting.fair_meeting_venues(a, mode, b, mode, venues, depart_at, max_minutes)
    return {"count": len(ranked), "venues": ranked}
