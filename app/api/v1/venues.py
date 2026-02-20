from datetime import datetime
from datetime import time as dt_time
from math import asin, cos, radians, sin, sqrt
from typing import List, Optional
import hashlib
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.venue import Venue
from app.models.venue_blackout import VenueBlackout
from app.models.venue_lead import VenueLead
from app.models.venue_slot import VenueSlot
from app.schemas.venue_lead import VenueLeadCreate, VenueLeadRead
from app.services.geocoding import geocode
from app.services.routing import get_time_bucket, get_travel_time
from app.services.cache import available_venues_cache, haversine_cache

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/venues", tags=["venues"])


# ── Date-appropriateness filter ───────────────────────────────────────────────

_NON_DATE_CUISINES = {
    "supermarket", "grocery", "convenience store", "petrol station",
    "fast food", "takeaway", "off licence", "newsagent", "pharmacy",
    "bakery", "butcher", "fishmonger", "food court",
    "bagel shop", "sandwich shop", "juice bar", "chicken restaurant",
    "sports bar",
}

_NON_DATE_VIBES = {
    "family friendly", "kids", "canteen", "buffet", "cafeteria",
}

_NON_DATE_VENUE_TYPES = {
    "event venue", "coffee shop", "newsagent",
}


def _is_date_appropriate(venue: Venue) -> bool:
    if venue.cuisine:
        cuisine_lower = venue.cuisine.lower().strip()
        if any(bad in cuisine_lower for bad in _NON_DATE_CUISINES):
            return False
        if cuisine_lower in _NON_DATE_VENUE_TYPES:
            return False
    if venue.vibe_tags:
        tags = [t.strip().lower() for t in venue.vibe_tags.split(",")]
        if any(tag in _NON_DATE_VIBES for tag in tags):
            return False
    return True


# ── Haversine pre-filter ──────────────────────────────────────────────────────

def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return R * 2 * asin(sqrt(a))


_SPEED_KM_PER_MIN = {
    "walk":    0.083,
    "drive":   0.5,
    "transit": 0.4,
}
_SAFETY_FACTOR = 1.8


def _max_radius_km(mode: str, max_minutes: int) -> float:
    return _SPEED_KM_PER_MIN.get(mode, 0.5) * max_minutes * _SAFETY_FACTOR


def prefilter_by_distance(
    venues: List[Venue],
    origin_lat: float,
    origin_lng: float,
    mode: str,
    max_travel_min: int,
) -> List[Venue]:
    radius_km = _max_radius_km(mode, max_travel_min)
    return [
        v for v in venues
        if v.lat is not None
        and v.lng is not None
        and _haversine_km(origin_lat, origin_lng, v.lat, v.lng) <= radius_km
    ]


# ── Cache key helpers ─────────────────────────────────────────────────────────

def _origin_hash(lat: float, lng: float) -> str:
    """Round to 3dp (~111m grid) so nearby origins share cache entries."""
    return f"{round(lat, 3)},{round(lng, 3)}"


def _available_cache_key(
    city: str,
    weekday: int,
    time_str: str,
    origin_hash: str,
    mode: str,
    max_travel_min: int,
) -> str:
    raw = f"{city}|{weekday}|{time_str}|{origin_hash}|{mode}|{max_travel_min}"
    return hashlib.md5(raw.encode()).hexdigest()


# ── Venue dict helper ─────────────────────────────────────────────────────────

def _venue_dict(v: Venue, travel_minutes: Optional[float]) -> dict:
    return {
        "id":           v.id,
        "name":         v.name,
        "address":      v.address,
        "lat":          v.lat,
        "lng":          v.lng,
        "city":         v.city,
        "cuisine":      v.cuisine,
        "price_band":   v.price_band.value if v.price_band else None,
        "noise_level":  v.noise_level.value if v.noise_level else None,
        "vibe_tags":    v.vibe_tags,
        "description":  v.description,
        "travel_minutes": travel_minutes,
    }


# ── Apply as venue ────────────────────────────────────────────────────────────

@router.post("/apply", response_model=VenueLeadRead, status_code=status.HTTP_201_CREATED)
async def apply_as_venue(
    payload: VenueLeadCreate,
    db: AsyncSession = Depends(get_db),
):
    lead = VenueLead(**payload.model_dump())
    db.add(lead)
    try:
        await db.commit()
        await db.refresh(lead)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An application from this email already exists.",
        )
    return lead


