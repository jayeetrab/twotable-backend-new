from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user_embedding import UserEmbedding
from app.models.user_profile import UserProfile
from app.models.user_social_signal import UserSocialSignal
from app.services.embeddings import TASK_DOCUMENT, embedding_provider

logger = logging.getLogger(__name__)


def build_user_source_text(
    profile: UserProfile,
    signals: list[UserSocialSignal],
) -> str:
    parts: list[str] = []

    if profile.gender:
        parts.append(f"I am a {profile.gender.value}.")
    if profile.looking_for_gender:
        parts.append(f"I am looking for a {', '.join(profile.looking_for_gender)}.")
    if profile.city:
        parts.append(f"I am based in {profile.city}.")
    if profile.relationship_goal:
        parts.append(f"I am looking for something {profile.relationship_goal.value}.")
    if profile.social_energy:
        parts.append(f"My social energy is {profile.social_energy.value}.")
    if profile.communication_style:
        parts.append(f"I communicate as a {profile.communication_style.value}.")
    if profile.love_language:
        parts.append(f"My love languages are {', '.join(profile.love_language)}.")
    if profile.preferred_mood:
        parts.append(f"I prefer {profile.preferred_mood} dates.")
    if profile.preferred_budget:
        parts.append(f"My preferred budget is {profile.preferred_budget}.")
    if profile.preferred_time:
        parts.append(f"I prefer {profile.preferred_time.value} dates.")
    if profile.noise_tolerance:
        parts.append(f"I prefer {profile.noise_tolerance} environments.")
    if profile.alcohol:
        parts.append(f"My relationship with alcohol is {profile.alcohol.value}.")
    if profile.cuisine_preferences:
        parts.append(f"I enjoy {', '.join(profile.cuisine_preferences)} cuisine.")
    if profile.music_genres:
        parts.append(f"I listen to {', '.join(profile.music_genres)} music.")
    if profile.activities:
        parts.append(f"I enjoy activities like {', '.join(profile.activities)}.")
    if profile.hobbies:
        parts.append(f"My hobbies include {', '.join(profile.hobbies)}.")
    if profile.dietary_requirements:
        parts.append(f"I am {profile.dietary_requirements}.")
    if profile.bio:
        parts.append(profile.bio.strip())
    if profile.fun_fact:
        parts.append(profile.fun_fact.strip())
    if profile.onboarding_answers:
        for value in profile.onboarding_answers.values():
            if value:
                parts.append(str(value).strip())

    # Social signals
    signal_map: dict[str, list[str]] = {}
    for s in signals:
        signal_map.setdefault(s.signal_type, []).append(s.signal_value)

    if "music_genre" in signal_map:
        parts.append(f"My music taste includes {', '.join(signal_map['music_genre'])}.")
    if "top_artist" in signal_map:
        parts.append(f"I listen to artists like {', '.join(signal_map['top_artist'][:5])}.")
    if "aesthetic" in signal_map:
        parts.append(f"My visual aesthetic is {', '.join(signal_map['aesthetic'])}.")
    if "activity" in signal_map:
        parts.append(f"I spend time doing {', '.join(signal_map['activity'])}.")
    if "personality_trait" in signal_map:
        parts.append(f"I am {', '.join(signal_map['personality_trait'])}.")
    if "valence" in signal_map:
        parts.append(f"My music mood is generally {signal_map['valence'][0]}.")
    if "energy_level" in signal_map:
        parts.append(f"My energy level is {signal_map['energy_level'][0]}.")

    return " ".join(parts)


async def upsert_user_embedding(
    db: AsyncSession,
    user_id: int,
) -> UserEmbedding:
    profile_result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    )
    profile = profile_result.scalar_one_or_none()
    if not profile:
        raise ValueError(f"No UserProfile for user_id={user_id}. Run /profile/setup first.")

    signals_result = await db.execute(
        select(UserSocialSignal).where(UserSocialSignal.user_id == user_id)
    )
    signals = list(signals_result.scalars().all())

    source_text = build_user_source_text(profile, signals)
    vector = await embedding_provider.embed(source_text, task_type=TASK_DOCUMENT)

    existing = await db.execute(
        select(UserEmbedding).where(UserEmbedding.user_id == user_id)
    )
    row = existing.scalar_one_or_none()

    if row:
        row.embedding   = vector
        row.model_name  = settings.EMBEDDING_MODEL
        row.source_text = source_text
    else:
        row = UserEmbedding(
            user_id=user_id,
            embedding=vector,
            model_name=settings.EMBEDDING_MODEL,
            source_text=source_text,
        )
        db.add(row)

    await db.commit()
    await db.refresh(row)
    logger.info("UserEmbedding upserted for user_id=%d", user_id)
    return row


async def find_similar_users(
    db: AsyncSession,
    user_id: int,
    limit: int = 20,
    exclude_ids: Optional[list[int]] = None,
) -> list[tuple[int, float]]:
    result = await db.execute(
        select(UserEmbedding).where(UserEmbedding.user_id == user_id)
    )
    my_row = result.scalar_one_or_none()
    if not my_row:
        return []

    exclude = set(exclude_ids or [])
    exclude.add(user_id)

    rows = await db.execute(
        select(
            UserEmbedding.user_id,
            UserEmbedding.embedding.cosine_distance(my_row.embedding).label("distance"),
        )
        .where(UserEmbedding.user_id.notin_(exclude))
        .order_by("distance")
        .limit(limit)
    )
    return [(row.user_id, row.distance) for row in rows]
