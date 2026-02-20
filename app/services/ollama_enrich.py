from __future__ import annotations

import json
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "mistral"

PROMPT_TEMPLATE = """You are a restaurant data enrichment assistant for a dating app.

Given a venue name and cuisine type, return ONLY a valid JSON object with exactly these three fields:
- "description": string, 2-3 sentences describing ambiance and why it suits a date
- "vibe_tags": string, comma-separated tags chosen ONLY from: candlelit, intimate, cosy, buzzy, lively, romantic, quiet, trendy, rustic, modern, rooftop, hidden-gem, neighbourhood-gem, wine-bar, cocktail-bar, fine-dining, casual, outdoor, live-music
- "noise_level": string, MUST be exactly one of: quiet, moderate, lively

Venue name: {name}
Cuisine type: {cuisine}

Respond with only the JSON object, nothing else."""


def _parse_noise(raw: str) -> Optional[str]:
    raw = raw.lower()
    if "quiet" in raw or "low" in raw:
        return "quiet"
    if "lively" in raw or "high" in raw or "loud" in raw:
        return "lively"
    return "moderate"


def _parse_vibe_tags(raw) -> str:
    if isinstance(raw, list):
        return ", ".join(str(t).lower().strip() for t in raw)
    return str(raw).lower().strip()


async def enrich_venue_with_ollama(
    name: str,
    types_list: list[str],
    reviews: list,
    attributes: dict,
) -> dict:
    cuisine = types_list[0] if types_list else "restaurant"
    prompt = PROMPT_TEMPLATE.format(name=name, cuisine=cuisine)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                OLLAMA_URL,
                json={
                    "model": MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                },
            )
            response.raise_for_status()
            raw = response.json().get("response", "{}")
            data = json.loads(raw)
            return {
                "description": data.get("description", "").strip(),
                "vibe_tags":   _parse_vibe_tags(data.get("vibe_tags", "")),
                "noise_level": _parse_noise(data.get("noise_level", "moderate")),
            }
    except Exception as exc:
        logger.error("Ollama enrichment failed for %s: %s", name, exc)
        return {}