# ── Geocode test ──────────────────────────────────────────────────────────────

@router.get("/geocode-test")
async def geocode_test(q: str, db: AsyncSession = Depends(get_db)):
    result = await geocode(q, db)
    if not result:
        raise HTTPException(status_code=404, detail="Could not geocode address")
    lat, lng, formatted = result
    return {"lat": lat, "lng": lng, "formatted": formatted}


# ── Scenario test ─────────────────────────────────────────────────────────────

class TwoTableScenarioRequest(BaseModel):
    person_a_address: str
    person_b_address: str
    venue_address: str
    mode: Optional[str] = "drive"


class PersonRoute(BaseModel):
    address: str
    lat: float
    lng: float
    travel_minutes: float
    within_45_min: bool
    verdict: str


class TwoTableScenarioResponse(BaseModel):
    venue_address: str
    venue_lat: float
    venue_lng: float
    person_a: PersonRoute
    person_b: PersonRoute
    both_within_45_min: bool
    recommendation: str
    time_bucket: str
    mode: str


@router.post("/scenario-test", response_model=TwoTableScenarioResponse)
async def twotable_scenario_test(
    payload: TwoTableScenarioRequest,
    db: AsyncSession = Depends(get_db),
):
    venue_coords = await geocode(payload.venue_address, db)
    if not venue_coords:
        raise HTTPException(
            status_code=404,
            detail=f"Could not geocode venue: {payload.venue_address}",
        )
    person_a_coords = await geocode(payload.person_a_address, db)
    if not person_a_coords:
        raise HTTPException(
            status_code=404,
            detail=f"Could not geocode person A: {payload.person_a_address}",
        )
    person_b_coords = await geocode(payload.person_b_address, db)
    if not person_b_coords:
        raise HTTPException(
            status_code=404,
            detail=f"Could not geocode person B: {payload.person_b_address}",
        )

    venue_lat, venue_lng, venue_formatted = venue_coords
    a_lat, a_lng, a_formatted = person_a_coords
    b_lat, b_lng, b_formatted = person_b_coords

    a_minutes = await _get_test_travel_time(
        origin=(a_lat, a_lng),
        destination=(venue_lat, venue_lng),
        mode=payload.mode,
    )
    b_minutes = await _get_test_travel_time(
        origin=(b_lat, b_lng),
        destination=(venue_lat, venue_lng),
        mode=payload.mode,
    )

    if a_minutes is None or b_minutes is None:
        raise HTTPException(status_code=502, detail="Could not calculate travel time.")

    a_ok   = a_minutes <= 45
    b_ok   = b_minutes <= 45
    both_ok = a_ok and b_ok

    if both_ok:
        recommendation = f"✅ Great venue! Both can reach {venue_formatted} within 45 minutes."
    elif a_ok and not b_ok:
        recommendation = f"⚠️ Too far for Person B ({b_minutes} min)."
    elif b_ok and not a_ok:
        recommendation = f"⚠️ Too far for Person A ({a_minutes} min)."
    else:
        recommendation = "❌ Too far for both. Find a more central venue."

    return TwoTableScenarioResponse(
        venue_address=venue_formatted,
        venue_lat=venue_lat,
        venue_lng=venue_lng,
        person_a=PersonRoute(
            address=a_formatted, lat=a_lat, lng=a_lng,
            travel_minutes=a_minutes, within_45_min=a_ok,
            verdict="✅ Within range" if a_ok else f"❌ {a_minutes} min — too far",
        ),
        person_b=PersonRoute(
            address=b_formatted, lat=b_lat, lng=b_lng,
            travel_minutes=b_minutes, within_45_min=b_ok,
            verdict="✅ Within range" if b_ok else f"❌ {b_minutes} min — too far",
        ),
        both_within_45_min=both_ok,
        recommendation=recommendation,
        time_bucket=get_time_bucket(),
        mode=payload.mode,
    )


async def _get_test_travel_time(
    origin: tuple, destination: tuple, mode: str
) -> Optional[float]:
    import httpx
    from app.core.config import settings

    travel_mode_map = {"drive": "car", "walk": "pedestrian", "transit": "car"}
    origin_str = f"{origin[0]},{origin[1]}"
    dest_str   = f"{destination[0]},{destination[1]}"

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"https://api.tomtom.com/routing/1/calculateRoute/{origin_str}:{dest_str}/json",
            params={
                "key":        settings.ROUTING_API_KEY,
                "travelMode": travel_mode_map.get(mode, "car"),
                "traffic":    "true",
                "routeType":  "fastest",
            },
        )
    if resp.status_code != 200:
        return None
    try:
        seconds = resp.json()["routes"][0]["summary"]["travelTimeInSeconds"]
        return round(seconds / 60, 1)
    except (KeyError, IndexError):
        return None


