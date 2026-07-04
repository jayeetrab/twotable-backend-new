"""
Date-plan coordination — two matched users agree on a time and a restaurant, then
both pay, entirely asynchronously (no chat).

State machine (a `date_plans` doc per matched pair):

    proposing_time → choosing_venue → venue_agreed → confirmed
                       (both submit       (both pick     (both pay →
                        slots, overlap      venues,        booking
                        picks the slot)     overlap)       created)

The clever bit: agreement is set intersection, computed server-side. Each person
just taps the times / restaurants that work for them; where they overlap, the plan
advances. The restaurant shortlist is generated from the fair meeting-point engine
(midpoint + travel time for the agreed slot), so the 5 options are already optimal.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

from app.api.v1.discovery import _card
from app.core.deps import get_current_user
from app.db import mongo
from app.services import events, meeting, routing
from app.services.geo import haversine_km

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dates", tags=["dates"])

PLANS = "date_plans"


# ── helpers ───────────────────────────────────────────────────────────────────

def _is_peak(slot: str) -> bool:
    """Peak = Friday/Saturday dinner slots (>= 18:00). Accepts ISO or a loose label."""
    try:
        dt = datetime.fromisoformat(slot)
        return dt.weekday() in (4, 5) and dt.hour >= 18
    except Exception:
        s = (slot or "").lower()
        has_eve = any(h in s for h in ["18", "19", "20", "21", "22", "23"])
        return ("fri" in s or "sat" in s) and has_eve


def _price(is_peak: Optional[bool]) -> int:
    return 8 if is_peak else 6


def _side(plan: dict, me: int) -> str:
    return "a" if plan["user_a_id"] == me else "b"


def _venue_card(v: dict, eta_min: Optional[float] = None) -> dict:
    photos = [mongo.photo_url(p) for p in (v.get("photos") or [])]
    return {"id": v["_id"], "name": v.get("name"), "cuisine": v.get("cuisine"),
            "price_band": v.get("price_band"), "lat": v.get("lat"), "lng": v.get("lng"),
            "photo_url": photos[0] if photos else None,
            "eta_min": eta_min}   # this viewer's estimated drive time, when known


async def _state(plan: dict, me: int) -> dict:
    """Full client-facing view of a plan from `me`'s perspective."""
    db = mongo.get_db()
    side = _side(plan, me)
    other_id = plan["user_b_id"] if side == "a" else plan["user_a_id"]
    other_user = await db[mongo.USERS].find_one({"_id": other_id})
    other_prof = await db[mongo.PROFILES].find_one({"user_id": other_id})

    my_slots = set(plan.get(f"slots_{side}") or [])
    their_slots = set(plan.get(f"slots_{'b' if side == 'a' else 'a'}") or [])
    my_picks = plan.get(f"picks_{side}") or []
    their_picks = plan.get(f"picks_{'b' if side == 'a' else 'a'}") or []

    opt_ids = plan.get("venue_options") or []
    opt_docs = {v["_id"]: v async for v in db[mongo.VENUES].find({"_id": {"$in": opt_ids}})}
    agreed_venue = opt_docs.get(plan.get("agreed_venue_id"))
    if plan.get("agreed_venue_id") and not agreed_venue:
        agreed_venue = await db[mongo.VENUES].find_one({"_id": plan["agreed_venue_id"]})

    # This viewer's drive time to each option ("we play on time"): cache-first, so it's a
    # Mapbox matrix call at most once per hour bucket, and instant on the estimate fallback.
    my_prof = await db[mongo.PROFILES].find_one({"user_id": me}) or {}
    etas: dict[int, float] = {}
    if my_prof.get("lat") is not None and my_prof.get("lng") is not None:
        coords = [(i, (opt_docs[i]["lat"], opt_docs[i]["lng"]))
                  for i in opt_ids
                  if i in opt_docs and opt_docs[i].get("lat") is not None]
        if coords:
            mins = await routing.travel_matrix(
                (my_prof["lat"], my_prof["lng"]), [c for _, c in coords], "drive")
            etas = {i: round(m, 0) for (i, _), m in zip(coords, mins) if m is not None}

    return {
        "id": plan["_id"],
        "status": plan["status"],
        "with": _card(other_user, other_prof) if other_user else None,
        "my_slots": sorted(my_slots),
        "their_slots": sorted(their_slots),
        "overlap_slots": sorted(my_slots & their_slots),
        "agreed_slot": plan.get("agreed_slot"),
        "is_peak": plan.get("is_peak"),
        "price": _price(plan.get("is_peak")),
        "venue_options": [_venue_card(opt_docs[i], etas.get(i)) for i in opt_ids if i in opt_docs],
        "my_picks": my_picks,
        "their_picks": their_picks,
        "agreed_venue": _venue_card(agreed_venue) if agreed_venue else None,
        "i_paid": plan.get(f"paid_{side}", False),
        "they_paid": plan.get(f"paid_{'b' if side == 'a' else 'a'}", False),
    }


