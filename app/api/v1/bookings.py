from __future__ import annotations

import logging
from typing import Optional

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone
from app.core.config import settings
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.booking import Booking, BookingStatus
from app.models.match import Match, MatchStatus
from app.models.user import User
from app.models.venue import Venue
from app.models.venue_slot import VenueSlot
from app.schemas.booking import BookingCreate, BookingRead, MatchCreate, MatchRead
from app.services.cache import available_venues_cache, suggest_cache

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/bookings", tags=["bookings"])

stripe.api_key = settings.STRIPE_SECRET_KEY
DEPOSIT_PENCE  = 1000  # £10.00


# ── Private helpers ───────────────────────────────────────────────────────────

async def _venue_or_404(db: AsyncSession, venue_id: int) -> Venue:
    r = await db.execute(select(Venue).where(Venue.id == venue_id))
    v = r.scalar_one_or_none()
    if not v:
        raise HTTPException(status_code=404, detail="Venue not found")
    return v


async def _slot_or_404(db: AsyncSession, slot_id: int, venue_id: int) -> VenueSlot:
    r = await db.execute(
        select(VenueSlot).where(
            VenueSlot.id        == slot_id,
            VenueSlot.venue_id  == venue_id,
            VenueSlot.is_active == True,  # noqa: E712
        )
    )
    s = r.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Slot not found or inactive")
    return s


async def _slot_load(db: AsyncSession, slot_id: int, booked_date: str, max_tables: int) -> float:
    r = await db.execute(
        select(func.count(Booking.id)).where(
            Booking.slot_id     == slot_id,
            Booking.booked_date == booked_date,
            Booking.status.in_([BookingStatus.confirmed, BookingStatus.pending]),
        )
    )
    return min((r.scalar() or 0) / max(max_tables, 1), 1.0)


async def _assert_match_member(match: Match, user_id: int) -> None:
    if user_id not in (match.user_a_id, match.user_b_id):
        raise HTTPException(status_code=403, detail="Not your match")


# ── Matches ───────────────────────────────────────────────────────────────────

