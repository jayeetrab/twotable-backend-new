"""
TwoTable Redis cache.

Namespaced keys: twotable:{namespace}:{key}
All values serialised as JSON.

Local dev:   redis://localhost:6379/0
Production:  Upstash or Render Redis — set REDIS_URL in .env
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from redis.asyncio import ConnectionPool, Redis

from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Single connection pool shared across the whole app ────────────────────────
_pool: Optional[ConnectionPool] = None


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool.from_url(
            settings.REDIS_URL,
            max_connections=20,
            decode_responses=True,
        )
    return _pool


def get_redis() -> Redis:
    return Redis(connection_pool=_get_pool())


# ── Generic async cache class ─────────────────────────────────────────────────

class RedisCache:
    """
    Async TTL cache backed by Redis.
    All methods are async — call with await.
    """

    def __init__(self, namespace: str, default_ttl_seconds: int = 300):
        self.ns  = namespace
        self.ttl = default_ttl_seconds

    def _key(self, key: str) -> str:
        return f"twotable:{self.ns}:{key}"

    async def get(self, key: str) -> Optional[Any]:
        try:
            r   = get_redis()
            raw = await r.get(self._key(key))
            if raw is None:
                logger.debug("[%s] MISS %s", self.ns, key[:30])
                return None
            logger.debug("[%s] HIT  %s", self.ns, key[:30])
            return json.loads(raw)
        except Exception as exc:
            logger.warning("[%s] get failed — %s", self.ns, exc)
            return None   # degrade gracefully, never crash

    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: Optional[int] = None,
    ) -> None:
        try:
            r   = get_redis()
            ttl = ttl_seconds if ttl_seconds is not None else self.ttl
            await r.setex(self._key(key), ttl, json.dumps(value))
            logger.debug("[%s] SET  %s (ttl=%ds)", self.ns, key[:30], ttl)
        except Exception as exc:
            logger.warning("[%s] set failed — %s", self.ns, exc)

    async def delete(self, key: str) -> None:
        try:
            r = get_redis()
            await r.delete(self._key(key))
        except Exception as exc:
            logger.warning("[%s] delete failed — %s", self.ns, exc)

    async def clear(self) -> None:
        try:
            r       = get_redis()
            pattern = f"twotable:{self.ns}:*"
            keys    = await r.keys(pattern)
            if keys:
                await r.delete(*keys)
            logger.info("[%s] Cleared %d keys", self.ns, len(keys or []))
        except Exception as exc:
            logger.warning("[%s] clear failed — %s", self.ns, exc)

    async def stats(self) -> dict:
        try:
            r    = get_redis()
            keys = await r.keys(f"twotable:{self.ns}:*")
            return {"cache": self.ns, "live_entries": len(keys)}
        except Exception as exc:
            return {"cache": self.ns, "error": str(exc)}


# ── Shared instances — import these everywhere ────────────────────────────────

available_venues_cache = RedisCache("available_venues", default_ttl_seconds=300)   # 5 min
haversine_cache        = RedisCache("haversine",        default_ttl_seconds=3600)  # 1 hr
intent_vector_cache    = RedisCache("intent_vectors",   default_ttl_seconds=3600)  # 1 hr
suggest_cache          = RedisCache("suggest_results",  default_ttl_seconds=300)   # 5 min
