import asyncio
from app.db import mongo

async def main():
    mongo.connect()
    db = mongo.get_db()
    
    # Give all DATERS a gender
    for phone in ["+447900000001", "+447900000002", "+447900000003", "+447900000004", "+447900000005", "+447900000006", "+447900000007", "+447900000008"]:
        user = await db[mongo.USERS].find_one({"phone": phone})
        if user:
            await db[mongo.USERS].update_one({"_id": user["_id"]}, {"$set": {"gender": "Woman"}})
            await db[mongo.PROFILES].update_one({"user_id": user["_id"]}, {"$set": {"gender": "Woman", "onboarding_raw.gender": "Woman"}})
    
    print("Fixed genders")
    mongo.close()

asyncio.run(main())
