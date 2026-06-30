"""
Compute similarity vectors for venues that don't have one yet.

Run after seeding (or any time new venues are added) to enable semantic
ranking in /venues/suggest. Uses the local MiniLM model + L2-normalised
vectors so the matcher's in-app cosine is meaningful.

Usage:
    python -m app.scripts.embed_venues
    python -m app.scripts.embed_venues --reembed   # recompute all
"""
from __future__ import annotations

import argparse
import asyncio

from app.db import mongo
from app.services import embeddings

_BATCH = 64


async def run(reembed: bool) -> None:
    mongo.connect()
    db = mongo.get_db()
    query = {} if reembed else {"embedding": {"$exists": False}}
    docs = await db[mongo.VENUES].find(query).to_list(length=None)
    print(f"📦 {len(docs)} venues to embed")

    done = 0
    for i in range(0, len(docs), _BATCH):
        batch = docs[i:i + _BATCH]
        texts = [embeddings.build_venue_source_text(d) for d in batch]
        vectors = await embeddings.embed_batch(texts)
        for d, text, vec in zip(batch, texts, vectors):
            await db[mongo.VENUES].update_one(
                {"_id": d["_id"]},
                {"$set": {"source_text": text, "embedding": vec}},
            )
        done += len(batch)
        print(f"  …{done}/{len(docs)}")

    print(f"✅ Embedded {done} venues")
    mongo.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reembed", action="store_true", help="Recompute all vectors")
    args = parser.parse_args()
    asyncio.run(run(reembed=args.reembed))
