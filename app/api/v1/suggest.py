from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.suggest import SuggestRequest, SuggestResponse
from app.services.matcher import suggest_venues

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/venues", tags=["suggest"])


@router.post("/suggest", response_model=SuggestResponse)
async def suggest(
    payload: SuggestRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    try:
        suggestions, intent_text = await suggest_venues(db=db, req=payload)
    except Exception as exc:
        logger.exception("Matcher failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Matcher error: {str(exc)}")

    if not suggestions:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No venues found in {payload.city} matching your criteria. "
                "Try a wider time window, different city, or adjust preferences."
            ),
        )

    return SuggestResponse(
        count=len(suggestions),
        intent_text=intent_text,
        suggestions=suggestions,
    )
