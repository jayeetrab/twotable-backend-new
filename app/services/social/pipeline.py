from __future__ import annotations

"""
Orchestrates the full social analysis pipeline for a single user.
Called after OAuth connection is saved.

Usage:
    await run_instagram_pipeline(user_id=1, access_token="...", db=db)
    await run_spotify_pipeline(user_id=1, access_token="...", db=db)
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user_social_connection import UserSocialConnection, SocialPlatform
from app.models.user_social_signal import UserSocialSignal
from app.services.social.instagram import (
    analyse_instagram_captions_with_groq,
    analyse_instagram_images_with_groq,
    build_instagram_signals,
    fetch_instagram_media,
    fetch_instagram_profile,
)
from app.services.social.spotify import (
    build_spotify_signals,
    derive_audio_signals,
    fetch_audio_features,
    fetch_top_artists,
    fetch_top_tracks,
)

logger = logging.getLogger(__name__)


async def _save_signals(
    db: AsyncSession,
    user_id: int,
    platform: str,
    signals: list[dict],
) -> int:
    """
    Full-replace all signals for this user + platform, then insert new ones.
    Returns count of signals saved.
    """
    # Delete existing signals for this platform
    await db.execute(
        delete(UserSocialSignal).where(
            UserSocialSignal.user_id == user_id,
            UserSocialSignal.platform == platform,
        )
    )
    # Insert new signals
    for s in signals:
        db.add(UserSocialSignal(
            user_id=user_id,
            platform=s["platform"],
            signal_type=s["signal_type"],
            signal_value=s["signal_value"],
            confidence=s.get("confidence"),
            extracted_at=datetime.now(timezone.utc),
        ))
    await db.commit()
    return len(signals)


async def _update_connection_synced(
    db: AsyncSession,
    user_id: int,
    platform: SocialPlatform,
) -> None:
    result = await db.execute(
        select(UserSocialConnection).where(
            UserSocialConnection.user_id == user_id,
            UserSocialConnection.platform == platform,
            UserSocialConnection.is_active == True,  # noqa: E712
        )
    )
    conn = result.scalar_one_or_none()
    if conn:
        conn.last_synced_at = datetime.now(timezone.utc)
        await db.commit()


async def run_instagram_pipeline(
    user_id: int,
    access_token: str,
    db: AsyncSession,
) -> dict:
    """
    Full Instagram analysis pipeline.
    Returns {"signals_saved": int, "platform": "instagram"}.
    """
    logger.info("Starting Instagram pipeline for user_id=%d", user_id)

    # 1. Fetch media + profile
    media   = await fetch_instagram_media(access_token, limit=20)
    profile = await fetch_instagram_profile(access_token)

    if not media:
        logger.warning("No Instagram media found for user_id=%d", user_id)
        return {"signals_saved": 0, "platform": "instagram"}

    # 2. Extract image URLs and captions
    image_urls = [
        m["media_url"] for m in media
        if m.get("media_type") in ("IMAGE", "CAROUSEL_ALBUM")
        and m.get("media_url")
    ]
    captions = [m.get("caption", "") for m in media if m.get("caption")]
    bio = profile.get("biography", "")

    # 3. Analyse images (Groq Vision)
    image_analysis = await analyse_instagram_images_with_groq(
        image_urls=image_urls,
        groq_api_key=settings.GROQ_API_KEY,
    )

    # 4. Analyse captions + bio (Groq LLM)
    caption_analysis = await analyse_instagram_captions_with_groq(
        captions=captions,
        bio=bio,
        groq_api_key=settings.GROQ_API_KEY,
    )

    # 5. Build signal list
    signals = build_instagram_signals(image_analysis, caption_analysis)

    # 6. Save to DB
    count = await _save_signals(db, user_id, "instagram", signals)
    await _update_connection_synced(db, user_id, SocialPlatform.instagram)

    logger.info("Instagram pipeline complete: %d signals saved for user_id=%d", count, user_id)
    return {"signals_saved": count, "platform": "instagram"}


async def run_spotify_pipeline(
    user_id: int,
    access_token: str,
    db: AsyncSession,
) -> dict:
    """
    Full Spotify analysis pipeline.
    Returns {"signals_saved": int, "platform": "spotify"}.
    """
    logger.info("Starting Spotify pipeline for user_id=%d", user_id)

    # 1. Fetch top artists + tracks
    top_artists = await fetch_top_artists(access_token, limit=10)
    top_tracks  = await fetch_top_tracks(access_token,  limit=20)

    if not top_artists and not top_tracks:
        logger.warning("No Spotify data found for user_id=%d", user_id)
        return {"signals_saved": 0, "platform": "spotify"}

    # 2. Fetch audio features for top tracks
    track_ids     = [t["id"] for t in top_tracks if t.get("id")]
    audio_feats   = await fetch_audio_features(access_token, track_ids)
    audio_signals = derive_audio_signals(audio_feats)

    # 3. Build signal list
    signals = build_spotify_signals(top_artists, audio_signals)

    # 4. Save to DB
    count = await _save_signals(db, user_id, "spotify", signals)
    await _update_connection_synced(db, user_id, SocialPlatform.spotify)

    logger.info("Spotify pipeline complete: %d signals saved for user_id=%d", count, user_id)
    return {"signals_saved": count, "platform": "spotify"}
