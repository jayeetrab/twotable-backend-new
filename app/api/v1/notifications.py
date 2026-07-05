"""
Notifications feed — derived, not stored.

Rather than maintain a separate notifications collection, we synthesise the user's feed from
the data that already exists: mutual matches, pending admirers (who likes you), and date-plan
milestones (confirmed / coming up). Each item is timestamped so the client can sort and show an
unread badge against a locally-stored "last seen" time.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends

from app.api.v1.dates import PLANS
from app.core.deps import get_current_user
from app.db import mongo

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _iso(dt) -> Optional[str]:
    if isinstance(dt, datetime):
        return dt.replace(tzinfo=dt.tzinfo or timezone.utc).isoformat()
    return None


async def _name(db, user_id: int) -> str:
    u = await db[mongo.USERS].find_one({"_id": user_id}, {"full_name": 1})
    return (u or {}).get("full_name") or "Someone"


@router.get("")
async def notifications(current_user: dict = Depends(get_current_user)):
    """Newest-first feed of matches, admirers and date milestones for the current user."""
    db = mongo.get_db()
    me = current_user["_id"]
    items: list[dict] = []

    # Mutual matches.
    async for c in db[mongo.CONNECTIONS].find(
        {"$or": [{"user_a_id": me}, {"user_b_id": me}]}).sort("created_at", -1).limit(30):
        other = c["user_b_id"] if c["user_a_id"] == me else c["user_a_id"]
        items.append({
            "type": "match", "icon": "heart",
            "title": "New match",
            "body": f"You and {await _name(db, other)} liked each other. Plan a date!",
            "created_at": _iso(c.get("created_at")), "user_id": other,
        })

    # Pending admirers (someone liked me, I haven't responded) — one summary item.
    admirer_ids = [d["from_user_id"] async for d in db[mongo.LIKES].find(
        {"to_user_id": me, "action": "like"})]
    if admirer_ids:
        actioned = {d["to_user_id"] async for d in db[mongo.LIKES].find(
            {"from_user_id": me, "to_user_id": {"$in": admirer_ids}})}
        pending = [i for i in admirer_ids if i not in actioned]
        if pending:
            latest = await db[mongo.LIKES].find_one(
                {"to_user_id": me, "from_user_id": {"$in": pending}, "action": "like"},
                sort=[("created_at", -1)])
            n = len(pending)
            items.append({
                "type": "likes", "icon": "sparkles",
                "title": "Someone likes you" if n == 1 else f"{n} people like you",
                "body": "Like them back to match instantly.",
                "created_at": _iso((latest or {}).get("created_at")), "user_id": None,
            })

    # Date-plan milestones (confirmed + coming up).
    now = datetime.now(timezone.utc)
    async for p in db[PLANS].find(
        {"$or": [{"user_a_id": me}, {"user_b_id": me}], "status": "confirmed"}).limit(30):
        other = p["user_b_id"] if p["user_a_id"] == me else p["user_a_id"]
        name = await _name(db, other)
        venue = await db[mongo.VENUES].find_one({"_id": p.get("agreed_venue_id")}, {"name": 1})
        vname = (venue or {}).get("name") or "your restaurant"
        items.append({
            "type": "date_confirmed", "icon": "checkmark.seal",
            "title": "Your table is booked",
            "body": f"Dinner with {name} at {vname} is confirmed.",
            "created_at": _iso(p.get("updated_at") or p.get("created_at")), "user_id": other,
        })
        # Reminder if the agreed slot is within the next 48 hours.
        try:
            slot = datetime.fromisoformat(p["agreed_slot"]).replace(tzinfo=timezone.utc)
            if now < slot <= now + timedelta(hours=48):
                items.append({
                    "type": "reminder", "icon": "clock",
                    "title": "Date coming up",
                    "body": f"Your dinner with {name} is soon. Getting there on time matters!",
                    "created_at": _iso(now), "user_id": other,
                })
        except Exception:
            pass

    items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return {"count": len(items), "notifications": items}
