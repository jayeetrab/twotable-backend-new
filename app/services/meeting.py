"""
Fair meeting-point optimiser — TwoTable's signature logistics innovation.

A date has *two* people. "Venue near user A" is the wrong objective. We solve for
the venue that is **fair and convenient for both**: minimise how long the
worse-off person travels AND minimise the gap between the two travel times, with
each person using their own mode of transport, at the actual date time (traffic
aware via services.routing).

Objective per candidate venue v, given travel times t_a, t_b (minutes):

    balance(v) = exp(-|t_a - t_b| / 8)     # equity: neither person carries the trip
    speed(v)   = exp(-max(t_a, t_b) / 20)  # convenience: short even for the farther one
    score(v)   = 0.5 * balance + 0.5 * speed   ∈ (0, 1]

Only venues reachable within `max_minutes` for BOTH are eligible. Returns the
ranked shortlist with each person's ETA and a fairness read-out.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Optional

from app.services import routing

Coord = tuple[float, float]


def _coord(v: dict) -> Optional[Coord]:
    if v.get("lat") is not None and v.get("lng") is not None:
        return (v["lat"], v["lng"])
    return None


async def fair_meeting_venues(
    origin_a: Coord, mode_a: str,
    origin_b: Coord, mode_b: str,
    venues: list[dict],
    depart_at: Optional[datetime] = None,
    max_minutes: int = 45,
    limit: int = 10,
) -> list[dict]:
    """Rank venues by fairness + convenience for two people travelling separately."""
    indexed = [(i, c) for i, v in enumerate(venues) if (c := _coord(v))]
    if not indexed:
        return []
    dests = [c for _, c in indexed]

    # Two matrix calls (one per person) cover the whole shortlist.
    ta = await routing.travel_matrix(origin_a, dests, mode_a, depart_at)
    tb = await routing.travel_matrix(origin_b, dests, mode_b, depart_at)

    out = []
    for (vi, _), t_a, t_b in zip(indexed, ta, tb):
        if t_a is None or t_b is None:
            continue
        if t_a > max_minutes or t_b > max_minutes:
            continue
        balance = math.exp(-abs(t_a - t_b) / 8.0)
        speed = math.exp(-max(t_a, t_b) / 20.0)
        score = 0.5 * balance + 0.5 * speed
        v = venues[vi]
        out.append({
            "venue_id": v.get("_id"),
            "name": v.get("name"),
            "cuisine": v.get("cuisine"),
            "price_band": v.get("price_band"),
            "lat": v.get("lat"), "lng": v.get("lng"),
            "eta_a_min": t_a, "eta_b_min": t_b,
            "fairness": round(balance, 3),
            "convenience": round(speed, 3),
            "score": round(score, 3),
        })
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:limit]
