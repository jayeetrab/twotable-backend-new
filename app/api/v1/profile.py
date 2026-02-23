from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.user_availability import UserAvailability
from app.models.user_profile import UserProfile
from app.schemas.profile import (
    AvailabilitySetRequest,
    AvailabilitySlotRead,
    FullProfileRead,
    ProfileRead,
    ProfileSetupRequest,
    SocialConnectionRead,
    SocialSignalRead,
    SocialConnectRequest,
)
from app.models.user_social_connection import UserSocialConnection, SocialPlatform
from app.models.user_social_signal import UserSocialSignal
from app.services.social.pipeline import run_instagram_pipeline, run_spotify_pipeline


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/profile", tags=["profile"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _compute_profile_complete(p: UserProfile) -> bool:
    """
    Profile is considered complete when the minimum required fields are set.
    This flag is used by the matching engine (Stage A hard filter).
    """
    return all([
        p.date_of_birth is not None,
        p.gender is not None,
        bool(p.looking_for_gender),
        bool(p.city),
        p.home_lat is not None,
        p.home_lng is not None,
        p.relationship_goal is not None,
        p.social_energy is not None,
        bool(p.bio),
        bool(p.onboarding_answers),
    ])


async def _get_profile(db: AsyncSession, user_id: int) -> UserProfile | None:
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def _get_availability(db: AsyncSession, user_id: int) -> list[UserAvailability]:
    result = await db.execute(
        select(UserAvailability)
        .where(UserAvailability.user_id == user_id)
        .order_by(UserAvailability.weekday, UserAvailability.start_time)
    )
    return list(result.scalars().all())


# ── GET /profile/me ───────────────────────────────────────────────────────────

