"""
Local embedding provider + in-app cosine similarity for TwoTable.

- Provider: sentence-transformers ``all-MiniLM-L6-v2`` (384-dim, CPU, no API key).
- The model is loaded lazily on first use so the API boots instantly; the first
  /venues/suggest call pays the one-time load cost.
- Vectors are L2-normalised at encode time, so cosine similarity == dot product.
"""
from __future__ import annotations

import asyncio
import logging
from typing import List, Optional, Sequence

import numpy as np

from app.core.config import settings

logger = logging.getLogger(__name__)

_model = None  # lazily-loaded SentenceTransformer


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        logger.info("Loading embedding model '%s' (first use)…", settings.EMBEDDING_MODEL)
        _model = SentenceTransformer(settings.EMBEDDING_MODEL)
        logger.info("Embedding model loaded. dim=%d", settings.EMBEDDING_DIM)
    return _model


def _container_memory_mb() -> Optional[float]:
    """Best-effort container memory limit (MB). Reads cgroup limits (how Render/Docker cap
    RAM); returns None if it can't tell. Used to auto-protect small instances."""
    for path in ("/sys/fs/cgroup/memory.max",                       # cgroup v2
                 "/sys/fs/cgroup/memory/memory.limit_in_bytes"):    # cgroup v1
        try:
            with open(path) as f:
                raw = f.read().strip()
            if raw and raw != "max":
                mb = int(raw) / (1024 * 1024)
                if 0 < mb < 1_000_000:                              # ignore "unlimited" sentinels
                    return mb
        except Exception:
            continue
    return None


# Loading the sentence-transformers model needs ~1GB. Below this we refuse to load it even if
# EMBEDDING_PROVIDER=local, because trying would OOM the worker and hang the feed.
_MIN_MODEL_MEMORY_MB = 1200
_forced_off_logged = False


def _disabled() -> bool:
    """True when semantic embeddings should be skipped — either configured off, or the
    instance is too small to safely load the model.

    Matching degrades gracefully: semantic similarity goes neutral while every other
    signal (reciprocity, lifestyle, distance, recency) keeps ranking the feed.
    """
    if settings.EMBEDDING_PROVIDER.lower() in ("off", "none", "disabled"):
        return True
    mem = _container_memory_mb()
    if mem is not None and mem < _MIN_MODEL_MEMORY_MB:
        global _forced_off_logged
        if not _forced_off_logged:
            logger.warning(
                "EMBEDDING_PROVIDER=%s but only ~%dMB RAM (< %dMB) — forcing embeddings OFF to "
                "avoid OOM. Matching uses non-semantic signals. Use a >=2GB instance for semantics.",
                settings.EMBEDDING_PROVIDER, int(mem), _MIN_MODEL_MEMORY_MB)
            _forced_off_logged = True
        return True
    return False


async def embed(text: str) -> List[float]:
    if _disabled():
        return [0.0] * settings.EMBEDDING_DIM
    text = (text or "").replace("\n", " ").strip()
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(
            None,
            lambda: _get_model().encode(
                text, normalize_embeddings=True, show_progress_bar=False
            ).tolist(),
        )
    except Exception as exc:  # never let a model failure take the API down
        logger.error("embed failed (%s); returning neutral vector", exc)
        return [0.0] * settings.EMBEDDING_DIM


async def embed_batch(texts: Sequence[str]) -> List[List[float]]:
    if not texts:
        return []
    if _disabled():
        return [[0.0] * settings.EMBEDDING_DIM for _ in texts]
    cleaned = [(t or "").replace("\n", " ").strip() for t in texts]
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(
            None,
            lambda: _get_model().encode(
                cleaned, normalize_embeddings=True, batch_size=64, show_progress_bar=False
            ).tolist(),
        )
    except Exception as exc:
        logger.error("embed_batch failed (%s); returning neutral vectors", exc)
        return [[0.0] * settings.EMBEDDING_DIM for _ in texts]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity in [-1, 1]. Robust to non-normalised inputs."""
    va = np.asarray(a, dtype=np.float32)
    vb = np.asarray(b, dtype=np.float32)
    na = np.linalg.norm(va)
    nb = np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


# ── Text builders ─────────────────────────────────────────────────────────────

def build_venue_source_text(venue: dict) -> str:
    """Venue document → natural-language string for embedding."""
    raw_tags = venue.get("vibe_tags") or ""
    if isinstance(raw_tags, list):
        tags = [t.strip() for t in raw_tags if str(t).strip()]
    else:
        tags = [t.strip() for t in str(raw_tags).split(",") if t.strip()]

    parts: list[str] = [f"Venue: {venue.get('name', '')}", f"City: {venue.get('city', '')}"]
    if venue.get("cuisine"):
        parts.append(f"Cuisine: {venue['cuisine']}")
    if tags:
        parts.append(f"Vibes: {', '.join(tags)}")
    if venue.get("price_band"):
        parts.append(f"Price: {venue['price_band']}")
    if venue.get("noise_level"):
        parts.append(f"Noise: {venue['noise_level']}")
    if venue.get("description"):
        parts.append(f"Description: {venue['description']}")
    return ". ".join(parts) + "."


def build_intent_text(
    *, stage: str, mood: str, energy: str, budget: str, city: str, free_text: str = "",
) -> str:
    """User booking intent → natural-language string for embedding."""
    parts = [stage, f"Mood: {mood}", f"Energy: {energy}", f"Budget: {budget}", f"City: {city}"]
    if free_text:
        parts.append(free_text)
    return ". ".join(parts) + "."
