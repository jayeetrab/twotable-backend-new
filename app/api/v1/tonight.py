"""
Tonight's Table — TwoTable's signature feature.

One curated restaurant per day per city. Users opt in before the evening cutoff
and get paired with other people who also want to dine out *tonight*. This makes
the app's Tonight tab real and persistent (it was local-only before):

- GET    /tonight            → today's pick, opt-in state, how many are in, avatars
- POST   /tonight/opt-in     → join tonight
- DELETE /tonight/opt-in     → leave tonight
- GET    /tonight/people     → others in tonight, ranked by the intent matcher
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Query

from app.api.v1.discovery import _card
from app.core.deps import get_current_user
from app.db import mongo
from app.services import dating_match, embeddings

router = APIRouter(prefix="/tonight", tags=["tonight"])

OPTINS = "tonight_optins"
CUTOFF_HOUR = 17  # opt in before 5pm


def _today() -> str:
    return date.today().isoformat()


def _venue_card(v: dict) -> dict:
    photos = [mongo.photo_url(p) for p in (v.get("photos") or [])]
    return {
        "id": v["_id"], "name": v.get("name"), "address": v.get("address"),
        "city": v.get("city"), "cuisine": v.get("cuisine"),
        "price_band": v.get("price_band"), "lat": v.get("lat"), "lng": v.get("lng"),
        "description": v.get("description"),
        "photo_url": photos[0] if photos else None, "photos": photos,
    }


async def _todays_venue(city: str) -> dict | None:
    """Deterministic pick for the day+city, stable for everyone until midnight."""
    db = mongo.get_db()
    venues = await db[mongo.VENUES].find({
        "city": {"$regex": city, "$options": "i"}, "is_active": True,
        "lat": {"$ne": None}, "lng": {"$ne": None},
    }).sort("_id", 1).to_list(length=500)
    venues = [v for v in venues if v.get("photos")] or venues
    if not venues:
        return None
    seed = int(hashlib.sha1(f"{_today()}:{city.lower()}".encode()).hexdigest(), 16)
    return venues[seed % len(venues)]


async def _optin_user_ids(exclude: int | None = None) -> list[int]:
    db = mongo.get_db()
    ids = [d["user_id"] async for d in db[OPTINS].find({"date": _today()})]
    return [i for i in ids if i != exclude]


@router.get("")
async def tonight(city: str = Query("Bristol"), current_user: dict = Depends(get_current_user)):
    db = mongo.get_db()
    me = current_user["_id"]
    venue = await _todays_venue(city)
    optins = await _optin_user_ids()
    am_in = me in optins

    # A few avatars of people who are in (excluding me).
    others = [i for i in optins if i != me][:8]
    profs = {p["user_id"]: p async for p in db[mongo.PROFILES].find({"user_id": {"$in": others}})}
    avatars = [mongo.photo_url(p["photos"][0])
               for i in others if (p := profs.get(i)) and p.get("photos")]

    now = datetime.now(timezone.utc)
    return {
        "date": _today(),
        "day": now.strftime("%A"),
        "cutoff_hour": CUTOFF_HOUR,
        "past_cutoff": now.hour >= CUTOFF_HOUR,
        "opted_in": am_in,
        "going_count": len(optins),
        "avatars": avatars[:4],
        "venue": _venue_card(venue) if venue else None,
    }


@router.post("/opt-in")
async def opt_in(city: str = Query("Bristol"), current_user: dict = Depends(get_current_user)):
    db = mongo.get_db()
    await db[OPTINS].update_one(
        {"user_id": current_user["_id"], "date": _today()},
        {"$set": {"user_id": current_user["_id"], "date": _today(), "city": city,
                  "created_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    count = await db[OPTINS].count_documents({"date": _today()})
    return {"opted_in": True, "going_count": count}


@router.delete("/opt-in")
async def opt_out(current_user: dict = Depends(get_current_user)):
    db = mongo.get_db()
    await db[OPTINS].delete_one({"user_id": current_user["_id"], "date": _today()})
    count = await db[OPTINS].count_documents({"date": _today()})
    return {"opted_in": False, "going_count": count}


@router.get("/people")
async def tonight_people(limit: int = Query(20, ge=1, le=50),
                         current_user: dict = Depends(get_current_user)):
    """Other people who are in for tonight, ranked by the same intent matcher as the feed."""
    db = mongo.get_db()
    me = current_user["_id"]

    actioned = {d["to_user_id"] async for d in db[mongo.LIKES].find({"from_user_id": me})}
    candidate_ids = [i for i in await _optin_user_ids(exclude=me) if i not in actioned]
    if not candidate_ids:
        return {"count": 0, "profiles": []}

    users = {u["_id"]: u async for u in db[mongo.USERS].find(
        {"_id": {"$in": candidate_ids}, "full_name": {"$nin": [None, ""]}})}
    profs = {p["user_id"]: p async for p in db[mongo.PROFILES].find({"user_id": {"$in": candidate_ids}})}
    my_profile = await db[mongo.PROFILES].find_one({"user_id": me}) or {}
    my_vec = my_profile.get("intent_vector")

    scored = []
    for uid, u in users.items():
        prof = profs.get(uid, {})
        if not dating_match.reciprocal_ok(my_profile, prof):
            continue
        cv = prof.get("intent_vector")
        sem = (embeddings.cosine(my_vec, cv) + 1.0) / 2.0 if (my_vec and cv) else 0.5
        s = dating_match.score(dating_match.build_features(my_profile, prof, sem))
        scored.append((s, u, prof))

    scored.sort(key=lambda x: x[0], reverse=True)
    cards = [{**_card(u, p), "match_score": round(s, 3)} for s, u, p in scored[:limit]]
    return {"count": len(cards), "profiles": cards}
