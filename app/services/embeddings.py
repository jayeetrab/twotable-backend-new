"""
Embedding provider abstraction for TwoTable.

Providers
---------
- local   : sentence-transformers all-MiniLM-L6-v2 (default)
            384-dim, runs on CPU, no API key, no rate limits.
- gemini  : google gemini-embedding-001
            768-dim, requires GEMINI_API_KEY.
            NOT used for venue/intent embeddings anymore.
            Kept for optional experimentation only.

Switch provider via EMBEDDING_PROVIDER in .env — zero code changes.
"""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import List

import numpy as np

from app.core.config import settings

logger = logging.getLogger(__name__)

TASK_DOCUMENT = "RETRIEVAL_DOCUMENT"
TASK_QUERY = "RETRIEVAL_QUERY"

_MAX_RETRIES = 3
_BASE_DELAY = 1.0


# ── Abstract interface ────────────────────────────────────────────────────────

class EmbeddingProvider(ABC):
    @abstractmethod
    async def embed(
        self,
        text: str,
        task_type: str = TASK_QUERY,
    ) -> List[float]: ...

    @abstractmethod
    async def embed_batch(
        self,
        texts: List[str],
        task_type: str = TASK_DOCUMENT,
    ) -> List[List[float]]: ...


# ── Normalisation ─────────────────────────────────────────────────────────────

def _l2_normalise(vector: List[float]) -> List[float]:
    arr = np.array(vector, dtype=np.float32)
    norm = np.linalg.norm(arr)
    if norm == 0:
        return vector
    return (arr / norm).tolist()


# ── Retry helper ──────────────────────────────────────────────────────────────

async def _with_retry(coro_fn, *args, **kwargs):
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            return await coro_fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            delay = _BASE_DELAY * (2 ** attempt)
            logger.warning(
                "Embedding call failed (attempt %d/%d): %s — retrying in %.1fs",
                attempt + 1, _MAX_RETRIES, exc, delay,
            )
            await asyncio.sleep(delay)
    raise last_exc


# ── Local provider (sentence-transformers) ────────────────────────────────────

class LocalEmbeddingProvider(EmbeddingProvider):
    """
    Runs all-MiniLM-L6-v2 (or any sentence-transformers model) locally.

    - No API key required
    - No rate limits
    - ~80MB RAM for MiniLM
    - ~5ms per embed on CPU
    - Model loaded once at startup, reused for every call
    - encode() is synchronous — wrapped in run_in_executor to avoid
      blocking the async event loop
    """

    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer
        logger.info(
            "Loading local embedding model '%s' — this takes a few seconds on first run.",
            settings.EMBEDDING_MODEL,
        )
        # normalize_embeddings=True at encode time handles L2 normalisation
        self._model = SentenceTransformer(settings.EMBEDDING_MODEL)
        self._dim = settings.EMBEDDING_DIM
        logger.info("Local embedding model loaded. dim=%d", self._dim)

    async def embed(
        self,
        text: str,
        task_type: str = TASK_QUERY,   # ignored — local models have no task type
    ) -> List[float]:
        text = text.replace("\n", " ").strip()
        loop = asyncio.get_event_loop()
        vector: List[float] = await loop.run_in_executor(
            None,
            lambda: self._model.encode(
                text,
                normalize_embeddings=True,
                show_progress_bar=False,
            ).tolist(),
        )
        return vector

    async def embed_batch(
        self,
        texts: List[str],
        task_type: str = TASK_DOCUMENT,  # ignored
    ) -> List[List[float]]:
        if not texts:
            return []
        cleaned = [t.replace("\n", " ").strip() for t in texts]
        loop = asyncio.get_event_loop()
        vectors: List[List[float]] = await loop.run_in_executor(
            None,
            lambda: self._model.encode(
                cleaned,
                normalize_embeddings=True,
                batch_size=64,
                show_progress_bar=False,
            ).tolist(),
        )
        return vectors


# ── Gemini provider (kept for optional use, not default) ──────────────────────

