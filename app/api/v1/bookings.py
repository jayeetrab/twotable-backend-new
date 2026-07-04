from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.core.config import settings
from app.core.deps import get_current_user
from app.db import mongo
from app.models.booking import BookingStatus
from app.models.match import MatchStatus
from app.schemas.booking import BookingCreate, BookingRead, MatchCreate, MatchRead

try:
    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY or None
except Exception:  # pragma: no cover - stripe optional
    stripe = None

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/bookings", tags=["bookings"])

DEPOSIT_PENCE = 1000  # £10.00
_ACTIVE_BOOKING = [BookingStatus.confirmed.value, BookingStatus.pending.value]


# ── Serializers ───────────────────────────────────────────────────────────────

def _booking_read(doc: dict) -> BookingRead:
    return BookingRead.model_validate({**doc, "id": doc["_id"]})


async def _match_read(doc: dict) -> MatchRead:
    db = mongo.get_db()
    bookings = await db[mongo.BOOKINGS].find({"match_id": doc["_id"]}).to_list(length=None)
    return MatchRead.model_validate({
        **doc,
        "id": doc["_id"],
        "bookings": [{**b, "id": b["_id"]} for b in bookings],
    })


# ── Lookups ───────────────────────────────────────────────────────────────────

async def _venue_or_404(venue_id: int) -> dict:
    db = mongo.get_db()
    v = await db[mongo.VENUES].find_one({"_id": venue_id})
    if not v:
        raise HTTPException(status_code=404, detail="Venue not found")
    return v


def _slot_or_404(venue: dict, slot_id: int) -> dict:
    for slot in venue.get("slots", []):
        if slot.get("id") == slot_id and slot.get("is_active", True):
            return slot
    raise HTTPException(status_code=404, detail="Slot not found or inactive")


async def _match_or_404(match_id: int) -> dict:
    db = mongo.get_db()
    m = await db[mongo.MATCHES].find_one({"_id": match_id})
    if not m:
        raise HTTPException(status_code=404, detail="Match not found")
    return m


def _assert_match_member(match: dict, user_id: int) -> None:
    if user_id not in (match.get("user_a_id"), match.get("user_b_id")):
        raise HTTPException(status_code=403, detail="Not your match")


async def _slot_load(slot_id: int, booked_date: str, max_tables: int) -> float:
    db = mongo.get_db()
    count = await db[mongo.BOOKINGS].count_documents({
        "slot_id": slot_id,
        "booked_date": booked_date,
        "status": {"$in": _ACTIVE_BOOKING},
    })
    return min(count / max(max_tables, 1), 1.0)


# ── Matches ───────────────────────────────────────────────────────────────────

@router.post("/matches", response_model=MatchRead, status_code=201)
async def create_match(payload: MatchCreate, current_user: dict = Depends(get_current_user)):
    """User A proposes a venue + slot. Status = pending until User B joins."""
    venue = await _venue_or_404(payload.venue_id)
    _slot_or_404(venue, payload.slot_id)

    db = mongo.get_db()
    now = datetime.now(timezone.utc)
    doc = {
        "_id": await mongo.next_id("matches"),
        "user_a_id": current_user["_id"],
        "user_b_id": None,
        "venue_id": payload.venue_id,
        "slot_id": payload.slot_id,
        "status": MatchStatus.pending.value,
        "city": payload.city,
        "date": str(payload.date),
        "time": str(payload.time),
        "mood": payload.mood,
        "stage": payload.stage,
        "created_at": now,
        "updated_at": now,
    }
    await db[mongo.MATCHES].insert_one(doc)
    logger.info("Match created id=%s user_a=%s venue=%s", doc["_id"], current_user["_id"], payload.venue_id)
    return await _match_read(doc)