async def _generate_venue_options(plan: dict) -> list[int]:
    """5 restaurant options for the pair: fair meeting-point ranked, midpoint + travel."""
    db = mongo.get_db()
    pa = await db[mongo.PROFILES].find_one({"user_id": plan["user_a_id"]}) or {}
    pb = await db[mongo.PROFILES].find_one({"user_id": plan["user_b_id"]}) or {}

    def coord(p):
        return (p["lat"], p["lng"]) if p.get("lat") is not None and p.get("lng") is not None else None

    a, b = coord(pa), coord(pb)
    city = pa.get("city") or pb.get("city") or "Bristol"
    venues = await db[mongo.VENUES].find(
        {"city": {"$regex": city, "$options": "i"}, "is_active": True,
         "lat": {"$ne": None}, "lng": {"$ne": None}},
        {"name": 1, "cuisine": 1, "price_band": 1, "lat": 1, "lng": 1, "photos": 1},
    ).to_list(length=400)
    if not venues:
        return []

    if a and b:
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        # Nearest to the pair's midpoint, preferring venues with photos so the
        # shortlist the app renders always looks good.
        venues.sort(key=lambda v: (0 if v.get("photos") else 1,
                                   haversine_km(mid[0], mid[1], v["lat"], v["lng"])))
        depart = None
        try:
            depart = datetime.fromisoformat(plan["agreed_slot"])
        except Exception:
            pass
        # Product rule: the meeting point must be at most 45 minutes' commute for BOTH.
        ranked = await meeting.fair_meeting_venues(a, "drive", b, "drive", venues[:24], depart, 45, 5)
        ids = [r["venue_id"] for r in ranked]
        if ids:
            return ids
    # Fallback (no coords / no token): 5 nearby venues, preferring ones with photos.
    venues.sort(key=lambda v: 0 if v.get("photos") else 1)
    return [v["_id"] for v in venues[:5]]


# ── endpoints ─────────────────────────────────────────────────────────────────

class StartRequest(BaseModel):
    with_user_id: int


@router.post("")
async def start_or_get(req: StartRequest, current_user: dict = Depends(get_current_user)):
    """Open (or fetch) the date plan with a matched user. Requires a mutual connection."""
    db = mongo.get_db()
    me = current_user["_id"]
    a, b = sorted((me, req.with_user_id))
    if not await db[mongo.CONNECTIONS].find_one({"user_a_id": a, "user_b_id": b}):
        raise HTTPException(403, "You can only plan a date with someone you've matched with.")

    plan = await db[PLANS].find_one({"user_a_id": a, "user_b_id": b})
    if not plan:
        now = datetime.now(timezone.utc)
        plan = {"_id": await mongo.next_id("date_plans"), "user_a_id": a, "user_b_id": b,
                "status": "proposing_time", "slots_a": [], "slots_b": [],
                "agreed_slot": None, "is_peak": None, "venue_options": [],
                "picks_a": [], "picks_b": [], "agreed_venue_id": None,
                "paid_a": False, "paid_b": False, "created_at": now, "updated_at": now}
        await db[PLANS].insert_one(plan)
    return await _state(plan, me)


@router.get("")
async def my_dates(current_user: dict = Depends(get_current_user)):
    db = mongo.get_db()
    me = current_user["_id"]
    plans = [p async for p in db[PLANS].find(
        {"$or": [{"user_a_id": me}, {"user_b_id": me}], "status": {"$ne": "cancelled"}})]
    return {"count": len(plans), "dates": [await _state(p, me) for p in plans]}


async def _load(plan_id: int, me: int) -> dict:
    plan = await mongo.get_db()[PLANS].find_one({"_id": plan_id})
    if not plan or me not in (plan["user_a_id"], plan["user_b_id"]):
        raise HTTPException(404, "Date plan not found")
    return plan


@router.get("/{plan_id}")
async def get_date(plan_id: int, current_user: dict = Depends(get_current_user)):
    return await _state(await _load(plan_id, current_user["_id"]), current_user["_id"])


