from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile, status

from app.core.deps import get_current_user
from app.db import mongo
from app.services import face, geocoding
from app.schemas.profile import (
    AvailabilitySetRequest,
    AvailabilitySlotRead,
    FullProfileRead,
    ProfileRead,
    ProfileSetupRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/profile", tags=["profile"])


# ── Helpers ───────────────────────────────────────────────────────────────────

_REQUIRED_FOR_COMPLETE = [
    "date_of_birth", "gender", "looking_for_gender", "city",
    "home_lat", "home_lng", "relationship_goal", "social_energy",
    "bio", "onboarding_answers",
]


def _compute_profile_complete(doc: dict) -> bool:
    """Profile is complete once the matcher's minimum required fields are set."""
    return all(bool(doc.get(field)) for field in _REQUIRED_FOR_COMPLETE)


def _profile_read(doc: dict) -> ProfileRead:
    data = {**doc, "id": doc["_id"]}
    return ProfileRead.model_validate(data)


def _availability_read(doc: dict) -> AvailabilitySlotRead:
    return AvailabilitySlotRead.model_validate({**doc, "id": doc["_id"]})


async def _get_profile(user_id: int) -> dict | None:
    db = mongo.get_db()
    return await db[mongo.PROFILES].find_one({"user_id": user_id})


async def _get_availability(user_id: int) -> list[dict]:
    db = mongo.get_db()
    cursor = db[mongo.AVAILABILITY].find({"user_id": user_id}).sort(
        [("weekday", 1), ("start_time", 1)]
    )
    return await cursor.to_list(length=None)


# ── GET /profile/me ───────────────────────────────────────────────────────────

@router.get("/me", response_model=FullProfileRead)
async def get_my_profile(current_user: dict = Depends(get_current_user)):
    """Full composite profile. `profile` is null until /profile/setup runs."""
    profile = await _get_profile(current_user["_id"])
    availability = await _get_availability(current_user["_id"])
    photo_urls = [mongo.photo_url(p) for p in ((profile or {}).get("photos") or [])]
    return FullProfileRead(
        id=current_user["_id"],
        email=current_user.get("email"),
        phone=current_user.get("phone"),
        full_name=current_user.get("full_name"),
        role=current_user.get("role", "dater"),
        is_active=current_user.get("is_active", True),
        photos=photo_urls,
        profile=_profile_read(profile) if profile else None,
        availability=[_availability_read(a) for a in availability],
        onboarding=(profile or {}).get("onboarding_raw"),
    )


# ── POST /profile/setup ───────────────────────────────────────────────────────

@router.post("/setup", response_model=ProfileRead, status_code=status.HTTP_200_OK)
async def setup_profile(
    payload: ProfileSetupRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Upsert the extended user profile. Only provided fields are written.
    Sets profile_complete=True once all required fields are present, and syncs
    a few fields back to the user doc for /venues/suggest defaults.
    """
    db = mongo.get_db()
    now = datetime.now(timezone.utc)
    # mode="json" turns date/time/enums into JSON-safe primitives for Mongo
    data = payload.model_dump(exclude_unset=True, mode="json")

    existing = await _get_profile(current_user["_id"])
    if existing is None:
        doc = {
            "_id": await mongo.next_id("user_profiles"),
            "user_id": current_user["_id"],
            "profile_complete": False,
            "created_at": now,
            "updated_at": now,
            **data,
        }
        doc["profile_complete"] = _compute_profile_complete(doc)
        await db[mongo.PROFILES].insert_one(doc)
        logger.info("UserProfile created for user_id=%s", current_user["_id"])
    else:
        merged = {**existing, **data}
        merged["profile_complete"] = _compute_profile_complete(merged)
        merged["updated_at"] = now
        await db[mongo.PROFILES].update_one(
            {"_id": existing["_id"]},
            {"$set": {**data, "profile_complete": merged["profile_complete"], "updated_at": now}},
        )
        doc = merged
        logger.info("UserProfile updated for user_id=%s fields=%s",
                    current_user["_id"], list(data.keys()))

    # ── Sync key fields back to the user doc for suggest defaults ─────────────
    user_sync: dict = {}
    if doc.get("preferred_mood"):
        user_sync["preferred_mood"] = doc["preferred_mood"]
    if doc.get("preferred_budget"):
        user_sync["preferred_budget"] = doc["preferred_budget"]
    if doc.get("relationship_stage_pref"):
        user_sync["preferred_stage"] = doc["relationship_stage_pref"]
    if doc.get("dietary_requirements"):
        user_sync["dietary_requirements"] = doc["dietary_requirements"]
    if user_sync:
        user_sync["updated_at"] = now
        await db[mongo.USERS].update_one({"_id": current_user["_id"]}, {"$set": user_sync})

    return _profile_read(doc)


# ── POST /profile/onboarding ──────────────────────────────────────────────────

@router.post("/onboarding", status_code=status.HTTP_200_OK)
async def submit_onboarding(
    payload: Dict[str, Any] = Body(...),
    current_user: dict = Depends(get_current_user),
):
    """
    Persist the full onboarding answer set as-is. The app collects far more than the
    structured ProfileSetupRequest, so the entire payload is stored under
    `onboarding_raw`; a few safe fields are mapped to typed columns / the user doc.
    """
    db = mongo.get_db()
    now = datetime.now(timezone.utc)

    existing = await _get_profile(current_user["_id"])
    update: dict = {"onboarding_raw": payload, "updated_at": now, "profile_complete": True}

    # Map a few safe, free-text fields (no enum validation) so they show on the profile.
    loc = payload.get("location") if isinstance(payload.get("location"), dict) else {}
    if loc.get("city"):
        update["city"] = loc["city"]
    if payload.get("date_of_birth"):
        update["date_of_birth"] = payload["date_of_birth"]

    # Geocode the user's location to real coordinates (postcode preferred) so distance-based
    # matching and venue travel-times work. Cached + graceful (no-op without a Mapbox token).
    place = loc.get("postcode") or loc.get("city")
    if place:
        geo = await geocoding.geocode(place)
        if geo:
            update["lat"], update["lng"], update["geo_name"] = geo

    if existing is None:
        doc = {
            "_id": await mongo.next_id("user_profiles"),
            "user_id": current_user["_id"],
            "created_at": now,
            **update,
        }
        await db[mongo.PROFILES].insert_one(doc)
    else:
        # Drop the cached intent vector so matching recomputes from the new answers.
        await db[mongo.PROFILES].update_one(
            {"_id": existing["_id"]},
            {"$set": update, "$unset": {"intent_vector": "", "intent_updated_at": ""}},
        )

    # Sync display name to the user record.
    if payload.get("first_name"):
        await db[mongo.USERS].update_one(
            {"_id": current_user["_id"]},
            {"$set": {"full_name": payload["first_name"], "updated_at": now}},
        )

    logger.info("Onboarding stored for user_id=%s (%d keys)", current_user["_id"], len(payload))
    return {"stored": True, "fields": len(payload)}


# ── POST /profile/availability ────────────────────────────────────────────────

@router.post("/availability", response_model=List[AvailabilitySlotRead])
async def set_availability(
    payload: AvailabilitySetRequest,
    current_user: dict = Depends(get_current_user),
):
    """Full-replace the user's weekly availability."""
    seen: set[tuple] = set()
    for slot in payload.slots:
        key = (slot.weekday, slot.start_time)
        if key in seen:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Duplicate availability slot: weekday={slot.weekday} start_time={slot.start_time}",
            )
        seen.add(key)

    db = mongo.get_db()
    await db[mongo.AVAILABILITY].delete_many({"user_id": current_user["_id"]})

    now = datetime.now(timezone.utc)
    docs = []
    for s in payload.slots:
        docs.append({
            "_id": await mongo.next_id("user_availability"),
            "user_id": current_user["_id"],
            "weekday": s.weekday,
            "start_time": s.start_time.isoformat(),
            "end_time": s.end_time.isoformat(),
            "created_at": now,
            "updated_at": now,
        })
    if docs:
        await db[mongo.AVAILABILITY].insert_many(docs)

    logger.info("Availability set for user_id=%s: %d slots", current_user["_id"], len(docs))
    return [_availability_read(d) for d in docs]


# ── GET /profile/availability ─────────────────────────────────────────────────

@router.get("/availability", response_model=List[AvailabilitySlotRead])
async def get_availability(current_user: dict = Depends(get_current_user)):
    slots = await _get_availability(current_user["_id"])
    return [_availability_read(s) for s in slots]


# ── Account self-service (pause / resume / delete) ────────────────────────────

@router.post("/pause")
async def pause_account(current_user: dict = Depends(get_current_user)):
    """Hide the profile from discovery without deleting it. Reversible via /resume.

    Uses a dedicated `paused` flag (NOT is_active) so the user can still sign in and
    un-pause — is_active is reserved for account deletion / bans.
    """
    await mongo.get_db()[mongo.USERS].update_one(
        {"_id": current_user["_id"]},
        {"$set": {"paused": True, "updated_at": datetime.now(timezone.utc)}},
    )
    return {"paused": True}


@router.post("/resume")
async def resume_account(current_user: dict = Depends(get_current_user)):
    await mongo.get_db()[mongo.USERS].update_one(
        {"_id": current_user["_id"]},
        {"$set": {"paused": False, "updated_at": datetime.now(timezone.utc)}},
    )
    return {"paused": False}


@router.delete("/me", status_code=200)
async def delete_my_account(current_user: dict = Depends(get_current_user)):
    """Permanently delete the account and everything attached to it."""
    db = mongo.get_db()
    me = current_user["_id"]

    profile = await db[mongo.PROFILES].find_one({"user_id": me})
    for pid in (profile or {}).get("photos") or []:
        try:
            from bson import ObjectId
            await mongo.gridfs().delete(ObjectId(pid))
        except Exception:
            pass

    await db[mongo.PROFILES].delete_many({"user_id": me})
    await db[mongo.AVAILABILITY].delete_many({"user_id": me})
    await db[mongo.LIKES].delete_many({"$or": [{"from_user_id": me}, {"to_user_id": me}]})
    await db[mongo.CONNECTIONS].delete_many({"$or": [{"user_a_id": me}, {"user_b_id": me}]})
    await db["tonight_optins"].delete_many({"user_id": me})
    await db[mongo.USERS].delete_one({"_id": me})
    logger.info("Account deleted for user_id=%s", me)
    return {"deleted": True}


# ── Profile verification (selfie analysis) ────────────────────────────────────

@router.get("/verification")
async def verification_status(current_user: dict = Depends(get_current_user)):
    """Where the current user is in verification: none / pending / verified / rejected."""
    db = mongo.get_db()
    u = await db[mongo.USERS].find_one({"_id": current_user["_id"]}) or {}
    return {
        "verified": bool(u.get("verified")),
        "status": u.get("verification_status") or ("verified" if u.get("verified") else "none"),
        "reason": u.get("verification_reason"),
    }


@router.post("/verify")
async def submit_verification(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """Submit a selfie for verification.

    The backend analyses the selfie (one clear, front-facing face) and, on a pass, grants the
    verified badge immediately. If OpenCV isn't available at runtime the selfie is stored and
    the account is marked `pending` for manual review in the admin tool.
    """
    db = mongo.get_db()
    me = current_user["_id"]
    data = await file.read()
    if not data:
        raise HTTPException(422, "Empty file")
    if len(data) > 12 * 1024 * 1024:
        raise HTTPException(413, "Selfie too large (max 12MB)")

    result = face.analyse_selfie(data)

    # Keep the selfie for audit / manual review (not shown on the public profile).
    now = datetime.now(timezone.utc)
    selfie_id = await mongo.gridfs().upload_from_stream(
        f"selfie_{me}.jpg", data,
        metadata={"user_id": me, "kind": "verification_selfie",
                  "content_type": file.content_type or "image/jpeg", "created_at": now})

    if not result.available:
        # No analyser available → queue for manual review rather than guess.
        update = {"verification_status": "pending", "verification_selfie": selfie_id,
                  "verification_reason": None, "verified": False, "updated_at": now}
        await db[mongo.USERS].update_one({"_id": me}, {"$set": update})
        return {"verified": False, "status": "pending",
                "message": "Thanks! Your selfie is in review and your badge will appear soon."}

    if result.ok:
        update = {"verified": True, "verification_status": "verified",
                  "verification_selfie": selfie_id, "verification_reason": None,
                  "verified_at": now, "updated_at": now}
        await db[mongo.USERS].update_one({"_id": me}, {"$set": update})
        logger.info("User %s verified via selfie", me)
        return {"verified": True, "status": "verified",
                "message": "You're verified! The badge now shows on your profile."}

    update = {"verified": False, "verification_status": "rejected",
              "verification_selfie": selfie_id, "verification_reason": result.reason,
              "updated_at": now}
    await db[mongo.USERS].update_one({"_id": me}, {"$set": update})
    return {"verified": False, "status": "rejected", "message": result.reason}
