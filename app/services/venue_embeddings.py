"""
CRUD + similarity search for venue and intent embeddings.
"""
from __future__ import annotations

import asyncio
import logging
from typing import List, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.intent_embedding import IntentEmbedding
from app.models.venue import Venue
from app.models.venue_embedding import VenueEmbedding
from app.services.embeddings import (
    TASK_DOCUMENT,
    TASK_QUERY,
    build_venue_source_text,
    embedding_provider,
)

logger = logging.getLogger(__name__)

# Batch size — local model can handle larger batches than Gemini free tier
BATCH_SIZE = 64


# ── Venue embedding CRUD ──────────────────────────────────────────────────────

async def upsert_venue_embedding(
    db: AsyncSession,
    venue: Venue,
) -> VenueEmbedding:
    source_text = build_venue_source_text(venue)
    vector = await embedding_provider.embed(source_text, task_type=TASK_DOCUMENT)

    result = await db.execute(
        select(VenueEmbedding).where(VenueEmbedding.venue_id == venue.id)
    )
    row = result.scalar_one_or_none()

    if row:
        row.embedding = vector
        row.model_name = settings.EMBEDDING_MODEL
        row.source_text = source_text
        logger.info("Updated embedding for venue_id=%d (%s)", venue.id, venue.name)
    else:
        row = VenueEmbedding(
            venue_id=venue.id,
            embedding=vector,
            model_name=settings.EMBEDDING_MODEL,
            source_text=source_text,
        )
        db.add(row)
        logger.info("Created embedding for venue_id=%d (%s)", venue.id, venue.name)

    await db.commit()
    await db.refresh(row)
    return row


async def embed_all_venues(db: AsyncSession) -> dict:
    """
    Bulk-embed all active venues.
    Local model: no rate limits, batch size 64, no sleep needed.
    """
    result = await db.execute(
        select(Venue).where(Venue.is_active == True)  # noqa: E712
    )
    venues: list[Venue] = result.scalars().all()
    total = len(venues)
    success = 0
    failed = 0

    logger.info("embed_all_venues starting — %d venues, batch_size=%d", total, BATCH_SIZE)

    for i in range(0, total, BATCH_SIZE):
        batch = venues[i: i + BATCH_SIZE]
        source_texts = [build_venue_source_text(v) for v in batch]

        try:
            vectors = await embedding_provider.embed_batch(
                source_texts, task_type=TASK_DOCUMENT
            )
        except Exception as exc:
            logger.error("Batch %d failed: %s", i // BATCH_SIZE, exc)
            failed += len(batch)
            continue

        # No sleep needed — local model has no rate limits

        for venue, vector, source_text in zip(batch, vectors, source_texts):
            try:
                existing = await db.execute(
                    select(VenueEmbedding).where(VenueEmbedding.venue_id == venue.id)
                )
                row = existing.scalar_one_or_none()
                if row:
                    row.embedding = vector
                    row.model_name = settings.EMBEDDING_MODEL
                    row.source_text = source_text
                else:
                    db.add(VenueEmbedding(
                        venue_id=venue.id,
                        embedding=vector,
                        model_name=settings.EMBEDDING_MODEL,
                        source_text=source_text,
                    ))
                await db.commit()
                success += 1
            except Exception as exc:
                await db.rollback()
                logger.error("DB write failed for venue_id=%d: %s", venue.id, exc)
                failed += 1

    logger.info(
        "embed_all_venues complete: %d/%d succeeded, %d failed",
        success, total, failed,
    )
    return {"total": total, "success": success, "failed": failed}


# ── Similarity search ─────────────────────────────────────────────────────────

async def find_similar_venues(
    db: AsyncSession,
    intent_vector: List[float],
    candidate_venue_ids: List[int],
    top_n: int = 10,
) -> List[Tuple[int, float]]:
    """
    pgvector cosine distance search.
    Returns [(venue_id, distance), ...] sorted ascending (lower = better match).
    Only searches within the pre-filtered candidate set.
    """
    if not candidate_venue_ids:
        return []

    rows = await db.execute(
        select(
            VenueEmbedding.venue_id,
            VenueEmbedding.embedding.cosine_distance(intent_vector).label("distance"),
        )
        .where(VenueEmbedding.venue_id.in_(candidate_venue_ids))
        .order_by("distance")
        .limit(top_n)
    )
    return [(r.venue_id, float(r.distance)) for r in rows.all()]


# ── Intent logging ────────────────────────────────────────────────────────────

async def log_intent_embedding(
    db: AsyncSession,
    *,
    session_id: str | None,
    intent_text: str,
    vector: List[float],
) -> None:
    try:
        db.add(IntentEmbedding(
            session_id=session_id,
            intent_text=intent_text,
            embedding=vector,
            model_name=settings.EMBEDDING_MODEL,
        ))
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.warning("Failed to log intent embedding: %s", exc)
