from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_admin, get_current_user
from app.db.session import get_db
from app.models.booking import Booking, BookingStatus
from app.models.match import Match, MatchStatus
from app.models.user import User
from app.models.venue import Venue
from app.models.venue_blackout import VenueBlackout
from app.models.venue_lead import VenueLead, VenueLeadStatus
from app.models.venue_slot import VenueSlot
from app.models.waitlist import WaitlistSubscriber
from app.schemas.booking import BookingRead, MatchRead
from app.schemas.venue import (
    VenueBlackoutCreate, VenueBlackoutRead,
    VenuePromoteRequest, VenueRead,
    VenueSlotCreate, VenueSlotRead,
    VenueUpdate,
)
from app.schemas.venue_lead import VenueLeadRead, VenueLeadStatusUpdate
from app.schemas.waitlist import WaitlistRead
from app.services.cache import (
    available_venues_cache,
    haversine_cache,
    intent_vector_cache,
    suggest_cache,
)
from app.services.geocoding import geocode
from app.services.ollama_enrich import enrich_venue_with_ollama as enrich_venue_with_gemini
from app.services.venue_embeddings import embed_all_venues, upsert_venue_embedding

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])

_GENERIC_SUFFIX = "is a restaurant in Bristol."
_GENERIC_VIBE   = "date night, restaurant"


def _needs_enrichment(venue: Venue) -> bool:
    desc_generic = (
        not venue.description
        or venue.description.strip().endswith(_GENERIC_SUFFIX)
        or venue.description.strip() == ""
    )
    vibe_generic = (
        not venue.vibe_tags
        or venue.vibe_tags.strip() == _GENERIC_VIBE
        or venue.vibe_tags.strip() == ""
    )
    return desc_generic or vibe_generic


# ── Cache ─────────────────────────────────────────────────────────────────────

@router.get("/cache/stats")
async def cache_stats(_: User = Depends(get_current_admin)):
    return {
        "caches": [
            await available_venues_cache.stats(),
            await haversine_cache.stats(),
            await intent_vector_cache.stats(),
            await suggest_cache.stats(),
        ]
    }


@router.delete("/cache/clear")
async def clear_all_caches(_: User = Depends(get_current_admin)):
    await available_venues_cache.clear()
    await haversine_cache.clear()
    await intent_vector_cache.clear()
    await suggest_cache.clear()
    return {"cleared": True}


# ── Waitlist ──────────────────────────────────────────────────────────────────