@router.post("/matches/{match_id}/join", response_model=MatchRead)
async def join_match(match_id: int, current_user: dict = Depends(get_current_user)):
    """User B joins a pending match → status becomes confirmed."""
    match = await _match_or_404(match_id)
    if match["status"] != MatchStatus.pending.value:
        raise HTTPException(status_code=400, detail=f"Match is already {match['status']}")
    if match["user_a_id"] == current_user["_id"]:
        raise HTTPException(status_code=400, detail="You cannot join your own match")

    db = mongo.get_db()
    match = await db[mongo.MATCHES].find_one_and_update(
        {"_id": match_id},
        {"$set": {
            "user_b_id": current_user["_id"],
            "status": MatchStatus.confirmed.value,
            "updated_at": datetime.now(timezone.utc),
        }},
        return_document=True,
    )
    logger.info("Match joined id=%s user_b=%s", match_id, current_user["_id"])
    return await _match_read(match)


@router.get("/matches/{match_id}", response_model=MatchRead)
async def get_match(match_id: int, current_user: dict = Depends(get_current_user)):
    match = await _match_or_404(match_id)
    _assert_match_member(match, current_user["_id"])
    return await _match_read(match)


@router.delete("/matches/{match_id}", status_code=204)
async def cancel_match(match_id: int, current_user: dict = Depends(get_current_user)):
    match = await _match_or_404(match_id)
    _assert_match_member(match, current_user["_id"])
    if match["status"] == MatchStatus.completed.value:
        raise HTTPException(status_code=400, detail="Cannot cancel a completed match")
    db = mongo.get_db()
    await db[mongo.MATCHES].update_one(
        {"_id": match_id},
        {"$set": {"status": MatchStatus.cancelled.value, "updated_at": datetime.now(timezone.utc)}},
    )


# ── Bookings ──────────────────────────────────────────────────────────────────

@router.post("", response_model=BookingRead, status_code=201)
async def create_booking(payload: BookingCreate, current_user: dict = Depends(get_current_user)):
    """Create a booking from a confirmed match. Charges a £10 Stripe deposit if configured."""
    db = mongo.get_db()
    match = await _match_or_404(payload.match_id)
    if match["status"] != MatchStatus.confirmed.value:
        raise HTTPException(status_code=400, detail="Match must be confirmed before booking")
    _assert_match_member(match, current_user["_id"])

    dup = await db[mongo.BOOKINGS].find_one({
        "match_id": payload.match_id,
        "status": {"$nin": [BookingStatus.cancelled.value, BookingStatus.refunded.value]},
    })
    if dup:
        raise HTTPException(status_code=409, detail="Booking already exists for this match")

    venue = await _venue_or_404(payload.venue_id)
    slot = _slot_or_404(venue, payload.slot_id)

    load = await _slot_load(payload.slot_id, str(payload.date), slot.get("max_tables_for_two", 2))
    if load >= 1.0:
        raise HTTPException(
            status_code=409,
            detail=f"No tables left for {venue['name']} on {payload.date} at {payload.time}",
        )

    payment_intent_id: Optional[str] = None
    initial_status = BookingStatus.confirmed.value  # dev fallback when no Stripe key

    if stripe is not None and settings.STRIPE_SECRET_KEY:
        try:
            intent = stripe.PaymentIntent.create(
                amount=DEPOSIT_PENCE,
                currency="gbp",
                metadata={
                    "match_id": str(payload.match_id),
                    "venue_id": str(payload.venue_id),
                    "user_id": str(current_user["_id"]),
                    "date": str(payload.date),
                    "time": str(payload.time),
                },
                description=f"TwoTable deposit — {venue['name']} {payload.date}",
            )
            payment_intent_id = intent.id
            initial_status = BookingStatus.pending.value  # wait for webhook
        except stripe.StripeError as exc:
            logger.error("Stripe error: %s", exc)
            raise HTTPException(status_code=502, detail=f"Payment failed: {exc}")
    else:
        logger.warning("Stripe not configured — booking auto-confirmed (dev mode)")

    now = datetime.now(timezone.utc)
    doc = {
        "_id": await mongo.next_id("bookings"),
        "match_id": payload.match_id,
        "venue_id": payload.venue_id,
        "slot_id": payload.slot_id,
        "status": initial_status,
        "stripe_payment_intent_id": payment_intent_id,
        "deposit_amount_pence": DEPOSIT_PENCE,
        "booked_date": str(payload.date),
        "booked_time": str(payload.time),
        "created_at": now,
        "updated_at": now,
    }
    await db[mongo.BOOKINGS].insert_one(doc)
    logger.info("Booking created id=%s match=%s venue=%s status=%s",
                doc["_id"], payload.match_id, venue["name"], initial_status)
    return _booking_read(doc)


