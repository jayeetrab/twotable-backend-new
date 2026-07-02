import asyncio
from app.db import mongo
from app.api.v1.discovery import feed
from fastapi import Request

class MockUser:
    def __init__(self, uid):
        self._id = uid
    def __getitem__(self, item):
        if item == "_id": return self._id
        return None

async def main():
    mongo.connect()
    db = mongo.get_db()
    me_user = await db[mongo.USERS].find_one({"role": "dater"}, sort=[("created_at", -1)])
    if not me_user:
        return
    res = await feed(limit=20, current_user=me_user)
    print("Feed response count:", res["count"])
    for p in res.get("profiles", []):
        print(f"{p['name']}: {len(p['photos'])} photos")
    mongo.close()

asyncio.run(main())
