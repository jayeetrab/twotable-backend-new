from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import date as date_type
from datetime import datetime
from datetime import time as time_type
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.venue import Venue
from app.models.venue_blackout import VenueBlackout
from app.models.venue_embedding import VenueEmbedding
from app.models.venue_slot import VenueSlot
from app.schemas.suggest import SuggestRequest, VenueSuggestion
from app.services.cache import intent_vector_cache, suggest_cache
from app.services.embeddings import TASK_QUERY, build_intent_text, embedding_provider
from app.services.routing import get_travel_time
from app.services.venue_embeddings import find_similar_venues, log_intent_embedding
from app.api.v1.venues import prefilter_by_distance

logger = logging.getLogger(__name__)

_MAX_LOAD_PENALTY = 0.3


@dataclass
class CandidateVenue:
    venue: Venue
    travel_minutes: Optional[float]


# ── Cache key ─────────────────────────────────────────────────────────────────

def _suggest_cache_key(req: SuggestRequest) -> str:
    raw = (
        f"{req.city}|{req.date}|{req.time}|"
        f"{round(req.origin_lat or 0, 3)},{round(req.origin_lng or 0, 3)}|"
        f"{req.travel_mode}|{req.max_travel_minutes}|"
        f"{req.stage}|{req.mood}|{req.energy}|{req.budget}|"
        f"{req.free_text or ''}|{req.top_n}"
    )
    return hashlib.md5(raw.encode()).hexdigest()


# ── Intent vector — Redis cached ──────────────────────────────────────────────

async def _get_intent_vector(intent_text: str) -> List[float]:
    cached = await intent_vector_cache.get(intent_text)
    if cached is not None:
        return cached
    vector = await embedding_provider.embed(intent_text, task_type=TASK_QUERY)
    await intent_vector_cache.set(intent_text, vector)
    return vector


# ── Layer 1: Hard SQL + pre-filters ──────────────────────────────────────────

async def _get_hard_filtered_candidates(
    db: AsyncSession,
    city: str,
    target_date: date_type,
    target_time: time_type,
    origin_lat: Optional[float],
    origin_lng: Optional[float],
    travel_mode: str,
    max_travel_minutes: int,
) -> List[CandidateVenue]:
    weekday = datetime.combine(target_date, target_time).weekday()

    stmt = (
        select(Venue)
        .join(VenueSlot, VenueSlot.venue_id == Venue.id)
        .where(
            Venue.city.ilike(f"%{city}%"),
            Venue.is_active == True,       # noqa: E712
            VenueSlot.is_active == True,   # noqa: E712
            VenueSlot.weekday == weekday,
            VenueSlot.start_time <= target_time,
            VenueSlot.end_time > target_time,
        )
        .distinct()
    )
    result  = await db.execute(stmt)
    venues: List[Venue] = result.scalars().all()

    if not venues:
        return []

    # Blackout filter
    blackout_result = await db.execute(
        select(VenueBlackout.venue_id).where(
            VenueBlackout.start_date <= target_date,
            VenueBlackout.end_date   >= target_date,
        )
    )
    blacked_out = {r for r in blackout_result.scalars().all()}
    venues = [v for v in venues if v.id not in blacked_out]

    if not venues:
        return []

    # Haversine pre-filter
    if origin_lat is not None and origin_lng is not None:
        before = len(venues)
        venues = prefilter_by_distance(
            venues, origin_lat, origin_lng, travel_mode, max_travel_minutes
        )
        logger.info(
            "Haversine: %d → %d venues (mode=%s max=%dmin)",
            before, len(venues), travel_mode, max_travel_minutes,
        )

    if not venues:
        return []

    # TomTom — get_travel_time() uses DB travel_time_cache internally
    candidates: List[CandidateVenue] = []
    for venue in venues:
        travel_minutes: Optional[float] = None
        if origin_lat is not None and origin_lng is not None and venue.lat and venue.lng:
            travel_minutes = await get_travel_time(
                origin=(origin_lat, origin_lng),
                destination=(venue.lat, venue.lng),
                venue_id=venue.id,
                db=db,
                mode=travel_mode,
            )
            if travel_minutes is None:
                continue
            if travel_minutes > max_travel_minutes:
                continue
        candidates.append(CandidateVenue(venue=venue, travel_minutes=travel_minutes))

    return candidates


# ── Layer 3: Load fairness ────────────────────────────────────────────────────

async def _get_load_factors(
    db: AsyncSession,
    candidate_venue_ids: List[int],
    target_date: date_type,
    target_time: time_type,
) -> Dict[int, float]:
    """
    Real load factor from bookings table (Step 9 complete).
    load = confirmed+pending bookings / max_tables_for_two for that slot.
    """
    from app.models.booking import Booking, BookingStatus
    from app.models.venue_slot import VenueSlot
    from datetime import datetime

    weekday   = datetime.combine(target_date, target_time).weekday()
    date_str  = str(target_date)
    load_map: Dict[int, float] = {}

    for venue_id in candidate_venue_ids:
        # Get the matching slot
        slot_result = await db.execute(
            select(VenueSlot).where(
                VenueSlot.venue_id   == venue_id,
                VenueSlot.weekday    == weekday,
                VenueSlot.start_time <= target_time,
                VenueSlot.end_time   >  target_time,
                VenueSlot.is_active  == True,  # noqa: E712
            ).limit(1)
        )
        slot = slot_result.scalar_one_or_none()
        if not slot:
            load_map[venue_id] = 0.0
            continue

        # Count active bookings for this slot on target date
        count_result = await db.execute(
            select(func.count(Booking.id)).where(
                Booking.slot_id     == slot.id,
                Booking.booked_date == date_str,
                Booking.status.in_([BookingStatus.confirmed, BookingStatus.pending]),
            )
        )
        booked = count_result.scalar() or 0
        load_map[venue_id] = min(booked / max(slot.max_tables_for_two, 1), 1.0)

    return load_map



