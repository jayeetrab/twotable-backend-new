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


async def embed(text: str) -> List[float]:
    text = (text or "").replace("\n", " ").strip()
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: _get_model().encode(
            text, normalize_embeddings=True, show_progress_bar=False
        ).tolist(),
    )


async def embed_batch(texts: Sequence[str]) -> List[List[float]]:
    if not texts:
        return []
    cleaned = [(t or "").replace("\n", " ").strip() for t in texts]
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: _get_model().encode(
            cleaned, normalize_embeddings=True, batch_size=64, show_progress_bar=False
        ).tolist(),
    )


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
