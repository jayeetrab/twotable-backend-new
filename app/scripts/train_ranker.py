"""
Train the dating ranker from real swipe outcomes (learning-to-rank).

Every like/pass in the `likes` collection is a labelled example: the actor saw a
candidate and chose (like = 1, pass = 0). We rebuild the same feature vector the
live feed uses (semantic intent similarity + intent/lifestyle alignment +
distance + recency) and fit a logistic-regression model, then store the learned
weights in `ranker_model` (_id="dating"). The feed picks them up automatically
on the next request; until enough data exists it keeps the expert defaults.

Run:  python -m app.scripts.train_ranker
Pure numpy — no scikit-learn dependency.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import numpy as np

from app.db import mongo
from app.services import dating_match, embeddings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("train_ranker")

FEATURES = ["semantic", "intent_align", "lifestyle_align", "distance", "recency"]
MIN_SAMPLES = 30  # below this, defaults are better than an overfit model


async def _build_dataset():
    db = mongo.get_db()
    profiles = {p["user_id"]: p async for p in db[mongo.PROFILES].find({})}

    X, y = [], []
    async for like in db[mongo.LIKES].find({}):
        me = profiles.get(like["from_user_id"])
        cand = profiles.get(like["to_user_id"])
        if not me or not cand:
            continue
        mv, cv = me.get("intent_vector"), cand.get("intent_vector")
        sem = (embeddings.cosine(mv, cv) + 1.0) / 2.0 if (mv and cv) else 0.5
        feats = dating_match.build_features(me, cand, sem)
        X.append([feats[k] for k in FEATURES])
        y.append(1.0 if like.get("action") == "like" else 0.0)
    return np.array(X, dtype=np.float64), np.array(y, dtype=np.float64)


def _fit_logreg(X, y, epochs=4000, lr=0.1, l2=1e-3):
    """Plain batch gradient descent on logistic loss with L2."""
    n, d = X.shape
    w = np.zeros(d)
    b = 0.0
    for _ in range(epochs):
        z = X @ w + b
        p = 1.0 / (1.0 + np.exp(-z))
        err = p - y
        w -= lr * (X.T @ err / n + l2 * w)
        b -= lr * float(err.mean())
    return w, b


async def main():
    mongo.connect()
    X, y = await _build_dataset()
    n = len(y)
    pos = int(y.sum()) if n else 0
    logger.info("Dataset: %d samples (%d like, %d pass)", n, pos, n - pos)

    if n < MIN_SAMPLES or pos == 0 or pos == n:
        logger.warning("Not enough balanced data (need >= %d with both classes). "
                       "Keeping expert defaults.", MIN_SAMPLES)
        mongo.close()
        return

    w, b = _fit_logreg(X, y)
    weights = {k: round(float(wi), 4) for k, wi in zip(FEATURES, w)}
    await mongo.get_db()["ranker_model"].update_one(
        {"_id": "dating"},
        {"$set": {"weights": weights, "bias": round(float(b), 4),
                  "trained_at": datetime.now(timezone.utc), "samples": n}},
        upsert=True,
    )
    logger.info("Trained ranker stored. weights=%s bias=%.4f", weights, b)
    mongo.close()


if __name__ == "__main__":
    asyncio.run(main())
