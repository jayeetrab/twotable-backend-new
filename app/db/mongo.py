"""
MongoDB connection layer for TwoTable (Motor / async).

A single AsyncIOMotorClient is created at app startup (see app.main.lifespan)
and shared across the process. Collection accessors and a small auto-increment
counter helper live here so the rest of the app never touches the driver
directly.

Integer primary keys
--------------------
The iOS client decodes ``id`` as an ``Int``, so documents use integer ``_id``
values produced by ``next_id()`` (a classic Mongo counters collection) instead
of ``ObjectId``. This keeps the JSON contract identical to the old SQL backend.
"""
from __future__ import annotations

from typing import Optional

from motor.motor_asyncio import (
    AsyncIOMotorClient,
    AsyncIOMotorDatabase,
    AsyncIOMotorGridFSBucket,
)

from app.core.config import settings

# Collection names.
# NOTE: the API owns `venues_app` (flattened, integer-id docs produced by
# app.scripts.seed_venues). The pre-existing `venues` collection holds raw
# Google-Places data and is left untouched.
USERS = "users"
PROFILES = "user_profiles"
AVAILABILITY = "user_availability"
VENUES = "venues_app"
VENUE_LEADS = "venue_leads"
MATCHES = "matches"
BOOKINGS = "bookings"
LIKES = "likes"              # dating like/pass actions
CONNECTIONS = "connections"  # mutual likes (dating matches)
COUNTERS = "counters"

_client: Optional[AsyncIOMotorClient] = None
_db: Optional[AsyncIOMotorDatabase] = None


def connect() -> AsyncIOMotorDatabase:
    global _client, _db
    if _db is None:
        _client = AsyncIOMotorClient(
            settings.MONGODB_URI,
            tz_aware=True,
            serverSelectionTimeoutMS=8000,
            connectTimeoutMS=8000,
        )
        _db = _client[settings.MONGODB_DB]
    return _db


def close() -> None:
    global _client, _db
    if _client is not None:
        _client.close()
    _client = None
    _db = None


def get_db() -> AsyncIOMotorDatabase:
    """Return the live database handle (must call connect() first)."""
    if _db is None:
        return connect()
    return _db


def gridfs() -> AsyncIOMotorGridFSBucket:
    """GridFS bucket for user photos."""
    return AsyncIOMotorGridFSBucket(get_db(), bucket_name="photos")


def photo_url(file_id) -> str:
    """Absolute URL the app can load a stored photo from."""
    return f"{settings.PUBLIC_BASE_URL}/api/v1/photos/{file_id}"


# ── Auto-increment integer IDs ────────────────────────────────────────────────

async def next_id(name: str) -> int:
    """
    Atomically return the next integer id for a named sequence.
    Uses the standard findOneAndUpdate upsert pattern on the counters collection.
    """
    db = get_db()
    doc = await db[COUNTERS].find_one_and_update(
        {"_id": name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,
    )
    return int(doc["seq"])


# ── Indexes ───────────────────────────────────────────────────────────────────

async def ensure_indexes() -> None:
    """Create indexes required for correctness + performance. Idempotent."""
    db = get_db()
    # email/phone are each unique only among docs that actually have one (partial index),
    # so email-only users and phone-only users can coexist with null in the other field.
    existing = await db[USERS].index_information()
    if "email_1" in existing and not existing["email_1"].get("partialFilterExpression"):
        await db[USERS].drop_index("email_1")
    await db[USERS].create_index(
        "email", unique=True, name="email_unique",
        partialFilterExpression={"email": {"$type": "string"}},
    )
    await db[USERS].create_index(
        "phone", unique=True, name="phone_unique",
        partialFilterExpression={"phone": {"$type": "string"}},
    )
    await db[PROFILES].create_index("user_id", unique=True)
    await db[PROFILES].create_index("city")
    await db[AVAILABILITY].create_index(
        [("user_id", 1), ("weekday", 1), ("start_time", 1)], unique=True
    )
    await db[VENUES].create_index("city")
    await db[VENUES].create_index("is_active")
    await db[VENUE_LEADS].create_index("email", unique=True)
    await db[MATCHES].create_index("user_a_id")
    await db[MATCHES].create_index("user_b_id")
    await db[BOOKINGS].create_index("match_id")
    await db[BOOKINGS].create_index("stripe_payment_intent_id")
    await db[LIKES].create_index([("from_user_id", 1), ("to_user_id", 1)], unique=True)
    await db[CONNECTIONS].create_index([("user_a_id", 1), ("user_b_id", 1)], unique=True)
    # The discovery feed and /matches query connections by EITHER side, so user_b_id needs
    # its own index (the compound above only covers the user_a_id prefix).
    await db[CONNECTIONS].create_index("user_b_id")
    # The feed scans daters who finished onboarding — index the filter fields.
    await db[USERS].create_index([("role", 1), ("full_name", 1)])
    # Tonight's Table opt-ins: one row per user per day, queried by date.
    await db["tonight_optins"].create_index([("user_id", 1), ("date", 1)], unique=True)
    await db["tonight_optins"].create_index("date")
    # Match funnel events (impression → like → match → booked → attended → rated).
    await db["match_events"].create_index([("kind", 1), ("target_id", 1)])
    await db["match_events"].create_index([("user_id", 1), ("created_at", -1)])
    # Date plans: one coordination doc per matched pair.
    await db["date_plans"].create_index([("user_a_id", 1), ("user_b_id", 1)], unique=True)
    # Safety reports, queried by moderation status and by target.
    await db["user_reports"].create_index([("status", 1), ("created_at", -1)])
    await db["user_reports"].create_index("target_id")
