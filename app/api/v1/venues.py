from __future__ import annotations

import logging
from datetime import datetime, timezone
from datetime import time as dt_time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pymongo.errors import DuplicateKeyError

from app.db import mongo
from app.models.venue_lead import VenueLeadStatus
from app.schemas.venue_lead import VenueLeadCreate, VenueLeadRead
from app.services.cache import available_venues_cache
from app.services.geo import estimate_travel_minutes, within_radius
from app.services.matcher import _is_blacked_out, _matching_slot, is_date_appropriate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/venues", tags=["venues"])


def _venue_dict(v: dict, travel_minutes: Optional[float]) -> dict:
    photos = [mongo.photo_url(p) for p in (v.get("photos") or [])]
    return {
        "id": v["_id"],
        "name": v.get("name"),
        "address": v.get("address"),
        "lat": v.get("lat"),
        "lng": v.get("lng"),
        "city": v.get("city"),
        "cuisine": v.get("cuisine"),
        "price_band": v.get("price_band"),
        "noise_level": v.get("noise_level"),
        "vibe_tags": v.get("vibe_tags"),
        "description": v.get("description"),
        "photo_url": photos[0] if photos else None,
        "photos": photos,
        "travel_minutes": travel_minutes,
    }


# ── Apply as a venue ──────────────────────────────────────────────────────────

@router.post("/apply", response_model=VenueLeadRead, status_code=status.HTTP_201_CREATED)
async def apply_as_venue(payload: VenueLeadCreate):
    db = mongo.get_db()
    now = datetime.now(timezone.utc)
    doc = {
        "_id": await mongo.next_id("venue_leads"),
        **payload.model_dump(mode="json"),
        "status": VenueLeadStatus.new.value,
        "created_at": now,
        "updated_at": now,
    }
    try:
        await db[mongo.VENUE_LEADS].insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An application from this email already exists.",
        )
    return VenueLeadRead.model_validate({**doc, "id": doc["_id"]})


# ── Available venues ──────────────────────────────────────────────────────────

@router.get("/available")
async def get_available_venues(
    date: datetime = Query(..., description="ISO date/datetime; weekday is derived"),
    time: dt_time = Query(..., description="HH:MM:SS"),
    city: str = Query("Bristol"),
    origin_lat: Optional[float] = Query(None),
    origin_lng: Optional[float] = Query(None),
    mode: str = Query("drive"),
    max_travel_min: int = Query(45),
):
    db = mongo.get_db()
    weekday = date.weekday()
    target_time = time.isoformat()
    date_str = date.date().isoformat()

    cursor = db[mongo.VENUES].find({
        "city": {"$regex": city, "$options": "i"},
        "is_active": True,
    })
    venues = await cursor.to_list(length=None)

    output = []
    for v in venues:
        if not _matching_slot(v, weekday, target_time):
            continue
        if _is_blacked_out(v, date_str):
            continue
        if not is_date_appropriate(v):
            continue

        travel_minutes: Optional[float] = None
        if origin_lat is not None and origin_lng is not None:
            if v.get("lat") is None or v.get("lng") is None:
                continue
            if not within_radius(origin_lat, origin_lng, v["lat"], v["lng"], mode, max_travel_min):
                continue
            travel_minutes = estimate_travel_minutes(
                origin_lat, origin_lng, v["lat"], v["lng"], mode
            )
            if travel_minutes > max_travel_min:
                continue

        output.append(_venue_dict(v, travel_minutes))

    return {"count": len(output), "venues": output}


# ── List venues (for the app's restaurant browser) ────────────────────────────

@router.get("")
async def list_venues(
    city: str = Query("Bristol"),
    limit: int = Query(30, ge=1, le=100),
):
    """Real, date-appropriate venues with coordinates — for the restaurant list + maps."""
    cache_key = f"list:{city.lower()}:{limit}"
    cached = await available_venues_cache.get(cache_key)
    if cached is not None:
        return cached

    db = mongo.get_db()
    cursor = db[mongo.VENUES].find({
        "city": {"$regex": city, "$options": "i"},
        "is_active": True,
        "lat": {"$ne": None},
        "lng": {"$ne": None},
    })
    docs = await cursor.to_list(length=500)
    venues = [_venue_dict(v, None) for v in docs if is_date_appropriate(v)][:limit]
    result = {"count": len(venues), "venues": venues}
    await available_venues_cache.set(cache_key, result)   # 5-min TTL; no-op if Redis is down
    return result


# ── Get a single venue ────────────────────────────────────────────────────────

@router.get("/{venue_id}")
async def get_venue(venue_id: int):
    db = mongo.get_db()
    v = await db[mongo.VENUES].find_one({"_id": venue_id})
    if not v:
        raise HTTPException(status_code=404, detail="Venue not found")
    return {
        **_venue_dict(v, None),
        "slots": v.get("slots", []),
    }
