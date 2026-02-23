from __future__ import annotations

"""
Spotify Web API analysis pipeline.

Flow:
1. Fetch top artists + top tracks (short_term = last 4 weeks)
2. Fetch audio features for top tracks (energy, valence, tempo, danceability)
3. Derive: music_genres, energy_level, valence_label, tempo_preference
4. Return structured signal list

This service assumes we already have a valid access_token from OAuth.
"""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

SPOTIFY_API_URL = "https://api.spotify.com/v1"

# Signal types this pipeline emits
SIGNAL_MUSIC_GENRE      = "music_genre"
SIGNAL_ENERGY           = "energy_level"      # value: "low" / "medium" / "high"
SIGNAL_VALENCE          = "valence"           # value: "melancholic" / "neutral" / "upbeat"
SIGNAL_TEMPO            = "tempo_preference"  # value: "slow" / "moderate" / "fast"
SIGNAL_DANCEABILITY     = "danceability"      # value: "low" / "medium" / "high"
SIGNAL_TOP_ARTIST       = "top_artist"


async def fetch_top_artists(
    access_token: str,
    limit: int = 10,
    time_range: str = "medium_term",  # short_term / medium_term / long_term
) -> list[dict[str, Any]]:
    """Returns list of top artist objects with name + genres."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{SPOTIFY_API_URL}/me/top/artists",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"limit": limit, "time_range": time_range},
        )
        if resp.status_code != 200:
            logger.error("Spotify top artists failed: %d %s", resp.status_code, resp.text)
            return []
        return resp.json().get("items", [])


async def fetch_top_tracks(
    access_token: str,
    limit: int = 20,
    time_range: str = "medium_term",
) -> list[dict[str, Any]]:
    """Returns list of top track objects with id + name."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{SPOTIFY_API_URL}/me/top/tracks",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"limit": limit, "time_range": time_range},
        )
        if resp.status_code != 200:
            logger.error("Spotify top tracks failed: %d", resp.status_code)
            return []
        return resp.json().get("items", [])


async def fetch_audio_features(
    access_token: str,
    track_ids: list[str],
) -> list[dict[str, Any]]:
    """Batch-fetch audio features for up to 100 tracks."""
    if not track_ids:
        return []
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{SPOTIFY_API_URL}/audio-features",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"ids": ",".join(track_ids[:100])},
        )
        if resp.status_code != 200:
            logger.error("Spotify audio features failed: %d", resp.status_code)
            return []
        return [f for f in resp.json().get("audio_features", []) if f]


def _bucket(value: float, low: float, high: float) -> str:
    """Convert a 0–1 float into low/medium/high label."""
    if value < low:
        return "low"
    if value < high:
        return "medium"
    return "high"


def derive_audio_signals(features: list[dict[str, Any]]) -> dict[str, str]:
    """
    Average audio features across all tracks and derive
    human-readable labels.
    """
    if not features:
        return {}

    avg_energy      = sum(f.get("energy",       0) for f in features) / len(features)
    avg_valence     = sum(f.get("valence",       0) for f in features) / len(features)
    avg_tempo       = sum(f.get("tempo",         0) for f in features) / len(features)
    avg_dance       = sum(f.get("danceability",  0) for f in features) / len(features)

    valence_label = (
        "melancholic" if avg_valence < 0.35
        else "upbeat" if avg_valence > 0.65
        else "neutral"
    )
    tempo_label = (
        "slow"     if avg_tempo < 90
        else "fast" if avg_tempo > 140
        else "moderate"
    )

    return {
        "energy_level":      _bucket(avg_energy, 0.35, 0.65),
        "valence":           valence_label,
        "tempo_preference":  tempo_label,
        "danceability":      _bucket(avg_dance, 0.35, 0.65),
    }


def build_spotify_signals(
    top_artists: list[dict[str, Any]],
    audio_signals: dict[str, str],
) -> list[dict[str, Any]]:
    """
    Convert Spotify data into flat signal dicts ready for DB storage.
    Each dict: {platform, signal_type, signal_value, confidence}
    """
    signals: list[dict[str, Any]] = []

    # Collect unique genres from all top artists (Spotify provides them per artist)
    seen_genres: set[str] = set()
    for artist in top_artists:
        for genre in artist.get("genres", []):
            g = genre.strip().lower()
            if g and g not in seen_genres:
                seen_genres.add(g)
                signals.append({
                    "platform": "spotify",
                    "signal_type": SIGNAL_MUSIC_GENRE,
                    "signal_value": g,
                    "confidence": 0.9,
                })

    # Top artist names (for later embedding enrichment)
    for artist in top_artists[:5]:
        name = artist.get("name", "").strip()
        if name:
            signals.append({
                "platform": "spotify",
                "signal_type": SIGNAL_TOP_ARTIST,
                "signal_value": name,
                "confidence": 0.95,
            })

    # Audio-derived signals
    type_map = {
        "energy_level":     SIGNAL_ENERGY,
        "valence":          SIGNAL_VALENCE,
        "tempo_preference": SIGNAL_TEMPO,
        "danceability":     SIGNAL_DANCEABILITY,
    }
    for key, signal_type in type_map.items():
        value = audio_signals.get(key)
        if value:
            signals.append({
                "platform": "spotify",
                "signal_type": signal_type,
                "signal_value": value,
                "confidence": 0.85,
            })

    return signals