# ── Available venues ──────────────────────────────────────────────────────────

@router.get("/available")
async def get_available_venues(
    date: datetime = Query(...),
    time: dt_time = Query(...),
    city: str = Query("Bristol"),
    origin_lat: Optional[float] = Query(None),
    origin_lng: Optional[float] = Query(None),
    mode: str = Query("drive"),
    max_travel_min: int = Query(45),
    db: AsyncSession = Depends(get_db),
):
    weekday   = date.weekday()
    date_only = date.date()

    # ── Redis cache check ─────────────────────────────────────────────────────
    origin_hash = _origin_hash(origin_lat, origin_lng) if origin_lat and origin_lng else "none"
    cache_key   = _available_cache_key(city, weekday, str(time), origin_hash, mode, max_travel_min)
    cached      = await available_venues_cache.get(cache_key)
    if cached is not None:
        logger.info("available_venues Redis HIT key=%s", cache_key[:12])
        return cached

    # ── Layer 1: SQL ──────────────────────────────────────────────────────────
    stmt = (
        select(Venue)
        .join(VenueSlot, VenueSlot.venue_id == Venue.id)
        .where(
            Venue.city.ilike(f"%{city}%"),
            Venue.is_active == True,       # noqa: E712
            VenueSlot.is_active == True,   # noqa: E712
            VenueSlot.weekday == weekday,
            VenueSlot.start_time <= time,
            VenueSlot.end_time > time,
        )
        .distinct()
    )
    result = await db.execute(stmt)
    venues: List[Venue] = result.scalars().all()
    logger.info("SQL layer: %d venues", len(venues))

    # ── Layer 2: Blackout filter ──────────────────────────────────────────────
    blackout_stmt = select(VenueBlackout.venue_id).where(
        VenueBlackout.start_date <= date_only,
        VenueBlackout.end_date >= date_only,
    )
    blackout_result = await db.execute(blackout_stmt)
    blacked_out_ids = {row for row in blackout_result.scalars().all()}
    venues = [v for v in venues if v.id not in blacked_out_ids]

    # ── Layer 3: Date-appropriateness ─────────────────────────────────────────
    venues = [v for v in venues if _is_date_appropriate(v)]
    logger.info("After date filter: %d venues", len(venues))

    # ── Layer 4 + 5: Haversine + TomTom ──────────────────────────────────────
    output = []

    if origin_lat is None or origin_lng is None:
        for v in venues:
            output.append(_venue_dict(v, travel_minutes=None))
    else:
        # Haversine — check Redis first
        haversine_key = f"{origin_hash}|{mode}|{max_travel_min}"
        cached_ids    = await haversine_cache.get(haversine_key)

        if cached_ids is not None:
            logger.info("haversine Redis HIT — %d ids", len(cached_ids))
            id_set = set(cached_ids)
            venues = [v for v in venues if v.id in id_set]
        else:
            before = len(venues)
            venues = prefilter_by_distance(
                venues, origin_lat, origin_lng, mode, max_travel_min
            )
            await haversine_cache.set(haversine_key, [v.id for v in venues])
            logger.info(
                "Haversine: %d → %d venues (radius=%.2fkm)",
                before, len(venues), _max_radius_km(mode, max_travel_min),
            )

        # TomTom — travel_time_cache already handled inside get_travel_time()
        for v in venues:
            travel_minutes = await get_travel_time(
                origin=(origin_lat, origin_lng),
                destination=(v.lat, v.lng),
                venue_id=v.id,
                db=db,
                mode=mode,
            )
            if travel_minutes is None:
                logger.warning("Travel time None for venue_id=%d (%s)", v.id, v.name)
                continue
            if travel_minutes > max_travel_min:
                continue
            output.append(_venue_dict(v, travel_minutes=travel_minutes))

    response = {"count": len(output), "venues": output}
    await available_venues_cache.set(cache_key, response)
    logger.info("available_venues Redis SET — %d venues", len(output))
    return response
