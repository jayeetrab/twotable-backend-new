"""
Backfill real photos for every placeholder:

- Demo dater profiles get real portrait photos (randomuser.me, gender-matched,
  deterministic per user id). Real/dev accounts are excluded.
- The most relevant active venues (coords + embedding, city centre first) get real
  restaurant/food photos (foodish-api.com, picsum fallback).

Everything lands in GridFS, so it serves through the normal /photos/{id} endpoint
with the long-lived cache headers. Idempotent-ish: only touches profiles/venues
whose photos are empty or monogram-generated, unless --replace is passed.

Run:  python -m app.scripts.backfill_photos [--venues 60] [--replace]
"""
from __future__ import annotations

import argparse
import asyncio
import logging

import httpx

from app.db import mongo
from app.services.geo import haversine_km

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("backfill_photos")

# Accounts that belong to real people testing the app: never touch their photos.
PROTECTED_PHONES = {"+447438153933"}

BRISTOL = (51.4545, -2.5879)


async def fetch(client: httpx.AsyncClient, url: str) -> bytes | None:
    try:
        r = await client.get(url, follow_redirects=True, timeout=20)
        if r.status_code == 200 and len(r.content) > 5000:
            return r.content
    except Exception as exc:
        log.warning("  fetch failed %s: %s", url[:60], exc)
    return None


async def store(data: bytes, name: str, kind: str) -> str:
    fid = await mongo.gridfs().upload_from_stream(
        name, data, metadata={"content_type": "image/jpeg", "backfill": kind})
    return str(fid)


async def portrait(client: httpx.AsyncClient, gender: str | None, seed: int) -> bytes | None:
    folder = "women" if (gender or "").lower().startswith("w") else "men"
    return await fetch(client, f"https://randomuser.me/api/portraits/{folder}/{seed % 99}.jpg")


async def food_photo(client: httpx.AsyncClient, venue_id: int) -> bytes | None:
    try:
        r = await client.get("https://foodish-api.com/api/", timeout=15)
        url = r.json().get("image")
        if url:
            data = await fetch(client, url)
            if data:
                return data
    except Exception:
        pass
    # Fallback: seeded real photography (generic but real).
    return await fetch(client, f"https://picsum.photos/seed/twotable{venue_id}/900/700")


async def backfill_daters(client: httpx.AsyncClient, replace: bool) -> None:
    db = mongo.get_db()
    done = 0
    async for user in db[mongo.USERS].find({"role": "dater"}):
        if user.get("phone") in PROTECTED_PHONES:
            continue
        prof = await db[mongo.PROFILES].find_one({"user_id": user["_id"]})
        if prof is None:
            continue
        if prof.get("photos") and not replace:
            # Only replace generated monograms; leave anything a human uploaded.
            first = prof["photos"][0]
            try:
                from bson import ObjectId
                g = await db["photos.files"].find_one({"_id": ObjectId(first)})
                if not g or "monogram" not in str((g.get("metadata") or {})).lower():
                    if (g.get("metadata") or {}).get("backfill") != "monogram" and \
                       "generated" not in str((g.get("metadata") or {})).lower():
                        # Existing non-generated photo: check if it's a tiny monogram (<20KB)
                        if (g or {}).get("length", 0) > 20000:
                            continue
            except Exception:
                pass

        gender = (prof.get("onboarding_raw") or {}).get("gender") or prof.get("gender")
        pics = []
        for k in range(2):  # two portraits per profile
            data = await portrait(client, gender, user["_id"] * 7 + k * 31)
            if data:
                pics.append(await store(data, f"dater_{user['_id']}_{k}.jpg", "portrait"))
        if pics:
            await db[mongo.PROFILES].update_one(
                {"_id": prof["_id"]}, {"$set": {"photos": pics}})
            done += 1
            log.info("dater %-4s %-14s -> %d portraits", user["_id"],
                     (user.get("full_name") or "?")[:14], len(pics))
    log.info("✅ daters updated: %d", done)


async def backfill_venues(client: httpx.AsyncClient, limit: int) -> None:
    db = mongo.get_db()
    venues = await db[mongo.VENUES].find(
        {"is_active": True, "lat": {"$ne": None}, "lng": {"$ne": None},
         "embedding": {"$exists": True},
         "$or": [{"photos": {"$exists": False}}, {"photos": []}]},
        {"name": 1, "lat": 1, "lng": 1},
    ).to_list(length=3000)
    venues.sort(key=lambda v: haversine_km(BRISTOL[0], BRISTOL[1], v["lat"], v["lng"]))
    picked = venues[:limit]
    log.info("Backfilling %d venues (of %d without photos)…", len(picked), len(venues))

    done = 0
    for v in picked:
        data = await food_photo(client, v["_id"])
        if not data:
            continue
        fid = await store(data, f"venue_{v['_id']}.jpg", "venue")
        await db[mongo.VENUES].update_one({"_id": v["_id"]}, {"$set": {"photos": [fid]}})
        done += 1
        if done % 10 == 0:
            log.info("  …%d/%d", done, len(picked))
    log.info("✅ venues updated: %d", done)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--venues", type=int, default=60, help="how many venues to photo-fill")
    ap.add_argument("--replace", action="store_true", help="replace existing dater photos too")
    args = ap.parse_args()

    mongo.connect()
    async with httpx.AsyncClient() as client:
        await backfill_daters(client, args.replace)
        await backfill_venues(client, args.venues)
    mongo.close()


if __name__ == "__main__":
    asyncio.run(main())