@router.put("/{plan_id}/slots")
async def submit_slots(plan_id: int, slots: list[str] = Body(..., embed=True),
                       current_user: dict = Depends(get_current_user)):
    """Submit the times that work for me. When both sides overlap, the slot is locked
    and the restaurant shortlist is generated."""
    db = mongo.get_db()
    me = current_user["_id"]
    plan = await _load(plan_id, me)
    side = _side(plan, me)
    other = "b" if side == "a" else "a"

    update = {f"slots_{side}": slots, "updated_at": datetime.now(timezone.utc)}
    plan[f"slots_{side}"] = slots
    overlap = sorted(set(slots) & set(plan.get(f"slots_{other}") or []))
    if overlap:
        agreed = overlap[0]
        update.update({"agreed_slot": agreed, "is_peak": _is_peak(agreed)})
        # Where the plan goes next depends on what already exists (reschedule keeps the
        # venue and payments, so re-agreeing a time jumps straight back to confirmed).
        if plan.get("agreed_venue_id") and plan.get("paid_a") and plan.get("paid_b"):
            update["status"] = "confirmed"
            if plan.get("booking_id"):
                await db[mongo.BOOKINGS].update_one(
                    {"_id": plan["booking_id"]},
                    {"$set": {"status": "confirmed", "slot": agreed,
                              "is_peak": _is_peak(agreed), "price": _price(_is_peak(agreed))}})
        elif plan.get("agreed_venue_id"):
            update["status"] = "venue_agreed"
        else:
            update["status"] = "choosing_venue"
            plan.update(update)
            plan["venue_options"] = update["venue_options"] = await _generate_venue_options(plan)
    else:
        update["status"] = "proposing_time"
    await db[PLANS].update_one({"_id": plan_id}, {"$set": update})
    plan.update(update)
    return await _state(plan, me)


@router.put("/{plan_id}/venue-picks")
async def submit_venue_picks(plan_id: int, venue_ids: list[int] = Body(..., embed=True),
                             current_user: dict = Depends(get_current_user)):
    """Pick my preferred restaurants from the shortlist. Overlap = the agreed venue."""
    db = mongo.get_db()
    me = current_user["_id"]
    plan = await _load(plan_id, me)
    if plan["status"] not in ("choosing_venue", "venue_agreed"):
        raise HTTPException(409, "Agree a time before picking the restaurant.")
    side = _side(plan, me)
    other = "b" if side == "a" else "a"
    valid = [v for v in venue_ids if v in (plan.get("venue_options") or [])][:3]

    update = {f"picks_{side}": valid, "updated_at": datetime.now(timezone.utc)}
    plan[f"picks_{side}"] = valid
    # First option (highest-ranked) that both picked becomes the venue.
    common = [v for v in (plan.get("venue_options") or [])
              if v in valid and v in (plan.get(f"picks_{other}") or [])]
    if common:
        update.update({"agreed_venue_id": common[0], "status": "venue_agreed"})
    await db[PLANS].update_one({"_id": plan_id}, {"$set": update})
    plan.update(update)
    return await _state(plan, me)


@router.post("/{plan_id}/pay")
async def pay(plan_id: int, current_user: dict = Depends(get_current_user)):
    """Mark my share paid (£6 off-peak / £8 peak). When both pay, the booking is created."""
    db = mongo.get_db()
    me = current_user["_id"]
    plan = await _load(plan_id, me)
    if not plan.get("agreed_venue_id"):
        raise HTTPException(409, "Agree a restaurant before paying.")
    side = _side(plan, me)
    now = datetime.now(timezone.utc)
    await db[PLANS].update_one({"_id": plan_id}, {"$set": {f"paid_{side}": True, "updated_at": now}})
    plan[f"paid_{side}"] = True
    await events.log_event("booked", me, target_id=(plan["user_b_id"] if side == "a" else plan["user_a_id"]),
                           venue_id=plan["agreed_venue_id"])

    if plan.get("paid_a") and plan.get("paid_b") and plan["status"] != "confirmed":
        booking = {"_id": await mongo.next_id("bookings"),
                   "user_id": plan["user_a_id"], "partner_id": plan["user_b_id"],
                   "venue_id": plan["agreed_venue_id"], "slot": plan.get("agreed_slot"),
                   "is_peak": plan.get("is_peak"), "price": _price(plan.get("is_peak")),
                   "status": "confirmed", "date_plan_id": plan["_id"], "created_at": now}
        await db[mongo.BOOKINGS].insert_one(booking)
        await db[PLANS].update_one({"_id": plan_id}, {"$set": {"status": "confirmed", "booking_id": booking["_id"]}})
        plan["status"] = "confirmed"
        logger.info("Date confirmed: plan %s → booking %s", plan_id, booking["_id"])

    return await _state(plan, me)