# ── Quick booking (single user locks a table from the app booking flow) ────────

class QuickBookingRequest(BaseModel):
    venue_id: int
    date: str
    time: str
    deposit_pence: int = DEPOSIT_PENCE


@router.post("/quick", status_code=201)
async def quick_booking(payload: QuickBookingRequest, current_user: dict = Depends(get_current_user)):
    """Create a confirmed booking for the current user (dev: no Stripe). Stored in MongoDB."""
    db = mongo.get_db()
    venue = await _venue_or_404(payload.venue_id)
    now = datetime.now(timezone.utc)
    doc = {
        "_id": await mongo.next_id("bookings"),
        "user_id": current_user["_id"],
        "match_id": None,
        "venue_id": payload.venue_id,
        "venue_name": venue.get("name"),
        "slot_id": None,
        "status": BookingStatus.confirmed.value,
        "stripe_payment_intent_id": None,
        "deposit_amount_pence": payload.deposit_pence,
        "booked_date": payload.date,
        "booked_time": payload.time,
        "created_at": now,
        "updated_at": now,
    }
    await db[mongo.BOOKINGS].insert_one(doc)
    logger.info("Quick booking id=%s user=%s venue=%s", doc["_id"], current_user["_id"], venue.get("name"))
    return {**doc, "id": doc["_id"]}


@router.get("/mine")
async def my_bookings(current_user: dict = Depends(get_current_user)):
    """The current user's bookings, newest first, enriched with venue photo/coords so
    the app can render them as date cards. Includes bookings where I'm the partner."""
    db = mongo.get_db()
    me = current_user["_id"]
    docs = await db[mongo.BOOKINGS].find(
        {"$or": [{"user_id": me}, {"partner_id": me}]}
    ).sort("created_at", -1).to_list(length=100)

    venue_ids = list({b["venue_id"] for b in docs if b.get("venue_id") is not None})
    venues = {v["_id"]: v async for v in db[mongo.VENUES].find({"_id": {"$in": venue_ids}})}

    out = []
    for b in docs:
        v = venues.get(b.get("venue_id")) or {}
        photos = [mongo.photo_url(p) for p in (v.get("photos") or [])]
        out.append({
            **b, "id": b["_id"],
            "venue_name": b.get("venue_name") or v.get("name"),
            "photo_url": photos[0] if photos else None,
            "lat": v.get("lat"), "lng": v.get("lng"),
        })
    return {"count": len(out), "bookings": out}


@router.post("/{booking_id}/confirm", response_model=BookingRead)
async def confirm_booking(booking_id: int, current_user: dict = Depends(get_current_user)):
    """Manually confirm a booking (Stripe webhook does this in production)."""
    db = mongo.get_db()
    booking = await db[mongo.BOOKINGS].find_one({"_id": booking_id})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking["status"] != BookingStatus.pending.value:
        raise HTTPException(status_code=400, detail=f"Booking already {booking['status']}")

    now = datetime.now(timezone.utc)
    booking = await db[mongo.BOOKINGS].find_one_and_update(
        {"_id": booking_id},
        {"$set": {"status": BookingStatus.confirmed.value, "updated_at": now}},
        return_document=True,
    )
    await db[mongo.MATCHES].update_one(
        {"_id": booking["match_id"]},
        {"$set": {"status": MatchStatus.completed.value, "updated_at": now}},
    )
    return _booking_read(booking)


async def _owned_booking(booking_id: int, user_id: int) -> dict:
    """Load a booking the user owns: direct owner, partner, or match participant."""
    db = mongo.get_db()
    booking = await db[mongo.BOOKINGS].find_one({"_id": booking_id})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if user_id in (booking.get("user_id"), booking.get("partner_id")):
        return booking
    if booking.get("match_id"):
        match = await db[mongo.MATCHES].find_one({"_id": booking["match_id"]})
        if match and user_id in (match.get("user_a_id"), match.get("user_b_id")):
            return booking
    raise HTTPException(status_code=403, detail="Not your booking")


