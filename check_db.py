import asyncio
from app.db import mongo

async def main():
    mongo.connect()
    db = mongo.get_db()
    daters = await db[mongo.USERS].count_documents({"role": "dater"})
    print(f"Daters count: {daters}")
    mongo.close()

asyncio.run(main())
