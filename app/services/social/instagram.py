from __future__ import annotations

"""
Instagram Basic Display API analysis pipeline.

Flow:
1. Fetch recent media (captions, image URLs) using the user's access token
2. Run image analysis on each photo via Groq vision (or GPT-4o Vision)
3. Run text analysis on captions + bio via Groq LLM
4. Return a structured list of SocialSignal dicts

Real Instagram OAuth is handled in the API layer (profile.py).
This service assumes we already have a valid access_token.
"""

import json
import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

INSTAGRAM_GRAPH_URL = "https://graph.instagram.com/v21.0"

# Signal types this pipeline emits
SIGNAL_AESTHETIC        = "aesthetic"
SIGNAL_ACTIVITY         = "activity"
SIGNAL_PERSONALITY      = "personality_trait"
SIGNAL_COMMUNICATION    = "communication_style"
SIGNAL_MUSIC_GENRE      = "music_genre"      # extracted from captions / hashtags


async def fetch_instagram_media(
    access_token: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """
    Fetch the user's recent Instagram posts.
    Returns list of {id, caption, media_url, media_type, timestamp}.
    """
    url = f"{INSTAGRAM_GRAPH_URL}/me/media"
    params = {
        "fields": "id,caption,media_url,media_type,timestamp",
        "limit": limit,
        "access_token": access_token,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, params=params)
        if resp.status_code != 200:
            logger.error(
                "Instagram media fetch failed: %d %s", resp.status_code, resp.text
            )
            return []
        data = resp.json()
        return data.get("data", [])


async def fetch_instagram_profile(access_token: str) -> dict[str, Any]:
    """Fetch the user's Instagram username and bio (account_type)."""
    url = f"{INSTAGRAM_GRAPH_URL}/me"
    params = {
        "fields": "id,username,account_type",
        "access_token": access_token,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, params=params)
        if resp.status_code != 200:
            return {}
        return resp.json()


async def analyse_instagram_images_with_groq(
    image_urls: list[str],
    groq_api_key: str,
) -> dict[str, Any]:
    """
    Send image URLs to Groq llama-3.2-90b-vision-preview for aesthetic + activity extraction.
    Returns {"aesthetic": [...], "activities": [...]}.

    Groq Vision is free-tier available as of 2025.
    Fallback: if Groq Vision is not available, returns empty dict (graceful degradation).
    """
    if not image_urls or not groq_api_key:
        return {}

    # Send up to 6 images (Groq Vision supports multi-image in one request)
    sample_urls = image_urls[:6]

    content: list[dict] = [
        {
            "type": "text",
            "text": (
                "You are analysing a person's Instagram photos to understand their "
                "aesthetic preferences and lifestyle. Look at all images together.\n\n"
                "Return ONLY valid JSON with this exact structure:\n"
                '{"aesthetic": ["tag1", "tag2"], "activities": ["tag1", "tag2"]}\n\n'
                "aesthetic tags: visual style/mood of their photos "
                "(e.g. warm tones, moody, minimalist, colourful, urban, nature, cosy interiors)\n"
                "activities tags: real-world activities visible "
                "(e.g. hiking, coffee shops, art galleries, travel, cooking, concerts)\n"
                "Max 5 tags each. Only return the JSON, nothing else."
            ),
        }
    ]
    for url in sample_urls:
        content.append({"type": "image_url", "image_url": {"url": url}})

    payload = {
        "model": "llama-3.2-90b-vision-preview",
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.2,
        "max_tokens": 200,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {groq_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if resp.status_code != 200:
                logger.error("Groq Vision failed: %d %s", resp.status_code, resp.text)
                return {}
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw)
    except Exception as exc:
        logger.error("Groq Vision image analysis error: %s", exc)
        return {}


async def analyse_instagram_captions_with_groq(
    captions: list[str],
    bio: str,
    groq_api_key: str,
) -> dict[str, Any]:
    """
    Run LLM text analysis on captions + bio.
    Returns {"personality_traits": [...], "communication_style": str,
             "interests": [...], "music_genres": [...]}.
    """
    if not groq_api_key:
        return {}

    combined_text = "\n".join(filter(None, captions[:15]))
    if not combined_text.strip() and not bio.strip():
        return {}

    prompt = (
        "You are analysing a person's Instagram captions and bio to extract "
        "personality and interest signals for a dating app.\n\n"
        f"Bio: {bio or 'not provided'}\n\n"
        f"Recent captions:\n{combined_text or 'not provided'}\n\n"
        "Return ONLY valid JSON with this exact structure:\n"
        '{"personality_traits": ["trait1", "trait2"], '
        '"communication_style": "deep_talker|light_banter|mix", '
        '"interests": ["interest1", "interest2"], '
        '"music_genres": ["genre1", "genre2"]}\n\n'
        "personality_traits: e.g. reflective, humorous, adventurous, creative, introverted\n"
        "communication_style: pick exactly one of: deep_talker, light_banter, mix\n"
        "interests: topics they clearly care about\n"
        "music_genres: only if mentioned in captions/hashtags, else empty list\n"
        "Max 5 items per list. Only return JSON, nothing else."
    )

    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 300,
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {groq_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if resp.status_code != 200:
                logger.error("Groq caption analysis failed: %d", resp.status_code)
                return {}
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw)
    except Exception as exc:
        logger.error("Groq caption analysis error: %s", exc)
        return {}


def build_instagram_signals(
    image_analysis: dict[str, Any],
    caption_analysis: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Convert raw LLM outputs into a flat list of signal dicts ready
    to be stored as UserSocialSignal rows.

    Each dict: {platform, signal_type, signal_value, confidence}
    """
    signals: list[dict[str, Any]] = []

    # From image analysis
    for tag in image_analysis.get("aesthetic", []):
        if tag.strip():
            signals.append({
                "platform": "instagram",
                "signal_type": SIGNAL_AESTHETIC,
                "signal_value": tag.strip().lower(),
                "confidence": 0.8,
            })
    for tag in image_analysis.get("activities", []):
        if tag.strip():
            signals.append({
                "platform": "instagram",
                "signal_type": SIGNAL_ACTIVITY,
                "signal_value": tag.strip().lower(),
                "confidence": 0.8,
            })

    # From caption analysis
    for trait in caption_analysis.get("personality_traits", []):
        if trait.strip():
            signals.append({
                "platform": "instagram",
                "signal_type": SIGNAL_PERSONALITY,
                "signal_value": trait.strip().lower(),
                "confidence": 0.7,
            })

    comm = caption_analysis.get("communication_style", "").strip()
    if comm in ("deep_talker", "light_banter", "mix"):
        signals.append({
            "platform": "instagram",
            "signal_type": SIGNAL_COMMUNICATION,
            "signal_value": comm,
            "confidence": 0.75,
        })

    for genre in caption_analysis.get("music_genres", []):
        if genre.strip():
            signals.append({
                "platform": "instagram",
                "signal_type": SIGNAL_MUSIC_GENRE,
                "signal_value": genre.strip().lower(),
                "confidence": 0.65,
            })

    return signals
