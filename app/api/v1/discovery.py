"""
Dating discovery: a feed of real candidate users, like/pass actions, and
mutual-match (connection) creation. All stored in MongoDB.

Collections
-----------
- likes:       {from_user_id, to_user_id, action: "like"|"pass", created_at}
- connections: {user_a_id, user_b_id, created_at}  (a < b; a mutual like)
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.core.deps import get_current_user
from app.db import mongo
from app.services import dating_match, date_recommender, embeddings, events

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/discovery", tags=["discovery"])

# In-process cache of a city's embedding-bearing venues. They change rarely, and refetching
# 400 vector docs from Atlas per feed request dominated latency.
_venue_cache: dict[str, tuple[float, list[dict]]] = {}
_VENUE_TTL = 600.0  # seconds


async def _city_venues(city: str) -> list[dict]:
    import time
    key = city.lower()
    hit = _venue_cache.get(key)
    if hit and (time.monotonic() - hit[0]) < _VENUE_TTL:
        return hit[1]
    docs = await mongo.get_db()[mongo.VENUES].find(
        {"city": {"$regex": city, "$options": "i"}, "is_active": True,
         "embedding": {"$exists": True}},
        {"name": 1, "cuisine": 1, "price_band": 1, "photos": 1, "lat": 1, "lng": 1, "embedding": 1},
    ).to_list(length=400)
    _venue_cache[key] = (time.monotonic(), docs)
    return docs


def _age_from(dob: Optional[str]) -> Optional[int]:
    if not dob:
        return None
    try:
        d = date.fromisoformat(str(dob)[:10])
    except ValueError:
        return None
    today = date.today()
    return today.year - d.year - ((today.month, today.day) < (d.month, d.day))


def _zodiac(dob: Optional[str]) -> Optional[str]:
    """Western zodiac sign from a date of birth (so profiles can show it without exposing DOB)."""
    if not dob:
        return None
    try:
        d = date.fromisoformat(str(dob)[:10])
    except ValueError:
        return None
    md = (d.month, d.day)
    # (start_month, start_day, sign) — a birthday on/after each cutoff belongs to that sign.
    cutoffs = [
        (1, 1, "Capricorn"), (1, 20, "Aquarius"), (2, 19, "Pisces"), (3, 21, "Aries"),
        (4, 20, "Taurus"), (5, 21, "Gemini"), (6, 21, "Cancer"), (7, 23, "Leo"),
        (8, 23, "Virgo"), (9, 23, "Libra"), (10, 23, "Scorpio"), (11, 22, "Sagittarius"),
        (12, 22, "Capricorn"),
    ]
    sign = "Capricorn"
    for month, day, name in cutoffs:
        if md >= (month, day):
            sign = name
    return sign


def _card(user: dict, profile: Optional[dict]) -> dict:
    """Build a discovery card from an already-loaded user + profile (no DB I/O)."""
    profile = profile or {}
    raw = profile.get("onboarding_raw") or {}
    occupation = ""
    occ = raw.get("occupation")
    if isinstance(occ, dict):
        occupation = occ.get("detail") or ""
    interests = raw.get("interests") if isinstance(raw.get("interests"), list) else []
    city = profile.get("city") or (raw.get("location") or {}).get("city") or "Bristol"
    dob = profile.get("date_of_birth") or raw.get("date_of_birth")
    photos = [mongo.photo_url(p) for p in (profile.get("photos") or [])]
    return {
        "user_id": user["_id"],
        "name": user.get("full_name") or "Someone",
        "age": _age_from(dob) or 0,
        "star_sign": _zodiac(dob),
        "verified": bool(user.get("verified") or profile.get("verified")),
        "occupation": occupation,
        "interests": interests[:6],
        "distance": city,
        "city": city,
        "photos": photos,
    }


async def _ensure_intent_vectors(items: list[tuple[dict, dict]]) -> None:
    """Compute + persist a semantic intent vector for any (user, profile) missing one.

    Batched: one embed_batch call and one bulk of upserts instead of per-user work.
    """
    missing = [(u, p) for (u, p) in items if not (p or {}).get("intent_vector")]
    if not missing:
        return
    texts = [dating_match.build_intent_text(p or {}, u.get("full_name") or "") for u, p in missing]
    vectors = await embeddings.embed_batch(texts)
    db = mongo.get_db()
    now = datetime.now(timezone.utc)
    for (u, p), vec in zip(missing, vectors):
        if p is None:
            p = {}
        p["intent_vector"] = vec            # mutate in place so the caller sees it
        await db[mongo.PROFILES].update_one(
            {"user_id": u["_id"]},
            {"$set": {"intent_vector": vec, "intent_updated_at": now}},
            upsert=True,
        )


async def _ranker_params() -> tuple[dict, float]:
    """Load learned ranker weights if a trained model exists, else expert defaults."""
    db = mongo.get_db()
    doc = await db["ranker_model"].find_one({"_id": "dating"})
    if doc and isinstance(doc.get("weights"), dict):
        return doc["weights"], float(doc.get("bias", dating_match.DEFAULT_BIAS))
    return dating_match.DEFAULT_WEIGHTS, dating_match.DEFAULT_BIAS


@router.get("/feed")
async def feed(
    limit: int = Query(20, ge=1, le=50),
    current_user: dict = Depends(get_current_user),
):
    """Candidate daters: exclude self, anyone already actioned, and existing connections."""
    db = mongo.get_db()
    me = current_user["_id"]

    actioned = {d["to_user_id"] async for d in db[mongo.LIKES].find({"from_user_id": me})}
    connected: set[int] = set()
    async for c in db[mongo.CONNECTIONS].find({"$or": [{"user_a_id": me}, {"user_b_id": me}]}):
        connected.add(c["user_a_id"]); connected.add(c["user_b_id"])
    exclude = actioned | connected | {me}

    candidates = await db[mongo.USERS].find({
        "role": "dater",
        "_id": {"$nin": list(exclude)},
        "full_name": {"$nin": [None, ""]},  # only users who finished onboarding
        "paused": {"$ne": True},            # paused accounts are hidden from discovery
    }).to_list(length=300)
    if not candidates:
        return {"count": 0, "profiles": []}

    # One query for all candidate profiles (no per-card lookup), keyed by user id.
    ids = [u["_id"] for u in candidates]
    prof_by_id = {p["user_id"]: p
                  async for p in db[mongo.PROFILES].find({"user_id": {"$in": ids}})}
    pairs = [(u, prof_by_id.get(u["_id"], {})) for u in candidates]

    # My profile + everyone's intent vectors (computed + cached the first time only).
    my_user = current_user
    my_profile = await db[mongo.PROFILES].find_one({"user_id": me}) or {}
    await _ensure_intent_vectors([(my_user, my_profile)] + pairs)
    my_vec = my_profile.get("intent_vector")

    weights, bias = await _ranker_params()

    # Exploration: how often has each candidate been shown? (rarely-shown get a boost)
    impressions = await events.impression_counts(ids)

    scored: list[tuple[float, dict, dict]] = []
    pmutual_of: dict[int, float] = {}
    for u, prof in pairs:
        if not dating_match.reciprocal_ok(my_profile, prof):
            continue                       # gender / who-you-date must match both ways
        cand_vec = prof.get("intent_vector")
        sem = (embeddings.cosine(my_vec, cand_vec) + 1.0) / 2.0 if (my_vec and cand_vec) else 0.5
        feats = dating_match.build_features(my_profile, prof, sem)
        p_mutual = dating_match.score(feats, weights, bias)
        pmutual_of[u["_id"]] = p_mutual
        rank_score = p_mutual + date_recommender.exploration_bonus(impressions.get(u["_id"], 0))
        scored.append((rank_score, u, prof))

    scored.sort(key=lambda x: x[0], reverse=True)
    # Diversity: avoid a top full of near-identical profiles.
    scored = date_recommender.diversify(
        scored, vector_of=lambda p: p.get("intent_vector"), k=limit)
    top = scored[:limit]

    # The TwoTable differentiator: for each top match, find the best *shared* venue and
    # score the full date-success funnel (mutual → book → great date).
    city = (my_profile.get("city") or "Bristol")
    venues = await _city_venues(city)

    # Batch all pair-intent embeddings in one model call (not one per candidate).
    pair_texts = [date_recommender.pair_date_text(my_profile, prof) for _, u, prof in top]
    pair_vecs = await embeddings.embed_batch(pair_texts) if pair_texts else []

    cards = []
    for (_, u, prof), pair_vec in zip(top, pair_vecs):
        p_mutual = pmutual_of.get(u["_id"], 0.5)
        bv = date_recommender.best_venue_for_pair(my_profile, prof, pair_vec, venues)
        venue_fit = bv[1] if bv else 0.5
        dist = dating_match.distance_score(my_profile, prof)
        funnel = date_recommender.expected_success(p_mutual, venue_fit, dist)
        card = {**_card(u, prof),
                "match_score": round(p_mutual, 3),
                "expected_success": round(funnel["expected_success"], 3),
                "funnel": {k: round(v, 3) for k, v in funnel.items()}}
        if bv:
            v = bv[0]
            vp = [mongo.photo_url(p) for p in (v.get("photos") or [])]
            card["suggested_venue"] = {
                "id": v["_id"], "name": v.get("name"), "cuisine": v.get("cuisine"),
                "price_band": v.get("price_band"), "fit": round(venue_fit, 3),
                "photo_url": vp[0] if vp else None,
            }
        cards.append(card)

    await events.log_impressions(me, [u["_id"] for _, u, _ in top])
    return {"count": len(cards), "profiles": cards}


class ActionRequest(BaseModel):
    target_id: int
    action: Literal["like", "pass"]


@router.post("/action")
async def action(payload: ActionRequest, current_user: dict = Depends(get_current_user)):
    """Record a like/pass. A like that's reciprocated creates a connection (a match)."""
    db = mongo.get_db()
    me = current_user["_id"]
    now = datetime.now(timezone.utc)

    await db[mongo.LIKES].update_one(
        {"from_user_id": me, "to_user_id": payload.target_id},
        {"$set": {"action": payload.action, "created_at": now}},
        upsert=True,
    )
    await events.log_event(payload.action, me, target_id=payload.target_id)  # funnel signal

    if payload.action != "like":
        return {"matched": False}

    reciprocal = await db[mongo.LIKES].find_one({
        "from_user_id": payload.target_id, "to_user_id": me, "action": "like",
    })
    if not reciprocal:
        return {"matched": False}

    await events.log_event("mutual_match", me, target_id=payload.target_id)

    a, b = sorted((me, payload.target_id))
    conn = await db[mongo.CONNECTIONS].find_one({"user_a_id": a, "user_b_id": b})
    if not conn:
        conn = {"_id": await mongo.next_id("connections"),
                "user_a_id": a, "user_b_id": b, "created_at": now}
        await db[mongo.CONNECTIONS].insert_one(conn)
    other = await db[mongo.USERS].find_one({"_id": payload.target_id})
    other_profile = await db[mongo.PROFILES].find_one({"user_id": payload.target_id}) if other else None
    logger.info("Match! %s <-> %s", me, payload.target_id)
    return {"matched": True, "connection_id": conn["_id"],
            "with": _card(other, other_profile) if other else None}