class GeminiEmbeddingProvider(EmbeddingProvider):
    """
    Uses google-genai async client.
    768-dim. Requires GEMINI_API_KEY.
    Not used by default — set EMBEDDING_PROVIDER=gemini to enable.
    """

    def __init__(self) -> None:
        from google import genai
        self._client = genai.Client(api_key=settings.GEMINI_API_KEY)
        self._model = settings.EMBEDDING_MODEL
        self._dim = settings.EMBEDDING_DIM
        self._normalise = self._dim < 3072

    async def _call_embed(
        self,
        contents: str | List[str],
        task_type: str,
    ) -> List[List[float]]:
        from google.genai import types as genai_types
        result = await self._client.aio.models.embed_content(
            model=self._model,
            contents=contents,
            config=genai_types.EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=self._dim,
            ),
        )
        vectors = [e.values for e in result.embeddings]
        if self._normalise:
            vectors = [_l2_normalise(v) for v in vectors]
        return vectors

    async def embed(self, text: str, task_type: str = TASK_QUERY) -> List[float]:
        text = text.replace("\n", " ").strip()
        vectors = await _with_retry(self._call_embed, text, task_type)
        return vectors[0]

    async def embed_batch(
        self,
        texts: List[str],
        task_type: str = TASK_DOCUMENT,
    ) -> List[List[float]]:
        if not texts:
            return []
        cleaned = [t.replace("\n", " ").strip() for t in texts]
        try:
            return await _with_retry(self._call_embed, cleaned, task_type)
        except Exception as exc:
            logger.error("Batch embed failed (%s). Falling back to sequential.", exc)
            return [await self.embed(t, task_type) for t in cleaned]


# ── Factory ───────────────────────────────────────────────────────────────────

def _build_provider() -> EmbeddingProvider:
    name = settings.EMBEDDING_PROVIDER.lower()
    if name == "local":
        return LocalEmbeddingProvider()
    if name == "gemini":
        return GeminiEmbeddingProvider()
    raise ValueError(
        f"Unknown EMBEDDING_PROVIDER='{name}'. "
        "Set EMBEDDING_PROVIDER=local or gemini in .env"
    )


# Module-level singleton — import this in all service modules
embedding_provider: EmbeddingProvider = _build_provider()


# ── Text builders ─────────────────────────────────────────────────────────────

def build_venue_source_text(venue) -> str:
    """
    Converts a Venue ORM row → natural language string for RETRIEVAL_DOCUMENT.
    vibe_tags is stored as a comma-separated string.
    """
    raw_tags = venue.vibe_tags or ""
    if isinstance(raw_tags, list):
        tags = [t.strip() for t in raw_tags if t.strip()]
    else:
        tags = [t.strip() for t in raw_tags.split(",") if t.strip()]

    parts: list[str] = [f"Venue: {venue.name}", f"City: {venue.city}"]
    if getattr(venue, "cuisine", None):
        parts.append(f"Cuisine: {venue.cuisine}")
    if tags:
        parts.append(f"Vibes: {', '.join(tags)}")
    if getattr(venue, "price_band", None):
        band = venue.price_band.value if hasattr(venue.price_band, "value") else venue.price_band
        parts.append(f"Price: {band}")
    if getattr(venue, "noise_level", None):
        level = venue.noise_level.value if hasattr(venue.noise_level, "value") else venue.noise_level
        parts.append(f"Noise: {level}")
    if getattr(venue, "description", None):
        parts.append(f"Description: {venue.description}")
    return ". ".join(parts) + "."


def build_intent_text(
    *,
    stage: str,
    mood: str,
    energy: str,
    budget: str,
    city: str,
    free_text: str = "",
) -> str:
    """
    Converts user booking intent → natural language string for RETRIEVAL_QUERY.
    """
    parts = [
        f"{stage}",
        f"Mood: {mood}",
        f"Energy: {energy}",
        f"Budget: {budget}",
        f"City: {city}",
    ]
    if free_text:
        parts.append(free_text)
    return ". ".join(parts) + "."
