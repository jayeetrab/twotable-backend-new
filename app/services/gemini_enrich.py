import asyncio
import json
import logging
import re
from typing import Any

from google import genai
from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Controlled vocabulary ─────────────────────────────────────────────────────

_VALID_NOISE_LEVELS = {"quiet", "moderate", "lively", "loud"}

_VALID_VIBE_TAGS = {
    "romantic", "intimate", "lively", "cosy", "trendy",
    "fine dining", "casual", "quiet", "outdoor", "date night",
    "hidden gem", "award-winning", "group friendly", "wine bar",
}

_GENERIC_SUFFIX = "is a restaurant in Bristol."


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_response(raw: str) -> dict:
    """Extract JSON from Gemini response — handles markdown fences."""
    clean = re.sub(r"```(?:json)?", "", raw).strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", clean, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    logger.warning("Could not parse Gemini JSON: %s", raw[:200])
    return {}


def _sanitise_tags(raw: Any) -> str:
    if isinstance(raw, list):
        tags = [str(t).strip().lower() for t in raw]
    elif isinstance(raw, str):
        tags = [t.strip().lower() for t in raw.split(",")]
    else:
        return "date night"
    valid = [t for t in tags if t in _VALID_VIBE_TAGS]
    return ", ".join(valid[:6]) if valid else "date night"


def _sanitise_noise(raw: Any) -> str:
    if isinstance(raw, str) and raw.strip().lower() in _VALID_NOISE_LEVELS:
        return raw.strip().lower()
    return "moderate"


def _fallback(name: str, venue_type: str = "restaurant") -> dict:
    return {
        "noise_level": "moderate",
        "vibe_tags": "date night",
        "description": (
            f"A {venue_type.lower()} in Bristol with a welcoming atmosphere. "
            f"A good choice for a relaxed date night in the city."
        ),
    }


# ── Main enrichment function ──────────────────────────────────────────────────

async def enrich_venue_with_gemini(
    name: str,
    types_list: list[str],
    reviews: list[str],
    attributes: dict,
) -> dict:
    """
    Call Gemini to generate noise_level, vibe_tags, description for a venue.
    Always returns a dict — never raises. Falls back to safe defaults on error.
    """
    if not settings.GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not set — returning fallback for '%s'", name)
        return _fallback(name)

    venue_type = ", ".join(types_list) if types_list else "restaurant"
    reviews_text = (
        "\n".join(f"- {r}" for r in reviews[:5])
        if reviews else "No reviews available."
    )
    attrs_text = ", ".join(
        k for k, v in attributes.items()
        if v is True and not isinstance(v, dict)
    )
    tag_vocab = ", ".join(sorted(_VALID_VIBE_TAGS))

    prompt = f"""You are enriching a restaurant profile for TwoTable, a romantic date-night dining app in Bristol.

Restaurant: {name}
Google Types: {venue_type}
Attributes: {attrs_text}
Customer Reviews:
{reviews_text}

Return ONLY valid JSON with these exact keys:
{{
  "noise_level": "quiet | moderate | lively | loud",
  "vibe_tags": "comma-separated max 6 tags chosen ONLY from: {tag_vocab}",
  "description": "Exactly 2 sentences. TwoTable marketing tone. Focus on date night experience. Do NOT start with the venue name."
}}

Return ONLY the JSON object, no markdown, no explanation."""

    try:
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-2.0-flash",
            contents=prompt,
        )
        raw = response.text.strip()
        logger.debug("Gemini raw for '%s': %s", name, raw[:300])

        parsed = _parse_response(raw)

        noise       = _sanitise_noise(parsed.get("noise_level"))
        vibe_tags   = _sanitise_tags(parsed.get("vibe_tags", ""))
        description = parsed.get("description", "").strip()

        # Reject description if it's still generic or starts with venue name
        if (
            not description
            or description.lower().endswith(_GENERIC_SUFFIX)
            or description.lower().startswith(name.lower())
        ):
            logger.warning(
                "Gemini description for '%s' is generic — using fallback description",
                name,
            )
            description = _fallback(name, venue_type)["description"]

        return {
            "noise_level": noise,
            "vibe_tags":   vibe_tags,
            "description": description,
        }

    except Exception as exc:
        logger.error("Gemini enrichment failed for '%s': %s", name, exc)
        return _fallback(name)
