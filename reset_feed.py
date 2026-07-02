import asyncio
from app.db import mongo

async def main():
    mongo.connect()
    db = mongo.get_db()
    await db[mongo.LIKES].delete_many({})
    await db[mongo.CONNECTIONS].delete_many({})
    print("Deleted all likes and connections. Feed should be reset.")
    mongo.close()

asyncio.run(main())
