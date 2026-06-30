"""
Seed demo dater users so the discovery feed has real people to match with.

Each becomes a real user (phone login) + a profile with onboarding_raw, exactly
like an app signup. Idempotent by phone. Run: python -m app.scripts.seed_daters
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.db import mongo

DATERS = [
    ("+447900000001", "Sofia",  "1999-03-12", "Model",         "Bristol", ["Travel", "Sports", "Cooking", "Fashion"]),
    ("+447900000002", "Aria",   "1996-07-02", "Architect",     "Bristol", ["Art", "Coffee", "Hiking"]),
    ("+447900000003", "Lena",   "1998-11-21", "Photographer",  "Bristol", ["Film", "Music", "Travel", "Books"]),
    ("+447900000004", "Maya",   "1997-01-09", "Doctor",        "Bristol", ["Yoga", "Wine", "Brunch"]),
    ("+447900000005", "Chloe",  "2000-05-30", "Designer",      "Bristol", ["Galleries", "Cocktails", "Dogs"]),
    ("+447900000006", "Ruby",   "1995-09-14", "Chef",          "Bristol", ["Food", "Markets", "Cycling"]),
    ("+447900000007", "Isla",   "1999-12-01", "Teacher",       "Bristol", ["Reading", "Theatre", "Coffee"]),
    ("+447900000008", "Nadia",  "1994-04-18", "Founder",       "Bristol", ["Startups", "Running", "Sushi"]),
]


async def run() -> None:
    mongo.connect()
    db = mongo.get_db()
    now = datetime.now(timezone.utc)
    created = 0
    for phone, name, dob, job, city, interests in DATERS:
        if await db[mongo.USERS].find_one({"phone": phone}):
            print(f"  ⏭  {name} exists"); continue
        uid = await mongo.next_id("users")
        await db[mongo.USERS].insert_one({
            "_id": uid, "email": None, "phone": phone, "hashed_password": None,
            "role": "dater", "is_active": True, "full_name": name,
            "preferred_mood": None, "preferred_budget": None, "preferred_stage": None,
            "dietary_requirements": None, "created_at": now, "updated_at": now,
        })
        await db[mongo.PROFILES].insert_one({
            "_id": await mongo.next_id("user_profiles"),
            "user_id": uid, "city": city, "date_of_birth": dob,
            "profile_complete": True, "created_at": now, "updated_at": now,
            "onboarding_raw": {
                "first_name": name, "interests": interests,
                "occupation": {"type": "job", "detail": job, "visible": True},
                "location": {"city": city}, "date_of_birth": dob,
            },
        })
        created += 1
        print(f"  ✅ {name} ({job})")
    print(f"\nDone. Created {created} daters.")
    mongo.close()


if __name__ == "__main__":
    asyncio.run(run())