# ── Main matcher ──────────────────────────────────────────────────────────────

async def suggest_venues(
    db: AsyncSession,
    req: SuggestRequest,
) -> Tuple[List[VenueSuggestion], str]:

    intent_text = build_intent_text(
        stage=req.stage.value,
        mood=req.mood.value,
        energy=req.energy.value,
        budget=req.budget.value,
        city=req.city,
        free_text=req.free_text or "",
    )

    # ── Redis suggest cache check ─────────────────────────────────────────────
    cache_key = _suggest_cache_key(req)
    cached    = await suggest_cache.get(cache_key)
    if cached is not None:
        logger.info("suggest Redis HIT key=%s", cache_key[:12])
        raw_suggestions, cached_intent = cached
        return [VenueSuggestion(**s) for s in raw_suggestions], cached_intent

    # ── Layer 1: Hard filters ─────────────────────────────────────────────────
    candidates = await _get_hard_filtered_candidates(
        db=db,
        city=req.city,
        target_date=req.date,
        target_time=req.time,
        origin_lat=req.origin_lat,
        origin_lng=req.origin_lng,
        travel_mode=req.travel_mode.value,
        max_travel_minutes=req.max_travel_minutes,
    )

    if not candidates:
        logger.info("No candidates after hard filters — city=%s", req.city)
        return [], intent_text

    candidate_ids = [c.venue.id for c in candidates]
    candidate_map = {c.venue.id: c for c in candidates}

    logger.info("Layer 1 passed: %d venues", len(candidates))

    # ── Layer 2: Embedding similarity ─────────────────────────────────────────
    emb_count = (
        await db.execute(
            select(func.count(VenueEmbedding.id))
            .where(VenueEmbedding.venue_id.in_(candidate_ids))
        )
    ).scalar() or 0

    similarity_map: Dict[int, float] = {}

    if emb_count == 0:
        logger.warning("No embeddings for candidates — neutral scores. Run /admin/venues/embed-all")
        similarity_map = {vid: 0.5 for vid in candidate_ids}
    else:
        intent_vector = await _get_intent_vector(intent_text)

        emb_result    = await db.execute(
            select(VenueEmbedding.venue_id)
            .where(VenueEmbedding.venue_id.in_(candidate_ids))
        )
        embedded_ids   = {r for r in emb_result.scalars().all()}
        unembedded_ids = [vid for vid in candidate_ids if vid not in embedded_ids]

        for vid in unembedded_ids:
            similarity_map[vid] = 0.5

        if embedded_ids:
            for venue_id, distance in await find_similar_venues(
                db=db,
                intent_vector=intent_vector,
                candidate_venue_ids=list(embedded_ids),
                top_n=len(embedded_ids),
            ):
                similarity_map[venue_id] = distance

        await log_intent_embedding(
            db=db,
            session_id=req.session_id,
            intent_text=intent_text,
            vector=intent_vector,
        )

    # ── Layer 3: Load fairness ────────────────────────────────────────────────
    load_factors = await _get_load_factors(
        db=db,
        candidate_venue_ids=candidate_ids,
        target_date=req.date,
        target_time=req.time,
    )

    # ── Final scoring ─────────────────────────────────────────────────────────
    scored: List[Tuple[float, int]] = sorted(
        [
            (
                similarity_map.get(vid, 0.5) * (1.0 + load_factors.get(vid, 0.0) * _MAX_LOAD_PENALTY),
                vid,
            )
            for vid in candidate_ids
        ]
    )
    top = scored[: req.top_n]

    # Fetch source_text for debug
    top_ids = [vid for _, vid in top]
    emb_texts = {
        r.venue_id: r.source_text
        for r in (
            await db.execute(
                select(VenueEmbedding.venue_id, VenueEmbedding.source_text)
                .where(VenueEmbedding.venue_id.in_(top_ids))
            )
        ).all()
    }

    # ── Build suggestions ─────────────────────────────────────────────────────
    suggestions: List[VenueSuggestion] = []
    for final_score, venue_id in top:
        c = candidate_map[venue_id]
        v = c.venue
        suggestions.append(VenueSuggestion(
            venue_id=v.id,
            name=v.name,
            address=v.address,
            city=v.city,
            cuisine=v.cuisine,
            vibe_tags=v.vibe_tags,
            noise_level=v.noise_level.value if v.noise_level else None,
            price_band=v.price_band.value if v.price_band else None,
            description=v.description,
            lat=v.lat,
            lng=v.lng,
            travel_minutes=c.travel_minutes,
            similarity_score=round(similarity_map.get(venue_id, 0.5), 4),
            load_factor=round(load_factors.get(venue_id, 0.0), 4),
            final_score=round(final_score, 4),
            source_text=emb_texts.get(venue_id),
        ))

    # ── Store in Redis ────────────────────────────────────────────────────────
    await suggest_cache.set(
        cache_key,
        ([s.model_dump() for s in suggestions], intent_text),
    )

    return suggestions, intent_text
