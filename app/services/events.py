"""
Interaction + outcome event log — the learning substrate for TwoTable's matcher.

Every step of the date funnel is recorded in `match_events`:

    impression → like / pass → mutual_match → booked → attended → rated → rematched

Two things make this a defensible signal competitors don't have:

1. We rank by *real-world date outcomes*, not just swipes. Because TwoTable owns the
   venue + booking, we observe whether a match actually became a booked, attended,
   well-rated date — the ground truth other dating apps never see.
2. The funnel lets us model expected date success as a calibrated product of stage
   probabilities and train the ranker on it (see services.date_recommender).

All writes are fire-and-forget and never raise into the request path.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.db import mongo

logger = logging.getLogger(__name__)

EVENTS = "match_events"

# Funnel stages, in order. Numeric rank lets us compute "how far did this pair get".
STAGES = {
    "impression": 0, "pass": 0, "like": 1, "mutual_match": 2,
    "booked": 3, "attended": 4, "rated": 5, "rematched": 6,
}


async def log_event(
    kind: str,
    user_id: int,
    target_id: Optional[int] = None,
    venue_id: Optional[int] = None,
    meta: Optional[dict[str, Any]] = None,
) -> None:
    """Append one funnel event. Best-effort: swallows all errors."""
    try:
        await mongo.get_db()[EVENTS].insert_one({
            "kind": kind,
            "stage": STAGES.get(kind, 0),
            "user_id": user_id,
            "target_id": target_id,
            "venue_id": venue_id,
            "meta": meta or {},
            "created_at": datetime.now(timezone.utc),
        })
    except Exception as exc:  # never break the request because logging failed
        logger.debug("event log failed (%s): %s", kind, exc)


async def log_impressions(user_id: int, target_ids: list[int]) -> None:
    """Record that these candidates were shown to `user_id` (for exploration + CTR)."""
    if not target_ids:
        return
    try:
        now = datetime.now(timezone.utc)
        await mongo.get_db()[EVENTS].insert_many(
            [{"kind": "impression", "stage": 0, "user_id": user_id,
              "target_id": t, "venue_id": None, "meta": {}, "created_at": now}
             for t in target_ids],
            ordered=False,
        )
    except Exception as exc:
        logger.debug("impression log failed: %s", exc)


async def impression_counts(target_ids: list[int]) -> dict[int, int]:
    """How many times each candidate has been shown — drives exploration of new profiles."""
    if not target_ids:
        return {}
    try:
        pipeline = [
            {"$match": {"kind": "impression", "target_id": {"$in": target_ids}}},
            {"$group": {"_id": "$target_id", "n": {"$sum": 1}}},
        ]
        out: dict[int, int] = {}
        async for row in mongo.get_db()[EVENTS].aggregate(pipeline):
            out[row["_id"]] = row["n"]
        return out
    except Exception:
        return {}
