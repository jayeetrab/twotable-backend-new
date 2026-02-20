"""
Admin endpoints for venue embedding management.

POST /api/v1/admin/venues/{id}/embed   — embed or refresh one venue
POST /api/v1/admin/venues/embed-all    — background bulk-embed of all active venues
GET  /api/v1/admin/venues/{id}/embed   — inspect current embedding metadata

Auth guards are commented out — uncomment once Step 4 auth is fully wired.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db, async_session_maker
from app.models.venue import Venue
from app.models.venue_embedding import VenueEmbedding
from app.services.venue_embeddings import upsert_venue_embedding, embed_all_venues

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/venues", tags=["admin – embeddings"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class EmbedResponse(BaseModel):
    venue_id: int
    model_name: str
    source_text: str
    message: str


class EmbedMetaResponse(BaseModel):
    venue_id: int
    model_name: str
    source_text: str | None
    created_at: str
    updated_at: str


class EmbedAllResponse(BaseModel):
    message: str


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/{venue_id}/embed", response_model=EmbedMetaResponse)
async def get_venue_embedding_meta(
    venue_id: int,
    db: AsyncSession = Depends(get_db),
    # _admin = Depends(get_current_admin),
):
    """Return metadata about the current embedding for a venue."""
    result = await db.execute(
        select(VenueEmbedding).where(VenueEmbedding.venue_id == venue_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"No embedding found for venue_id={venue_id}. Run POST embed first.",
        )
    return EmbedMetaResponse(
        venue_id=row.venue_id,
        model_name=row.model_name,
        source_text=row.source_text,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.post("/{venue_id}/embed", response_model=EmbedResponse)
async def embed_single_venue(
    venue_id: int,
    db: AsyncSession = Depends(get_db),
    # _admin = Depends(get_current_admin),
):
    """Generate or refresh the embedding for a single venue."""
    venue = await db.get(Venue, venue_id)
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found.")

    row = await upsert_venue_embedding(db, venue)
    return EmbedResponse(
        venue_id=venue_id,
        model_name=row.model_name,
        source_text=row.source_text or "",
        message="Embedding created/updated successfully.",
    )


# Background task creates its own session — the request session will be
# closed long before the task finishes for large venue catalogues.
async def _embed_all_background() -> None:
    async with async_session_maker() as db:
        stats = await embed_all_venues(db)
        logger.info("embed-all finished: %s", stats)


@router.post("/embed-all", response_model=EmbedAllResponse)
async def embed_all_venues_endpoint(
    background_tasks: BackgroundTasks,
    # _admin = Depends(get_current_admin),
):
    """
    Kick off background embedding for every active venue.
    Returns immediately; embedding runs asynchronously.
    Safe to re-run — upserts existing rows.
    """
    background_tasks.add_task(_embed_all_background)
    return EmbedAllResponse(
        message="Bulk embedding task queued. Check server logs for progress."
    )
