"""User photo upload + serving, backed by MongoDB GridFS."""
from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

from app.core.deps import get_current_user
from app.db import mongo

router = APIRouter(tags=["photos"])

MAX_PHOTOS = 9


@router.post("/profile/photos")
async def upload_photo(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """Upload one profile photo. Stored in GridFS; its id is appended to the profile."""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    bucket = mongo.gridfs()
    file_id = await bucket.upload_from_stream(
        file.filename or "photo.jpg", data,
        metadata={"user_id": current_user["_id"],
                  "content_type": file.content_type or "image/jpeg"},
    )
    pid = str(file_id)

    db = mongo.get_db()
    res = await db[mongo.PROFILES].update_one(
        {"user_id": current_user["_id"]}, {"$push": {"photos": pid}}
    )
    if res.matched_count == 0:
        now = datetime.now(timezone.utc)
        await db[mongo.PROFILES].insert_one({
            "_id": await mongo.next_id("user_profiles"),
            "user_id": current_user["_id"], "photos": [pid],
            "profile_complete": False, "created_at": now, "updated_at": now,
        })
    return {"photo_id": pid, "url": mongo.photo_url(pid)}


@router.delete("/profile/photos/{file_id}", status_code=204)
async def delete_photo(file_id: str, current_user: dict = Depends(get_current_user)):
    """Remove one of the current user's photos (from the profile list + GridFS)."""
    db = mongo.get_db()
    profile = await db[mongo.PROFILES].find_one({"user_id": current_user["_id"]})
    if not profile or file_id not in (profile.get("photos") or []):
        raise HTTPException(status_code=404, detail="Photo not found")

    await db[mongo.PROFILES].update_one(
        {"user_id": current_user["_id"]}, {"$pull": {"photos": file_id}}
    )
    try:
        await mongo.gridfs().delete(ObjectId(file_id))
    except Exception:
        pass  # already gone — the profile list is the source of truth
    return Response(status_code=204)


@router.put("/profile/photos/order")
async def reorder_photos(
    order: list[str] = Body(..., embed=True),
    current_user: dict = Depends(get_current_user),
):
    """Reorder the current user's photos. `order` must be a permutation of existing ids."""
    db = mongo.get_db()
    profile = await db[mongo.PROFILES].find_one({"user_id": current_user["_id"]})
    existing = set((profile or {}).get("photos") or [])
    if set(order) != existing:
        raise HTTPException(status_code=400, detail="order must contain exactly the current photo ids")
    await db[mongo.PROFILES].update_one(
        {"user_id": current_user["_id"]}, {"$set": {"photos": order}}
    )
    return {"photos": [mongo.photo_url(p) for p in order]}


@router.get("/photos/{file_id}")
async def get_photo(file_id: str):
    """Stream a stored photo by id."""
    try:
        oid = ObjectId(file_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Not found")
    bucket = mongo.gridfs()
    try:
        stream = await bucket.open_download_stream(oid)
        data = await stream.read()
    except Exception:
        raise HTTPException(status_code=404, detail="Photo not found")
    ct = (stream.metadata or {}).get("content_type", "image/jpeg")
    # Photos are keyed by an immutable id, so they can be cached aggressively. This lets the
    # app's URLCache serve them from disk instead of re-downloading on every redraw/scroll.
    return Response(content=data, media_type=ct,
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})