def _slot_dt(plan: dict) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(plan["agreed_slot"]).replace(tzinfo=timezone.utc)
    except Exception:
        return None


@router.delete("/{plan_id}")
async def cancel(plan_id: int, current_user: dict = Depends(get_current_user)):
    """Cancel a plan or a confirmed reservation.

    Refund policy (matches the in-app fine print): a paid, confirmed date cancelled
    more than 24 hours before the slot is refunded in full; later than that it isn't.
    """
    db = mongo.get_db()
    me = current_user["_id"]
    plan = await _load(plan_id, me)
    if plan["status"] == "cancelled":
        return {"cancelled": True, "refunded": bool(plan.get("refunded"))}

    paid = plan.get("paid_a") or plan.get("paid_b")
    slot = _slot_dt(plan)
    refunded = bool(paid and slot and (slot - datetime.now(timezone.utc)) > timedelta(hours=24))

    now = datetime.now(timezone.utc)
    await db[PLANS].update_one(
        {"_id": plan_id},
        {"$set": {"status": "cancelled", "cancelled_by": me, "refunded": refunded,
                  "updated_at": now}})
    if plan.get("booking_id"):
        await db[mongo.BOOKINGS].update_one(
            {"_id": plan["booking_id"]}, {"$set": {"status": "cancelled", "refunded": refunded}})
    other = plan["user_b_id"] if _side(plan, me) == "a" else plan["user_a_id"]
    await events.log_event("cancelled", me, target_id=other, venue_id=plan.get("agreed_venue_id"))
    logger.info("Plan %s cancelled by %s (refunded=%s)", plan_id, me, refunded)
    return {"cancelled": True, "refunded": refunded}


@router.post("/{plan_id}/reschedule")
async def reschedule(plan_id: int, current_user: dict = Depends(get_current_user)):
    """Re-open time coordination: keeps the venue and any payments, clears the slot.

    Both people re-propose times through the normal flow; the plan (and booking) update
    to the newly agreed slot when they overlap again.
    """
    db = mongo.get_db()
    me = current_user["_id"]
    plan = await _load(plan_id, me)
    if plan["status"] == "cancelled":
        raise HTTPException(409, "This date was cancelled; start a new plan instead.")

    now = datetime.now(timezone.utc)
    await db[PLANS].update_one(
        {"_id": plan_id},
        {"$set": {"status": "proposing_time", "slots_a": [], "slots_b": [],
                  "agreed_slot": None, "is_peak": None,
                  "rescheduled_by": me, "updated_at": now}})
    if plan.get("booking_id"):
        await db[mongo.BOOKINGS].update_one(
            {"_id": plan["booking_id"]}, {"$set": {"status": "rescheduling", "slot": None}})
    plan.update({"status": "proposing_time", "slots_a": [], "slots_b": [],
                 "agreed_slot": None, "is_peak": None})
    return await _state(plan, me)


class RateRequest(BaseModel):
    score: int  # 1..5


@router.post("/{plan_id}/rate")
async def rate(plan_id: int, req: RateRequest, current_user: dict = Depends(get_current_user)):
    """Post-date rating. Feeds the outcome funnel the matcher learns from
    (attended → rated → rematch-worthy)."""
    if not 1 <= req.score <= 5:
        raise HTTPException(422, "score must be 1-5")
    db = mongo.get_db()
    me = current_user["_id"]
    plan = await _load(plan_id, me)
    if plan["status"] != "confirmed":
        raise HTTPException(409, "Only confirmed dates can be rated.")

    side = _side(plan, me)
    other = plan["user_b_id"] if side == "a" else plan["user_a_id"]
    await db[PLANS].update_one(
        {"_id": plan_id},
        {"$set": {f"rating_{side}": req.score, "updated_at": datetime.now(timezone.utc)}})
    await events.log_event("attended", me, target_id=other, venue_id=plan.get("agreed_venue_id"))
    await events.log_event("rated", me, target_id=other, venue_id=plan.get("agreed_venue_id"),
                           meta={"score": req.score})
    return {"rated": True, "score": req.score}
