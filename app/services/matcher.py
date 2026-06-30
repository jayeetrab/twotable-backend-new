"""
Venue suggestion engine (MongoDB).

Pipeline
--------
1. Hard filters  — city, active, an open slot for the requested weekday/time,
                   not blacked out, within travel radius (haversine).
2. Similarity    — in-app cosine between the intent vector and each venue's
                   stored embedding (neutral 0.5 when a venue has none).
3. Load fairness — busier slots are gently down-ranked.

Higher ``final_score`` = better; results are sorted descending.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional, Tuple

from app.db import mongo
from app.schemas.suggest import SuggestRequest, VenueSuggestion
from app.services import embeddings
from app.services.geo import estimate_travel_minutes, within_radius

logger = logging.getLogger(__name__)

_MAX_LOAD_PENALTY = 0.3

# ── Date-appropriateness filter (shared with /venues/available) ────────────────

_NON_DATE_CUISINES = {
    "supermarket", "grocery", "convenience store", "petrol station",
    "fast food", "takeaway", "off licence", "off-licence", "liquor",
    "newsagent", "pharmacy", "bakery", "butcher", "fishmonger", "food court",
    "bagel shop", "sandwich shop", "juice bar", "chicken restaurant", "sports bar",
}
_NON_DATE_VIBES = {"family friendly", "kids", "canteen", "buffet", "cafeteria"}
_NON_DATE_VENUE_TYPES = {"event venue", "coffee shop", "newsagent"}


def is_date_appropriate(venue: dict) -> bool:
    cuisine = venue.get("cuisine")
    if cuisine:
        c = cuisine.lower().strip()
        if any(bad in c for bad in _NON_DATE_CUISINES) or c in _NON_DATE_VENUE_TYPES:
            return False
    tags_raw = venue.get("vibe_tags")
    if tags_raw:
        tags = [t.strip().lower() for t in str(tags_raw).split(",")]
        if any(tag in _NON_DATE_VIBES for tag in tags):
            return False
    return True


def _matching_slot(venue: dict, weekday: int, target_time: str) -> Optional[dict]:
    """First active slot covering (weekday, target_time). Times are 'HH:MM:SS'."""
    for slot in venue.get("slots", []):
        if not slot.get("is_active", True):
            continue
        if slot.get("weekday") != weekday:
            continue
        if slot.get("start_time", "") <= target_time < slot.get("end_time", ""):
            return slot
    return None


def _is_blacked_out(venue: dict, date_str: str) -> bool:
    for b in venue.get("blackouts", []):
        if b.get("start_date", "") <= date_str <= b.get("end_date", "9999-12-31"):
            return True
    return False


async def _load_factor(venue_id: int, slot_id, date_str: str, max_tables: int) -> float:
    if slot_id is None:
        return 0.0
    db = mongo.get_db()
    booked = await db[mongo.BOOKINGS].count_documents({
        "venue_id": venue_id,
        "slot_id": slot_id,
        "booked_date": date_str,
        "status": {"$in": ["confirmed", "pending"]},
    })
    return min(booked / max(max_tables, 1), 1.0)


async def suggest_venues(
    req: SuggestRequest,
) -> Tuple[List[VenueSuggestion], str]:
    db = mongo.get_db()

    intent_text = embeddings.build_intent_text(
        stage=req.stage.value,
        mood=req.mood.value,
        energy=req.energy.value,
        budget=req.budget.value,
        city=req.city,
        free_text=req.free_text or "",
    )

    weekday = datetime.combine(req.date, req.time).weekday()
    target_time = req.time.isoformat()
    date_str = req.date.isoformat()

    # ── Layer 1: hard filters ─────────────────────────────────────────────────
    cursor = db[mongo.VENUES].find({
        "city": {"$regex": req.city, "$options": "i"},
        "is_active": True,
    })
    venues = await cursor.to_list(length=None)

    candidates: list[dict] = []
    for v in venues:
        slot = _matching_slot(v, weekday, target_time)
        if not slot:
            continue
        if _is_blacked_out(v, date_str):
            continue
        if not is_date_appropriate(v):
            continue

        travel_minutes: Optional[float] = None
        if req.origin_lat is not None and req.origin_lng is not None:
            if v.get("lat") is None or v.get("lng") is None:
                continue
            if not within_radius(req.origin_lat, req.origin_lng, v["lat"], v["lng"],
                                 req.travel_mode.value, req.max_travel_minutes):
                continue
            travel_minutes = estimate_travel_minutes(
                req.origin_lat, req.origin_lng, v["lat"], v["lng"], req.travel_mode.value
            )
            if travel_minutes > req.max_travel_minutes:
                continue

        candidates.append({"venue": v, "slot": slot, "travel_minutes": travel_minutes})

    if not candidates:
        logger.info("No candidates after hard filters — city=%s", req.city)
        return [], intent_text

    logger.info("Layer 1 passed: %d venues", len(candidates))

    # ── Layer 2: cosine similarity ────────────────────────────────────────────
    has_embeddings = any(c["venue"].get("embedding") for c in candidates)
    intent_vec: Optional[List[float]] = None
    if has_embeddings:
        intent_vec = await embeddings.embed(intent_text)

    # ── Layer 3 + scoring ─────────────────────────────────────────────────────
    scored: list[tuple[float, dict, float, float]] = []
    for c in candidates:
        v = c["venue"]
        emb = v.get("embedding")
        if intent_vec is not None and emb:
            sim01 = (embeddings.cosine(intent_vec, emb) + 1.0) / 2.0
        else:
            sim01 = 0.5

        load = await _load_factor(
            v["_id"], c["slot"].get("id"), date_str,
            c["slot"].get("max_tables_for_two", 2),
        )
        final = sim01 * (1.0 - load * _MAX_LOAD_PENALTY)
        scored.append((final, c, sim01, load))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[: req.top_n]

    suggestions: List[VenueSuggestion] = []
    for final, c, sim01, load in top:
        v = c["venue"]
        suggestions.append(VenueSuggestion(
            venue_id=v["_id"],
            name=v["name"],
            address=v.get("address", ""),
            city=v.get("city", ""),
            cuisine=v.get("cuisine"),
            vibe_tags=v.get("vibe_tags"),
            noise_level=v.get("noise_level"),
            price_band=v.get("price_band"),
            description=v.get("description"),
            lat=v.get("lat"),
            lng=v.get("lng"),
            travel_minutes=c["travel_minutes"],
            similarity_score=round(sim01, 4),
            load_factor=round(load, 4),
            final_score=round(final, 4),
            source_text=v.get("source_text"),
        ))

    return suggestions, intent_text