@router.get("/waitlist", response_model=list[WaitlistRead])
async def list_waitlist(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    result = await db.execute(
        select(WaitlistSubscriber)
        .offset(skip).limit(limit)
        .order_by(WaitlistSubscriber.created_at.desc())
    )
    return result.scalars().all()


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/users", tags=["admin"])
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    role: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    query = (
        select(User)
        .offset(skip).limit(limit)
        .order_by(User.created_at.desc())
    )
    if role:
        query = query.where(User.role == role)
    result = await db.execute(query)
    users = result.scalars().all()
    return [
        {
            "id": u.id,
            "email": u.email,
            "full_name": u.full_name,
            "role": u.role,
            "is_active": u.is_active,
            "created_at": u.created_at,
        }
        for u in users
    ]


@router.patch("/users/{user_id}/deactivate")
async def deactivate_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = False
    await db.commit()
    return {"id": user_id, "is_active": False}


@router.patch("/users/{user_id}/activate")
async def activate_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = True
    await db.commit()
    return {"id": user_id, "is_active": True}


# ── Venue Leads ───────────────────────────────────────────────────────────────

@router.get("/venues/leads", response_model=list[VenueLeadRead])
async def list_venue_leads(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status: Optional[VenueLeadStatus] = Query(None),
    city: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    query = (
        select(VenueLead)
        .offset(skip).limit(limit)
        .order_by(VenueLead.created_at.desc())
    )
    if status:
        query = query.where(VenueLead.status == status)
    if city:
        query = query.where(VenueLead.city.ilike(f"%{city}%"))
    result = await db.execute(query)
    return result.scalars().all()


@router.patch("/venues/leads/{lead_id}/status", response_model=VenueLeadRead)
async def update_lead_status(
    lead_id: int,
    payload: VenueLeadStatusUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    result = await db.execute(select(VenueLead).where(VenueLead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    lead.status = payload.status
    await db.commit()
    await db.refresh(lead)
    return lead


@router.post("/venues/leads/{lead_id}/promote", response_model=VenueRead)
async def promote_lead_to_venue(
    lead_id: int,
    payload: VenuePromoteRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    result = await db.execute(select(VenueLead).where(VenueLead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if lead.status != VenueLeadStatus.approved:
        raise HTTPException(status_code=400, detail="Only approved leads can be promoted")

    existing = await db.execute(select(Venue).where(Venue.email == lead.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Venue with this email already exists")

    geocode_query = f"{lead.address}, {lead.city}, UK"
    coords = await geocode(geocode_query, db)
    lat = coords[0] if coords else None
    lng = coords[1] if coords else None

    venue = Venue(
        lead_id=lead.id,
        name=lead.venue_name,
        email=lead.email,
        phone=lead.phone,
        website=lead.website,
        address=lead.address,
        city=lead.city,
        postcode=payload.postcode,
        lat=lat,
        lng=lng,
        cuisine=lead.cuisine,
        vibe_tags=lead.vibes or payload.vibe_tags,
        description=payload.description,
        noise_level=payload.noise_level,
        price_band=payload.price_band,
        total_capacity=lead.seating_capacity,
    )
    db.add(venue)
    lead.status = VenueLeadStatus.promoted
    await db.commit()
    await db.refresh(venue)
    return venue


# ── Venues ────────────────────────────────────────────────────────────────────

@router.get("/venues", response_model=list[VenueRead])
async def list_venues(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    city: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    query = (
        select(Venue)
        .options(selectinload(Venue.slots), selectinload(Venue.blackouts))
        .offset(skip).limit(limit)
        .order_by(Venue.created_at.desc())
    )
    if city:
        query = query.where(Venue.city.ilike(f"%{city}%"))
    if is_active is not None:
        query = query.where(Venue.is_active == is_active)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/venues/{venue_id}", response_model=VenueRead)
async def get_venue(
    venue_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    result = await db.execute(
        select(Venue)
        .options(selectinload(Venue.slots), selectinload(Venue.blackouts))
        .where(Venue.id == venue_id)
    )
    venue = result.scalar_one_or_none()
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")
    return venue


@router.patch("/venues/{venue_id}", response_model=VenueRead)
async def update_venue(
    venue_id: int,
    payload: VenueUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    result = await db.execute(select(Venue).where(Venue.id == venue_id))
    venue = result.scalar_one_or_none()
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(venue, field, value)
    venue.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(venue)
    await available_venues_cache.clear()
    await suggest_cache.clear()
    return venue


@router.delete("/venues/{venue_id}", status_code=204)
async def deactivate_venue(
    venue_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    result = await db.execute(select(Venue).where(Venue.id == venue_id))
    venue = result.scalar_one_or_none()
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")
    venue.is_active = False
    await db.commit()
    await available_venues_cache.clear()
    await suggest_cache.clear()


# ── Venue Slots ───────────────────────────────────────────────────────────────

@router.post("/venues/{venue_id}/slots", response_model=VenueSlotRead, status_code=201)
async def add_venue_slot(
    venue_id: int,
    payload: VenueSlotCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    result = await db.execute(select(Venue).where(Venue.id == venue_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Venue not found")
    slot = VenueSlot(venue_id=venue_id, **payload.model_dump())
    db.add(slot)
    await db.commit()
    await db.refresh(slot)
    return slot


@router.patch("/venues/{venue_id}/slots/{slot_id}", response_model=VenueSlotRead)
async def update_venue_slot(
    venue_id: int,
    slot_id: int,
    payload: VenueSlotCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    result = await db.execute(
        select(VenueSlot).where(VenueSlot.id == slot_id, VenueSlot.venue_id == venue_id)
    )
    slot = result.scalar_one_or_none()
    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(slot, field, value)
    await db.commit()
    await db.refresh(slot)
    return slot


@router.delete("/venues/{venue_id}/slots/{slot_id}", status_code=204)
async def delete_venue_slot(
    venue_id: int,
    slot_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    result = await db.execute(
        select(VenueSlot).where(VenueSlot.id == slot_id, VenueSlot.venue_id == venue_id)
    )
    slot = result.scalar_one_or_none()
    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found")
    await db.delete(slot)
    await db.commit()


# ── Venue Blackouts ───────────────────────────────────────────────────────────

@router.post("/venues/{venue_id}/blackouts", response_model=VenueBlackoutRead, status_code=201)
async def add_venue_blackout(
    venue_id: int,
    payload: VenueBlackoutCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    result = await db.execute(select(Venue).where(Venue.id == venue_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Venue not found")
    if payload.end_date < payload.start_date:
        raise HTTPException(status_code=400, detail="end_date must be on or after start_date")
    blackout = VenueBlackout(venue_id=venue_id, **payload.model_dump())
    db.add(blackout)
    await db.commit()
    await db.refresh(blackout)
    return blackout


@router.delete("/venues/{venue_id}/blackouts/{blackout_id}", status_code=204)
async def delete_venue_blackout(
    venue_id: int,
    blackout_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    result = await db.execute(
        select(VenueBlackout).where(
            VenueBlackout.id == blackout_id,
            VenueBlackout.venue_id == venue_id,
        )
    )
    blackout = result.scalar_one_or_none()
    if not blackout:
        raise HTTPException(status_code=404, detail="Blackout not found")
    await db.delete(blackout)
    await db.commit()


# ── Bookings (admin view) ─────────────────────────────────────────────────────

@router.get("/bookings", response_model=list[BookingRead])
async def list_all_bookings(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status: Optional[BookingStatus] = Query(None),
    venue_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    query = (
        select(Booking)
        .offset(skip).limit(limit)
        .order_by(Booking.created_at.desc())
    )
    if status:
        query = query.where(Booking.status == status)
    if venue_id:
        query = query.where(Booking.venue_id == venue_id)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/bookings/stats")
async def booking_stats(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    total = await db.scalar(select(func.count(Booking.id)))
    confirmed = await db.scalar(
        select(func.count(Booking.id)).where(Booking.status == BookingStatus.confirmed)
    )
    pending = await db.scalar(
        select(func.count(Booking.id)).where(Booking.status == BookingStatus.pending)
    )
    cancelled = await db.scalar(
        select(func.count(Booking.id)).where(Booking.status == BookingStatus.cancelled)
    )
    revenue_pence = await db.scalar(
        select(func.sum(Booking.deposit_amount_pence)).where(
            Booking.status == BookingStatus.confirmed
        )
    ) or 0
    return {
        "total_bookings": total,
        "confirmed": confirmed,
        "pending": pending,
        "cancelled": cancelled,
        "revenue_gbp": round(revenue_pence / 100, 2),
    }


@router.get("/matches", response_model=list[MatchRead])
async def list_all_matches(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status: Optional[MatchStatus] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    query = (
        select(Match)
        .offset(skip).limit(limit)
        .order_by(Match.created_at.desc())
    )
    if status:
        query = query.where(Match.status == status)
    result = await db.execute(query)
    return result.scalars().all()


# ── Enrichment ────────────────────────────────────────────────────────────────

@router.post("/venues/{venue_id}/enrich")
async def enrich_venue(
    venue_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    result = await db.execute(select(Venue).where(Venue.id == venue_id))
    venue = result.scalar_one_or_none()
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")
    enriched = await enrich_venue_with_gemini(
        name=venue.name,
        types_list=[venue.cuisine or "restaurant"],
        reviews=[],
        attributes={},
    )
    if enriched.get("noise_level"):
        venue.noise_level = enriched["noise_level"]
    if enriched.get("vibe_tags"):
        venue.vibe_tags = enriched["vibe_tags"]
    if enriched.get("description"):
        venue.description = enriched["description"]
    await db.commit()
    await db.refresh(venue)
    return {
        "venue_id":    venue.id,
        "name":        venue.name,
        "noise_level": venue.noise_level,
        "vibe_tags":   venue.vibe_tags,
        "description": venue.description,
    }


@router.post("/venues/enrich-all")
async def enrich_all_generic_venues(
    dry_run: bool = False,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    result = await db.execute(select(Venue).where(Venue.is_active == True))  # noqa: E712
    all_venues: list[Venue] = result.scalars().all()
    needs_work = [v for v in all_venues if _needs_enrichment(v)]
    total = len(needs_work)

    if dry_run:
        return {
            "dry_run": True,
            "venues_needing_enrichment": total,
            "sample": [
                {"id": v.id, "name": v.name, "description": v.description, "vibe_tags": v.vibe_tags}
                for v in needs_work[:10]
            ],
        }

    success = failed = skipped = 0
    for i, venue in enumerate(needs_work):
        try:
            enriched = await enrich_venue_with_gemini(
                name=venue.name,
                types_list=[venue.cuisine or "restaurant"],
                reviews=[],
                attributes={},
            )
            new_desc = enriched.get("description", "").strip()
            if not new_desc or new_desc.endswith(_GENERIC_SUFFIX):
                skipped += 1
            else:
                if enriched.get("noise_level"):
                    venue.noise_level = enriched["noise_level"]
                if enriched.get("vibe_tags"):
                    venue.vibe_tags = enriched["vibe_tags"]
                venue.description = new_desc
                await db.commit()
                success += 1
                logger.info("[%d/%d] Enriched venue_id=%d (%s)", i + 1, total, venue.id, venue.name)
        except Exception as exc:
            await db.rollback()
            failed += 1
            logger.error("[%d/%d] Failed venue_id=%d: %s", i + 1, total, venue.id, exc)

    await suggest_cache.clear()
    await available_venues_cache.clear()
    return {"total": total, "success": success, "failed": failed, "skipped": skipped}


# ── Embeddings ────────────────────────────────────────────────────────────────

@router.post("/venues/{venue_id}/embed")
async def embed_single_venue(
    venue_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    result = await db.execute(select(Venue).where(Venue.id == venue_id))
    venue = result.scalar_one_or_none()
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")
    row = await upsert_venue_embedding(db=db, venue=venue)
    return {"venue_id": venue.id, "name": venue.name, "model": row.model_name, "source_text": row.source_text}


@router.post("/venues/embed-all")
async def embed_all(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    stats = await embed_all_venues(db=db)
    await suggest_cache.clear()
    return stats