def _booking_when(booking: dict) -> Optional[datetime]:
    """The reservation moment, from either a plan slot or booked_date/booked_time."""
    if booking.get("slot"):
        try:
            return datetime.fromisoformat(booking["slot"]).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    if booking.get("booked_date"):
        try:
            t = str(booking.get("booked_time") or "19:00:00")[:5]
            return datetime.fromisoformat(f"{booking['booked_date']}T{t}").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


@router.delete("/{booking_id}")
async def cancel_booking(booking_id: int, current_user: dict = Depends(get_current_user)):
    """Cancel a reservation. Policy: >24h before the table time → full refund."""
    db = mongo.get_db()
    booking = await _owned_booking(booking_id, current_user["_id"])
    if booking.get("status") == BookingStatus.cancelled.value:
        return {"cancelled": True, "refunded": bool(booking.get("refunded"))}

    when = _booking_when(booking)
    refunded = bool(when and (when - datetime.now(timezone.utc)) > timedelta(hours=24))
    await db[mongo.BOOKINGS].update_one(
        {"_id": booking_id},
        {"$set": {"status": BookingStatus.cancelled.value, "refunded": refunded,
                  "cancelled_by": current_user["_id"],
                  "updated_at": datetime.now(timezone.utc)}},
    )
    logger.info("Booking %s cancelled by %s (refunded=%s)",
                booking_id, current_user["_id"], refunded)
    return {"cancelled": True, "refunded": refunded}


class BookingRescheduleRequest(BaseModel):
    date: str   # "2026-07-12"
    time: str   # "19:30:00"


@router.patch("/{booking_id}")
async def reschedule_booking(
    booking_id: int,
    payload: BookingRescheduleRequest,
    current_user: dict = Depends(get_current_user),
):
    """Move a direct table booking to a new date/time (keeps the venue)."""
    db = mongo.get_db()
    booking = await _owned_booking(booking_id, current_user["_id"])
    if booking.get("status") == BookingStatus.cancelled.value:
        raise HTTPException(status_code=409, detail="This booking was cancelled; book again instead.")

    await db[mongo.BOOKINGS].update_one(
        {"_id": booking_id},
        {"$set": {"booked_date": payload.date, "booked_time": payload.time,
                  "status": BookingStatus.confirmed.value,
                  "updated_at": datetime.now(timezone.utc)}},
    )
    logger.info("Booking %s rescheduled to %s %s", booking_id, payload.date, payload.time)
    return {"rescheduled": True, "date": payload.date, "time": payload.time}


@router.get("/{booking_id}", response_model=BookingRead)
async def get_booking(booking_id: int, current_user: dict = Depends(get_current_user)):
    db = mongo.get_db()
    booking = await db[mongo.BOOKINGS].find_one({"_id": booking_id})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    match = await _match_or_404(booking["match_id"])
    _assert_match_member(match, current_user["_id"])
    return _booking_read(booking)


# ── Stripe webhook ────────────────────────────────────────────────────────────

@router.post("/stripe/webhook", include_in_schema=False)
async def stripe_webhook(request: Request):
    """Receives Stripe payment_intent.succeeded events."""
    if stripe is None:
        raise HTTPException(status_code=500, detail="Stripe not installed")
    payload = await request.body()
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
        db = mongo.get_db()
        booking = await db[mongo.BOOKINGS].find_one({"stripe_payment_intent_id": pi_id})
        if booking and booking["status"] == BookingStatus.pending.value:
            now = datetime.now(timezone.utc)
            await db[mongo.BOOKINGS].update_one(
                {"_id": booking["_id"]},
                {"$set": {"status": BookingStatus.confirmed.value, "updated_at": now}},
            )
            await db[mongo.MATCHES].update_one(
                {"_id": booking["match_id"]},
                {"$set": {"status": MatchStatus.completed.value, "updated_at": now}},
            )
            logger.info("Stripe webhook confirmed booking id=%s", booking["_id"])

    return {"received": True}
