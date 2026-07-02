import asyncio
from app.db import mongo
from app.api.v1.discovery import feed, _ensure_intent_vectors, _city_venues
from app.services import dating_match, date_recommender, embeddings, events

async def main():
    mongo.connect()
    db = mongo.get_db()
    
    # Get the latest user to act as "me"
    me_user = await db[mongo.USERS].find_one({"role": "dater"}, sort=[("created_at", -1)])
    if not me_user:
        print("No users found")
        return
        
    print(f"Me: {me_user['_id']} - {me_user.get('full_name')}")
    
    # Let's mock the feed call logic locally
    me = me_user["_id"]
    candidates = await db[mongo.USERS].find({
        "role": "dater",
        "_id": {"$ne": me},
        "full_name": {"$nin": [None, ""]},
        "paused": {"$ne": True},
    }).to_list(length=300)
    print(f"Found {len(candidates)} candidate daters")
    
    ids = [u["_id"] for u in candidates]
    prof_by_id = {p["user_id"]: p async for p in db[mongo.PROFILES].find({"user_id": {"$in": ids}})}
    pairs = [(u, prof_by_id.get(u["_id"], {})) for u in candidates]
    
    my_profile = await db[mongo.PROFILES].find_one({"user_id": me}) or {}
    
    scored = []
    for u, prof in pairs:
        ok = dating_match.reciprocal_ok(my_profile, prof)
        print(f"Candidate {u['full_name']} reciprocal_ok: {ok}")
        if ok:
            scored.append(u)
    
    print(f"Remaining candidates after reciprocal_ok: {len(scored)}")
    mongo.close()

asyncio.run(main())