@router.get("/me", response_model=FullProfileRead)
async def get_my_profile(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return the full composite profile for the authenticated user.
    `profile` is null if the user has not yet run /profile/setup.
    `availability` is an empty list until /profile/availability is called.
    """
    profile      = await _get_profile(db, current_user.id)
    availability = await _get_availability(db, current_user.id)

    return FullProfileRead(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role.value,
        is_active=current_user.is_active,
        profile=ProfileRead.model_validate(profile) if profile else None,
        availability=[AvailabilitySlotRead.model_validate(a) for a in availability],
    )


# ── POST /profile/setup ───────────────────────────────────────────────────────

@router.post("/setup", response_model=ProfileRead, status_code=status.HTTP_200_OK)
async def setup_profile(
    payload: ProfileSetupRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create or update the extended user profile (upsert).
    Only provided fields are written — omitted fields are left unchanged.
    Sets profile_complete=True when all required fields are present.

    Also syncs preferred_mood, preferred_budget, preferred_stage,
    dietary_requirements back to the users table so that /venues/suggest
    continues to work with user defaults.
    """
    profile = await _get_profile(db, current_user.id)
    data    = payload.model_dump(exclude_unset=True)

    # Flatten onboarding_answers from Pydantic model → plain dict for JSONB
    if "onboarding_answers" in data and data["onboarding_answers"] is not None:
        data["onboarding_answers"] = payload.onboarding_answers.model_dump(exclude_none=True)

    if profile is None:
        profile = UserProfile(user_id=current_user.id, **data)
        db.add(profile)
        logger.info("UserProfile created for user_id=%d", current_user.id)
    else:
        for field, value in data.items():
            setattr(profile, field, value)
        profile.updated_at = datetime.now(timezone.utc)
        logger.info("UserProfile updated for user_id=%d fields=%s", current_user.id, list(data.keys()))

    # Compute completeness after applying updates
    profile.profile_complete = _compute_profile_complete(profile)

    # ── Sync key fields back to User for /venues/suggest compat ──────────────
    if profile.preferred_mood:
        current_user.preferred_mood = profile.preferred_mood
    if profile.preferred_budget:
        current_user.preferred_budget = profile.preferred_budget
    if profile.relationship_stage_pref:
        current_user.preferred_stage = profile.relationship_stage_pref.value
    if profile.dietary_requirements:
        current_user.dietary_requirements = profile.dietary_requirements
    current_user.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(profile)
    return profile


# ── POST /profile/availability ────────────────────────────────────────────────

@router.post(
    "/availability",
    response_model=List[AvailabilitySlotRead],
    status_code=status.HTTP_200_OK,
)
async def set_availability(
    payload: AvailabilitySetRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Full-replace the user's weekly availability.
    Deletes all existing slots, then inserts the provided set.
    Supply up to 21 windows (e.g. 3 per day across 7 days).
    """
    # Validate no duplicate (weekday, start_time) pairs within the payload
    seen: set[tuple] = set()
    for slot in payload.slots:
        key = (slot.weekday, slot.start_time)
        if key in seen:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Duplicate availability slot: weekday={slot.weekday} start_time={slot.start_time}",
            )
        seen.add(key)

    # Delete existing slots
    await db.execute(
        delete(UserAvailability).where(UserAvailability.user_id == current_user.id)
    )

    # Insert new slots
    new_slots: list[UserAvailability] = []
    for s in payload.slots:
        slot = UserAvailability(
            user_id=current_user.id,
            weekday=s.weekday,
            start_time=s.start_time,
            end_time=s.end_time,
        )
        db.add(slot)
        new_slots.append(slot)

    await db.commit()

    # Refresh all to get DB-assigned IDs
    for slot in new_slots:
        await db.refresh(slot)

    logger.info(
        "Availability set for user_id=%d: %d slots",
        current_user.id, len(new_slots),
    )
    return new_slots


# ── GET /profile/availability ─────────────────────────────────────────────────

@router.get("/availability", response_model=List[AvailabilitySlotRead])
async def get_availability(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the current user's weekly availability slots."""
    slots = await _get_availability(db, current_user.id)
    return slots
# ── GET /profile/social ───────────────────────────────────────────────────────

@router.get("/social/connections", response_model=List[SocialConnectionRead])
async def get_social_connections(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all connected social platforms for the current user."""
    result = await db.execute(
        select(UserSocialConnection).where(
            UserSocialConnection.user_id == current_user.id,
            UserSocialConnection.is_active == True,  # noqa: E712
        )
    )
    return result.scalars().all()


@router.get("/social/signals", response_model=List[SocialSignalRead])
async def get_social_signals(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all extracted social signals for the current user."""
    result = await db.execute(
        select(UserSocialSignal)
        .where(UserSocialSignal.user_id == current_user.id)
        .order_by(UserSocialSignal.platform, UserSocialSignal.signal_type)
    )
    return result.scalars().all()


# ── POST /profile/connect/instagram ──────────────────────────────────────────

@router.post("/connect/instagram", status_code=status.HTTP_200_OK)
async def connect_instagram(
    payload: SocialConnectRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Save Instagram OAuth tokens and immediately run the analysis pipeline.

    In production: your frontend handles the Instagram OAuth redirect,
    receives the access_token, and posts it here.

    Instagram Basic Display API OAuth flow:
    1. Redirect user to:
       https://api.instagram.com/oauth/authorize
         ?client_id={INSTAGRAM_APP_ID}
         &redirect_uri={REDIRECT_URI}
         &scope=user_profile,user_media
         &response_type=code
    2. Instagram redirects back with ?code=...
    3. Exchange code for access_token via POST to:
       https://api.instagram.com/oauth/access_token
    4. POST that access_token to this endpoint.
    """
    # Upsert the connection record
    result = await db.execute(
        select(UserSocialConnection).where(
            UserSocialConnection.user_id == current_user.id,
            UserSocialConnection.platform == SocialPlatform.instagram,
        )
    )
    conn = result.scalar_one_or_none()
    if conn:
        conn.access_token        = payload.access_token
        conn.platform_user_id    = payload.platform_user_id
        conn.platform_username   = payload.platform_username
        conn.is_active           = True
        conn.connected_at        = datetime.now(timezone.utc)
    else:
        conn = UserSocialConnection(
            user_id=current_user.id,
            platform=SocialPlatform.instagram,
            access_token=payload.access_token,
            platform_user_id=payload.platform_user_id,
            platform_username=payload.platform_username,
        )
        db.add(conn)
    await db.commit()

    # Run pipeline immediately (in prod, offload to background task / Celery)
    result = await run_instagram_pipeline(
        user_id=current_user.id,
        access_token=payload.access_token,
        db=db,
    )
    logger.info(
        "Instagram connected for user_id=%d: %d signals",
        current_user.id, result["signals_saved"],
    )
    return {
        "platform": "instagram",
        "connected": True,
        "signals_extracted": result["signals_saved"],
    }


# ── POST /profile/connect/spotify ────────────────────────────────────────────

@router.post("/connect/spotify", status_code=status.HTTP_200_OK)
async def connect_spotify(
    payload: SocialConnectRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Save Spotify OAuth tokens and immediately run the analysis pipeline.

    Spotify OAuth flow:
    1. Redirect user to:
       https://accounts.spotify.com/authorize
         ?client_id={SPOTIFY_CLIENT_ID}
         &redirect_uri={REDIRECT_URI}
         &scope=user-top-read user-read-recently-played
         &response_type=code
    2. Spotify redirects back with ?code=...
    3. Exchange code for access_token + refresh_token via POST to:
       https://accounts.spotify.com/api/token
    4. POST access_token here.
    """
    result = await db.execute(
        select(UserSocialConnection).where(
            UserSocialConnection.user_id == current_user.id,
            UserSocialConnection.platform == SocialPlatform.spotify,
        )
    )
    conn = result.scalar_one_or_none()
    if conn:
        conn.access_token       = payload.access_token
        conn.refresh_token      = payload.refresh_token
        conn.platform_user_id   = payload.platform_user_id
        conn.platform_username  = payload.platform_username
        conn.is_active          = True
        conn.connected_at       = datetime.now(timezone.utc)
    else:
        conn = UserSocialConnection(
            user_id=current_user.id,
            platform=SocialPlatform.spotify,
            access_token=payload.access_token,
            refresh_token=payload.refresh_token,
            platform_user_id=payload.platform_user_id,
            platform_username=payload.platform_username,
        )
        db.add(conn)
    await db.commit()

    result = await run_spotify_pipeline(
        user_id=current_user.id,
        access_token=payload.access_token,
        db=db,
    )
    logger.info(
        "Spotify connected for user_id=%d: %d signals",
        current_user.id, result["signals_saved"],
    )
    return {
        "platform": "spotify",
        "connected": True,
        "signals_extracted": result["signals_saved"],
    }


# ── POST /profile/social/resync ───────────────────────────────────────────────

@router.post("/social/resync/{platform}", status_code=status.HTTP_200_OK)
async def resync_social(
    platform: SocialPlatform,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Re-run the analysis pipeline for an already-connected platform."""
    result = await db.execute(
        select(UserSocialConnection).where(
            UserSocialConnection.user_id == current_user.id,
            UserSocialConnection.platform == platform,
            UserSocialConnection.is_active == True,  # noqa: E712
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(
            status_code=404,
            detail=f"{platform.value} is not connected. Call /connect/{platform.value} first.",
        )
    if not conn.access_token:
        raise HTTPException(status_code=400, detail="No access token stored for this platform.")

    if platform == SocialPlatform.instagram:
        run_result = await run_instagram_pipeline(
            user_id=current_user.id,
            access_token=conn.access_token,
            db=db,
        )
    else:
        run_result = await run_spotify_pipeline(
            user_id=current_user.id,
            access_token=conn.access_token,
            db=db,
        )

    return {
        "platform": platform.value,
        "resynced": True,
        "signals_extracted": run_result["signals_saved"],
    }