@router.post("/matches", response_model=MatchRead, status_code=201)
async def create_match(
    payload: MatchCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """User A proposes a venue + slot. Status = pending until User B joins."""
    await _venue_or_404(db, payload.venue_id)
    await _slot_or_404(db, payload.slot_id, payload.venue_id)

    match = Match(
        user_a_id = current_user.id,
        venue_id  = payload.venue_id,
        slot_id   = payload.slot_id,
        city      = payload.city,
        date      = str(payload.date),
        time      = str(payload.time),
        mood      = payload.mood,
        stage     = payload.stage,
        status    = MatchStatus.pending,
    )
    db.add(match)
    await db.commit()
    await db.refresh(match)
    logger.info("Match created id=%d user_a=%d venue=%d", match.id, current_user.id, payload.venue_id)
    return match


@router.post("/matches/{match_id}/join", response_model=MatchRead)
async def join_match(
    match_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """User B joins a pending match → status becomes confirmed."""
    r     = await db.execute(select(Match).where(Match.id == match_id))
    match = r.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if match.status != MatchStatus.pending:
        raise HTTPException(status_code=400, detail=f"Match is already {match.status}")
    if match.user_a_id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot join your own match")

    match.user_b_id = current_user.id
    match.status    = MatchStatus.confirmed
    await db.commit()
    await db.refresh(match)
    logger.info("Match joined id=%d user_b=%d", match.id, current_user.id)
    return match


@router.get("/matches/{match_id}", response_model=MatchRead)
async def get_match(
    match_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r     = await db.execute(select(Match).where(Match.id == match_id))
    match = r.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    await _assert_match_member(match, current_user.id)
    return match


@router.delete("/matches/{match_id}", status_code=204)
async def cancel_match(
    match_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r     = await db.execute(select(Match).where(Match.id == match_id))
    match = r.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    await _assert_match_member(match, current_user.id)
    if match.status == MatchStatus.completed:
        raise HTTPException(status_code=400, detail="Cannot cancel a completed match")
    match.status = MatchStatus.cancelled
    await db.commit()


# ── Bookings ──────────────────────────────────────────────────────────────────

@router.post("", response_model=BookingRead, status_code=201)
async def create_booking(
    payload: BookingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a booking from a confirmed match. Charges £10 Stripe deposit."""
    r     = await db.execute(select(Match).where(Match.id == payload.match_id))
    match = r.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if match.status != MatchStatus.confirmed:
        raise HTTPException(status_code=400, detail="Match must be confirmed before booking")
    await _assert_match_member(match, current_user.id)

    # Prevent duplicate booking
    dup = await db.execute(
        select(Booking).where(
            Booking.match_id == payload.match_id,
            Booking.status.not_in([BookingStatus.cancelled, BookingStatus.refunded]),
        )
    )
    if dup.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Booking already exists for this match")

    venue = await _venue_or_404(db, payload.venue_id)
    slot  = await _slot_or_404(db, payload.slot_id, payload.venue_id)

    # Capacity check
    load = await _slot_load(db, slot.id, str(payload.date), slot.max_tables_for_two)
    if load >= 1.0:
        raise HTTPException(
            status_code=409,
            detail=f"No tables left for {venue.name} on {payload.date} at {payload.time}",
        )

    # Stripe PaymentIntent
    payment_intent_id: Optional[str] = None
    initial_status = BookingStatus.confirmed  # dev fallback when no Stripe key

    if settings.STRIPE_SECRET_KEY:
        try:
            intent = stripe.PaymentIntent.create(
                amount=DEPOSIT_PENCE,
                currency="gbp",
                metadata={
                    "match_id": str(payload.match_id),
                    "venue_id": str(payload.venue_id),
                    "user_id":  str(current_user.id),
                    "date":     str(payload.date),
                    "time":     str(payload.time),
                },
                description=f"TwoTable deposit — {venue.name} {payload.date}",
            )
            payment_intent_id = intent.id
            initial_status    = BookingStatus.pending  # wait for webhook
            logger.info("Stripe PaymentIntent created: %s", payment_intent_id)
        except stripe.StripeError as exc:
            logger.error("Stripe error: %s", exc)
            raise HTTPException(status_code=502, detail=f"Payment failed: {exc}")
    else:
        logger.warning("STRIPE_SECRET_KEY not set — booking auto-confirmed (dev mode)")

    booking = Booking(
        match_id=payload.match_id,
        venue_id=payload.venue_id,
        slot_id=payload.slot_id,
        booked_date=str(payload.date),
        booked_time=str(payload.time),
        deposit_amount_pence=DEPOSIT_PENCE,
        stripe_payment_intent_id=payment_intent_id,
        status=initial_status,
    )
    db.add(booking)
    await db.commit()
    await db.refresh(booking)

    # Invalidate caches — load factor changed
    await available_venues_cache.clear()
    await suggest_cache.clear()

    logger.info(
        "Booking created id=%d match=%d venue=%s date=%s status=%s",
        booking.id, payload.match_id, venue.name, payload.date, booking.status,
    )
    return booking


@router.post("/{booking_id}/confirm", response_model=BookingRead)
async def confirm_booking(
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Manually confirm a booking.
    In production this is called automatically by the Stripe webhook.
    """
    r       = await db.execute(select(Booking).where(Booking.id == booking_id))
    booking = r.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.status != BookingStatus.pending:
        raise HTTPException(status_code=400, detail=f"Booking already {booking.status}")

    booking.status = BookingStatus.confirmed

    match_r = await db.execute(select(Match).where(Match.id == booking.match_id))
    match   = match_r.scalar_one_or_none()
    if match:
        match.status = MatchStatus.completed

    await db.commit()
    await db.refresh(booking)
    return booking

@router.delete("/{booking_id}", status_code=204)
async def cancel_booking(
    booking_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    booking = await db.get(Booking, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    # only participants can cancel
    match = await db.get(Match, booking.match_id)
    if current_user.id not in (match.user_a_id, match.user_b_id):
        raise HTTPException(status_code=403, detail="Not your booking")
    
    if booking.status == BookingStatus.confirmed:
        # optionally: trigger Stripe refund here
        pass

    booking.status = BookingStatus.cancelled
    booking.updated_at = datetime.now(timezone.utc)
    await db.commit()

@router.get("/{booking_id}", response_model=BookingRead)
async def get_booking(
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r       = await db.execute(select(Booking).where(Booking.id == booking_id))
    booking = r.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    match_r = await db.execute(select(Match).where(Match.id == booking.match_id))
    match   = match_r.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    await _assert_match_member(match, current_user.id)
    return booking


# ── Stripe webhook ────────────────────────────────────────────────────────────

@router.post("/stripe/webhook", include_in_schema=False)
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Receives Stripe payment_intent.succeeded events.
    Register in Stripe Dashboard → Webhooks:
      https://your-domain.com/api/v1/bookings/stripe/webhook
    Events to send: payment_intent.succeeded
    """
    payload    = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Webhook secret not configured")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except stripe.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature")

    if event["type"] == "payment_intent.succeeded":
        pi_id = event["data"]["object"]["id"]
        r     = await db.execute(
            select(Booking).where(Booking.stripe_payment_intent_id == pi_id)
        )
        booking = r.scalar_one_or_none()
        if booking and booking.status == BookingStatus.pending:
            booking.status = BookingStatus.confirmed
            match_r = await db.execute(select(Match).where(Match.id == booking.match_id))
            match   = match_r.scalar_one_or_none()
            if match:
                match.status = MatchStatus.completed
            await db.commit()
            logger.info("Stripe webhook confirmed booking id=%d", booking.id)

    return {"received": True}