@router.get("/matches")
async def matches(current_user: dict = Depends(get_current_user)):
    """The users the current user has mutually matched with."""
    db = mongo.get_db()
    me = current_user["_id"]
    other_ids = []
    async for c in db[mongo.CONNECTIONS].find({"$or": [{"user_a_id": me}, {"user_b_id": me}]}):
        other_ids.append(c["user_b_id"] if c["user_a_id"] == me else c["user_a_id"])
    if not other_ids:
        return {"count": 0, "matches": []}

    # Batch-load users + profiles instead of one query per connection.
    users = {u["_id"]: u async for u in db[mongo.USERS].find({"_id": {"$in": other_ids}})}
    profs = {p["user_id"]: p async for p in db[mongo.PROFILES].find({"user_id": {"$in": other_ids}})}
    out = [_card(users[i], profs.get(i)) for i in other_ids if i in users]
    return {"count": len(out), "matches": out}


class ReportRequest(BaseModel):
    target_id: int
    reason: str                      # e.g. "fake_profile", "inappropriate", "harassment", "other"
    details: Optional[str] = None


@router.post("/report", status_code=201)
async def report_user(payload: ReportRequest, current_user: dict = Depends(get_current_user)):
    """Report (and effectively block) another user.

    Safety must-have: stores the report for moderation, records a pass so they never
    resurface in the reporter's feed, and severs any existing match between the two.
    """
    db = mongo.get_db()
    me = current_user["_id"]
    now = datetime.now(timezone.utc)
    await db["user_reports"].insert_one({
        "reporter_id": me, "target_id": payload.target_id,
        "reason": payload.reason, "details": payload.details,
        "status": "open", "created_at": now,
    })
    # Block: pass them + remove any connection, both directions of visibility.
    await db[mongo.LIKES].update_one(
        {"from_user_id": me, "to_user_id": payload.target_id},
        {"$set": {"action": "pass", "created_at": now}}, upsert=True)
    a, b = sorted((me, payload.target_id))
    await db[mongo.CONNECTIONS].delete_one({"user_a_id": a, "user_b_id": b})
    logger.info("User %s reported %s (%s)", me, payload.target_id, payload.reason)
    return {"reported": True}


@router.delete("/matches/{user_id}", status_code=200)
async def unmatch(user_id: int, current_user: dict = Depends(get_current_user)):
    """Remove a mutual match. Records a pass so they won't resurface in the feed."""
    db = mongo.get_db()
    me = current_user["_id"]
    a, b = sorted((me, user_id))
    await db[mongo.CONNECTIONS].delete_one({"user_a_id": a, "user_b_id": b})
    # Turn my like into a pass so the unmatched person doesn't reappear.
    await db[mongo.LIKES].update_one(
        {"from_user_id": me, "to_user_id": user_id},
        {"$set": {"action": "pass", "created_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    return {"unmatched": True}
