"""
TwoTable date recommender — the part competitors structurally cannot copy.

Standard dating apps rank *people*. TwoTable ranks *dates*: a date is the triple
(you, a candidate, a specific venue). Because we own the restaurant + booking, we
optimise for predicted real-world date success, decomposed as a calibrated funnel:

    E[success] = P(mutual like) · P(book | match) · P(great date | book)

- P(mutual like)  comes from the reciprocal intent model (services.dating_match).
- P(book | match) rises when a genuinely good *shared* venue exists nearby — i.e.
  a place that fits BOTH people's taste/budget and is reachable for both.
- P(great date)   rises with deep compatibility + venue fit.

On top of the point estimate we add two recommender-grade behaviours that turn this
from a static filter into a system that *learns*:
- Exploration: a UCB-style bonus for rarely-shown profiles, so good matches aren't
  buried by popularity (rich-get-richer) and every profile gets evidence gathered.
- Diversity: Maximal Marginal Relevance re-ranking so the top results aren't ten
  near-identical people.

Pure python + numpy. Embeddings come from services.embeddings; venue vectors live
on each venue's `embedding` field.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

from app.services import dating_match, embeddings
from app.services.geo import estimate_travel_minutes, haversine_km

# Product rule: a date venue must be reachable within 45 minutes for BOTH people.
MAX_COMMUTE_MIN = 45.0


# ── Pair → ideal shared venue ─────────────────────────────────────────────────

def pair_date_text(me: dict, cand: dict) -> str:
    """A combined 'first-date intent' for two people, for venue matching."""
    raw_me, raw_c = dating_match._raw(me), dating_match._raw(cand)

    def vals(raw, key):
        v = raw.get(key)
        return v if isinstance(v, list) else ([v] if isinstance(v, str) and v else [])

    budget = vals(raw_me, "budget") + vals(raw_c, "budget")
    cuisines = vals(raw_me, "cuisine_preferences") + vals(raw_c, "cuisine_preferences")
    vibes = vals(raw_me, "restaurant_vibe") + vals(raw_c, "restaurant_vibe")
    interests = (dating_match._as_list(raw_me.get("interests"))
                 + dating_match._as_list(raw_c.get("interests")))

    parts = ["A relaxed first dinner date for two people."]
    if budget:
        parts.append("Budget: " + ", ".join(dict.fromkeys(budget)))
    if cuisines:
        parts.append("Cuisine: " + ", ".join(dict.fromkeys(cuisines)))
    if vibes:
        parts.append("Vibe: " + ", ".join(dict.fromkeys(vibes)))
    if interests:
        parts.append("Shared interests: " + ", ".join(dict.fromkeys(interests))[:200])
    return " ".join(parts)


def _coords(p: dict):
    loc = dating_match._raw(p).get("location") or {}
    lat = loc.get("lat") or p.get("lat")
    lng = loc.get("lng") or p.get("lng")
    return (lat, lng) if lat is not None and lng is not None else None


def best_venue_for_pair(me: dict, cand: dict, pair_vec: list[float],
                        venues: list[dict]) -> Optional[tuple[dict, float]]:
    """Pick the venue that best fits BOTH people (semantic fit + reachable for both)."""
    if not pair_vec or not venues:
        return None
    a, b = _coords(me), _coords(cand)
    best, best_score = None, -1.0
    for v in venues:
        emb = v.get("embedding")
        if not emb:
            continue
        fit = (embeddings.cosine(pair_vec, emb) + 1.0) / 2.0   # 0..1 taste fit
        # Reachability: hard 45-minute commute cap for BOTH, then a soft decay so the
        # fairest-to-reach venues among the eligible ones win.
        if a and b and v.get("lat") is not None and v.get("lng") is not None:
            ta = estimate_travel_minutes(a[0], a[1], v["lat"], v["lng"], "drive")
            tb = estimate_travel_minutes(b[0], b[1], v["lat"], v["lng"], "drive")
            if ta > MAX_COMMUTE_MIN or tb > MAX_COMMUTE_MIN:
                continue                                        # not meetable: skip entirely
            reach = math.exp(-max(ta, tb) / 25.0)
            fit = 0.75 * fit + 0.25 * reach
        if fit > best_score:
            best, best_score = v, fit
    return (best, best_score) if best else None


# ── Calibrated date-success funnel ────────────────────────────────────────────
# Each stage is a logistic with expert-prior coefficients; retrainable from the
# match_events funnel as real outcomes accumulate.

def _sig(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z))


def expected_success(p_mutual: float, venue_fit: float, distance: float) -> dict:
    """Decompose and combine the funnel into one expected-success score."""
    # P(book | match): a strong shared venue + closeness drives conversion to a booking.
    p_book = _sig(-0.4 + 2.4 * venue_fit + 1.1 * p_mutual + 0.8 * distance)
    # P(great date | book): deep compatibility + venue fit.
    p_great = _sig(0.2 + 1.6 * venue_fit + 1.6 * p_mutual)
    e = p_mutual * p_book * p_great
    return {"p_mutual": p_mutual, "p_book": p_book, "p_great": p_great, "expected_success": e}


# ── Exploration (UCB-style) ───────────────────────────────────────────────────

def exploration_bonus(impressions: int, weight: float = 0.08) -> float:
    """Boost rarely-shown profiles so the system gathers evidence on everyone."""
    return weight / math.sqrt(1.0 + max(impressions, 0))


# ── Diversity (Maximal Marginal Relevance) ────────────────────────────────────

def diversify(items: list[tuple[float, dict, dict]],
              vector_of, k: int, lam: float = 0.7) -> list[tuple[float, dict, dict]]:
    """Re-rank to balance relevance with novelty so the top-k aren't near-duplicates.

    `items` are (score, user, profile) sorted by score desc. `vector_of(profile)`
    returns that profile's intent vector (or None).
    """
    if len(items) <= 1:
        return items
    selected: list[tuple[float, dict, dict]] = []
    pool = items[:]
    # Normalise scores to 0..1 for a stable relevance/diversity trade-off.
    smax = max(s for s, _, _ in pool) or 1.0

    def sim(pa, pb) -> float:
        va, vb = vector_of(pa), vector_of(pb)
        if not va or not vb:
            return 0.0
        return max(0.0, embeddings.cosine(va, vb))

    while pool and len(selected) < k:
        best_i, best_mmr = 0, -1e9
        for i, (s, u, p) in enumerate(pool):
            rel = s / smax
            nov = max((sim(p, sp) for _, _, sp in selected), default=0.0)
            mmr = lam * rel - (1.0 - lam) * nov
            if mmr > best_mmr:
                best_i, best_mmr = i, mmr
        selected.append(pool.pop(best_i))
    return selected + pool  # keep the tail in original order after the diversified head
