"""
TwoTable dating match engine — reciprocal *intent* matching.

This is deliberately not keyword overlap. Each user is turned into a single
natural-language "intent document" (bio + prompt answers + what they're looking
for + values + interests), embedded into a semantic vector, and two people are
scored on what they *mean*, so "love quiet nights in with a book" matches
"homebody who reads" with zero shared words.

The final match score blends several signals through a small logistic model
whose weights are expert-tuned by default but can be retrained from real swipe
outcomes (learning-to-rank). Scoring is two-sided: a candidate only appears if
*both* people's hard preferences (gender/who-you-date) are satisfied, and the
ranking approximates P(both like).

Pure-python + numpy; no API keys. Embeddings come from app.services.embeddings.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Optional

from app.services import embeddings
from app.services.geo import haversine_km

# ── Profile field access ──────────────────────────────────────────────────────
# The app stores the full answer set under profile["onboarding_raw"]; a few fields
# are also mirrored at the top level. These helpers read whichever is present.

def _raw(profile: dict) -> dict:
    return profile.get("onboarding_raw") or {}


def _as_list(v: Any) -> list[str]:
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str) and v.strip():
        return [v.strip()]
    return []


def _facts(profile: dict) -> dict:
    f = _raw(profile).get("facts")
    return f if isinstance(f, dict) else {}


def _fact(profile: dict, key: str) -> Optional[str]:
    vals = _facts(profile).get(key)
    if isinstance(vals, list) and vals:
        return str(vals[0])
    if isinstance(vals, str) and vals:
        return vals
    return None


# ── Intent document → embedding ───────────────────────────────────────────────

def build_intent_text(profile: dict, full_name: str = "") -> str:
    """Fuse the free-text + selections that express who someone is and wants."""
    raw = _raw(profile)
    parts: list[str] = []

    bio = (raw.get("bio") or profile.get("bio") or "").strip()
    if bio:
        parts.append(f"About me: {bio}")

    looking_for = _as_list(raw.get("intentions"))
    if looking_for:
        parts.append("Looking for: " + ", ".join(looking_for))

    values = _as_list(raw.get("date_values")) + _as_list(raw.get("wow_values"))
    if values:
        parts.append("I value: " + ", ".join(values))

    interests = _as_list(raw.get("interests"))
    if interests:
        parts.append("Interests: " + ", ".join(interests))

    # Free-text prompt answers carry the most personality — weight them by including all.
    prompts = raw.get("prompts")
    if isinstance(prompts, list):
        for p in prompts:
            if isinstance(p, dict) and p.get("answer"):
                key = (p.get("key") or "").replace("_", " ")
                parts.append(f"{key}: {p['answer']}".strip(": ").strip())

    ideal = raw.get("ideal_time")
    if isinstance(ideal, str) and ideal.strip():
        parts.append(f"Ideal date: {ideal.strip()}")

    if not parts:
        parts.append("New here, open to meeting someone over dinner.")
    return ". ".join(parts) + "."


async def compute_intent_vector(profile: dict, full_name: str = "") -> list[float]:
    return await embeddings.embed(build_intent_text(profile, full_name))


# ── Hard reciprocal filter (gender / who-you-date) ────────────────────────────

def _gender_category(gender: Optional[str]) -> Optional[str]:
    if not gender:
        return None
    g = gender.lower()
    if "non" in g or "nonconv" in g or "nonconforming" in g:
        return "nonbinary"
    if "woman" in g or "female" in g:   # covers "Transgender woman"
        return "woman"
    if "man" in g or "male" in g:       # covers "Transgender Man"
        return "man"
    return "nonbinary"


def _wants(pref: list[str], category: Optional[str]) -> bool:
    """Does this preference list accept someone of `category`? Permissive when unknown."""
    if not pref:
        return True                      # no preference set → don't exclude (demo-friendly)
    norm = {p.lower() for p in pref}
    if any("every" in p for p in norm):  # "Everyone"
        return True
    if category is None:
        return True
    if category == "woman":
        return any("woman" in p for p in norm)
    if category == "man":
        return any(p == "man" or p.startswith("man") for p in norm)
    if category == "nonbinary":
        return any("non" in p for p in norm)
    return True


def reciprocal_ok(me: dict, cand: dict) -> bool:
    """True if each person's who-you-date preference admits the other's gender."""
    my_pref = _as_list(_raw(me).get("date_preferences"))
    cand_pref = _as_list(_raw(cand).get("date_preferences"))
    my_cat = _gender_category(_raw(me).get("gender") or me.get("gender"))
    cand_cat = _gender_category(_raw(cand).get("gender") or cand.get("gender"))
    return _wants(my_pref, cand_cat) and _wants(cand_pref, my_cat)


# ── Soft-signal feature builders (each returns 0..1) ──────────────────────────

def _overlap(a: list[str], b: list[str]) -> float:
    sa, sb = {x.lower() for x in a}, {x.lower() for x in b}
    if not sa or not sb:
        return 0.5                       # unknown → neutral
    return len(sa & sb) / len(sa | sb)   # Jaccard


def _agree(a: Optional[str], b: Optional[str]) -> Optional[float]:
    if not a or not b:
        return None
    return 1.0 if a.strip().lower() == b.strip().lower() else 0.0


def lifestyle_alignment(me: dict, cand: dict) -> float:
    """Average agreement across lifestyle facts that both people answered."""
    keys = ["drink", "smokeCigarette", "weed", "drugs", "children", "religion", "politics", "education"]
    scores = [s for k in keys if (s := _agree(_fact(me, k), _fact(cand, k))) is not None]
    return sum(scores) / len(scores) if scores else 0.5


def distance_score(me: dict, cand: dict) -> float:
    """1.0 when very close, decaying with travel distance; neutral when unknown."""
    def coords(p: dict):
        loc = _raw(p).get("location") or {}
        lat = loc.get("lat") or p.get("lat")
        lng = loc.get("lng") or p.get("lng")
        return (lat, lng) if lat is not None and lng is not None else None

    a, b = coords(me), coords(cand)
    if a and b:
        km = haversine_km(a[0], a[1], b[0], b[1])
        return math.exp(-km / 15.0)      # ~0.5 at 10km, ~0.13 at 30km
    # Fall back to city match when coordinates are missing.
    my_city = (_raw(me).get("location") or {}).get("city") or me.get("city")
    cand_city = (_raw(cand).get("location") or {}).get("city") or cand.get("city")
    if my_city and cand_city:
        return 1.0 if my_city.strip().lower() == cand_city.strip().lower() else 0.3
    return 0.5


def recency_score(cand: dict) -> float:
    """Recently-active profiles rank a little higher."""
    ts = cand.get("updated_at") or cand.get("created_at")
    if not isinstance(ts, datetime):
        return 0.5
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    days = (datetime.now(timezone.utc) - ts).total_seconds() / 86400.0
    return math.exp(-days / 30.0)        # ~1 today, ~0.37 at 30 days


def build_features(me: dict, cand: dict, semantic: float) -> dict[str, float]:
    """All model features in [0, 1]. `semantic` is cosine remapped to 0..1."""
    return {
        "semantic": semantic,
        "intent_align": _overlap(_as_list(_raw(me).get("intentions")),
                                 _as_list(_raw(cand).get("intentions"))),
        "lifestyle_align": lifestyle_alignment(me, cand),
        "distance": distance_score(me, cand),
        "recency": recency_score(cand),
    }


# ── Logistic ranker (expert-tuned defaults, retrainable) ──────────────────────
# score = sigmoid(bias + Σ wᵢ·xᵢ). Semantic intent dominates; the rest refine.

DEFAULT_WEIGHTS: dict[str, float] = {
    "semantic": 3.2,
    "intent_align": 1.4,
    "lifestyle_align": 1.0,
    "distance": 1.3,
    "recency": 0.5,
}
DEFAULT_BIAS = -2.6


def score(features: dict[str, float],
          weights: Optional[dict[str, float]] = None,
          bias: float = DEFAULT_BIAS) -> float:
    w = weights or DEFAULT_WEIGHTS
    z = bias + sum(w.get(k, 0.0) * v for k, v in features.items())
    return 1.0 / (1.0 + math.exp(-z))    # P(match) in (0, 1)
