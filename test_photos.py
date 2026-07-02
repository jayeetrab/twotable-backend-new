import asyncio
from app.db import mongo

async def main():
    mongo.connect()
    db = mongo.get_db()
    profs = await db[mongo.PROFILES].find({"onboarding_raw.first_name": "Maya"}).to_list(length=1)
    if profs:
        print(profs[0].get("photos"))
    mongo.close()

asyncio.run(main())
