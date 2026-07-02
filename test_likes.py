import asyncio
from app.db import mongo

async def main():
    mongo.connect()
    db = mongo.get_db()
    
    users = await db[mongo.USERS].find({"role": "dater"}).to_list(None)
    for me in users:
        likes = await db[mongo.LIKES].count_documents({"from_user_id": me["_id"]})
        if likes > 0:
            print(f"User {me.get('full_name')} ({me['_id']}) has {likes} actions (likes/passes).")
            
    mongo.close()

asyncio.run(main())
