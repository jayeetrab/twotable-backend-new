# TwoTable Geo + Routing Engine

## Thesis: fair logistics for two people, not "near me"

A date has two people who travel separately. Every maps SDK answers "what's near
*one* location". TwoTable answers a harder, two-sided question:

> Given two people, each with their own transport mode, at the actual date time and
> traffic, which venue is **fair and convenient for both**?

This is a multi-party, time-aware, fairness-constrained routing problem. It's the
logistics counterpart to the matching engine, and competitors built on single-user
"near me" search don't solve it.

## How it works

### Time-aware, multi-modal travel (`services/routing.py`)
- **Traffic-aware ETAs**: driving uses Mapbox `driving-traffic` with `depart_at`, so
  estimates reflect congestion at the real date time — not free-flow distance.
- **Per-person mode**: walking / cycling / driving, independently for each dater.
- **Matrix-native**: one Mapbox Matrix request scores a whole venue shortlist.
- **Isochrones**: reachable-area polygons for "where can we realistically meet".
- **Cache-first + graceful**: every OD pair is memoised (`travel_time_cache`, bucketed
  by hour); with no token / on any error it falls back to a calibrated haversine
  estimate so the product never blocks.

### Fair meeting-point optimiser (`services/meeting.py`)
For two origins + modes, over the venues near their midpoint, score each venue:

```
balance(v) = exp(-|tA - tB| / 8)      # equity — neither person carries the trip
speed(v)   = exp(-max(tA, tB) / 20)   # convenience — short even for the farther one
score(v)   = 0.5·balance + 0.5·speed
```

Only venues reachable within `max_minutes` for **both** are eligible. The result is
a ranked shortlist with each person's ETA and an explicit fairness read-out.

## API surface (all scenarios)

| Endpoint | Purpose |
|---|---|
| `POST /geo/geocode` | address / postcode → coordinates |
| `POST /geo/reverse` | coordinates → place name |
| `POST /geo/travel-time` | time-aware ETA, one origin→dest |
| `POST /geo/matrix` | ETAs, one origin → many destinations (one call) |
| `POST /geo/isochrone` | reachable-area polygon within N minutes |
| `POST /geo/fair-venues` | rank venues fair+convenient for two arbitrary origins |
| `GET /geo/fair-venues/match/{user_id}` | same, auto-pulling both matched users' home coords |

## Why it's distinguished
- **Two-sided fairness objective** — optimises equity *and* convenience, not single-user
  proximity.
- **Time + traffic + multi-modal** — ETAs at the real date time, each person their own way.
- **Tied into matching** — `/geo/fair-venues/match/{user_id}` turns a match directly into
  a concrete, fair, bookable plan.

## Activation & scale
Set `MAPBOX_TOKEN` in `.env` to switch from the haversine fallback to live Mapbox
Matrix / Isochrone / traffic-aware Directions. Caching keeps cost low; the matrix
path and per-hour cache bucketing scale to many concurrent date-planning requests.
