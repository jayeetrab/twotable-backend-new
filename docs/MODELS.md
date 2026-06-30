# Models & External Services

Honest, precise inventory of every model / API the backend uses, what it's used
for, and why it was chosen. (For the deeper design rationale see
[../MATCHING.md](../MATCHING.md) and [../GEO.md](../GEO.md).)

---

## 1. Machine-learning models (matching)

### 1.1 Semantic embedding model — `BAAI/bge-small-en-v1.5`
- **Type:** transformer (BERT-family) **sentence-embedding** model, ~33M params,
  **384-dim** output, run locally via the `sentence-transformers` library.
- **Provenance:** BGE ("BAAI General Embedding") v1.5, trained with contrastive
  learning; ranks at the top of the **MTEB** benchmark *for its size class*.
- **Why this one:** strong semantic quality, **CPU-friendly, fully offline, no API
  key, low latency** (≈ms per short text, batched). It's a deliberate
  quality/cost trade-off — a "small" model that punches far above MiniLM (our
  previous model) without a GPU or per-call cost.
- **What it powers:**
  - **User intent vectors** — each user's bio + prompts + "looking for" + values +
    interests are fused into one document and embedded (`services/dating_match.py`).
  - **Venue vectors** — each venue's name/cuisine/vibe/description embedded once
    (`scripts/embed_venues.py`, stored on `venue.embedding`).
  - **Pair date vectors** — a combined two-person "first-date intent" used to find
    the best shared venue (`services/date_recommender.py`).
- **Similarity:** vectors are L2-normalised at encode time, so cosine similarity is
  a dot product — "in-app cosine", no external vector DB needed at current scale.
- **Config:** `EMBEDDING_MODEL` / `EMBEDDING_DIM` in `app/core/config.py`. Swapping
  to a larger local model or an embedding API (OpenAI/Voyage/Cohere) is a one-line
  change + a venue re-embed.

> Note on terminology: the **deep-learning** component is this transformer encoder.
> We do **not** use a large generative LLM (GPT-style) in the matching path — that
> would be slower and costlier without improving *similarity* quality. This is the
> standard architecture for production recommenders.

### 1.2 Ranking model — logistic regression (learning-to-rank)
- **What:** a linear logistic model `P(match) = σ(b + Σ wᵢ·xᵢ)` over features
  (semantic similarity, intent alignment, lifestyle agreement, distance, recency).
- **Training:** `scripts/train_ranker.py` refits the weights from real swipe /
  funnel outcomes (`match_events`); the feed auto-loads the learned model from the
  `ranker_model` collection, falling back to **expert-tuned priors** before enough
  data exists. Implemented in plain NumPy (no scikit-learn dependency).
- **Why linear first:** interpretable, trains on tiny data, no overfitting on a cold
  start. Documented upgrade path: gradient-boosted trees / a two-tower neural
  re-ranker as data grows.

### 1.3 Success-funnel model
Three calibrated logistic stages — `P(mutual) · P(book|match) · P(great|book)` —
combined into an **expected date-success** score the feed ranks by
(`services/date_recommender.py: expected_success`).

### 1.4 Recommender behaviours
- **Exploration:** UCB-style bonus for rarely-shown profiles (`exploration_bonus`).
- **Diversity:** Maximal Marginal Relevance re-rank so the top isn't near-duplicates
  (`diversify`).

**Dependencies:** `sentence-transformers==3.4.1`, `numpy==2.2.2`. The model weights
(~130 MB) download once on first use and are cached by `sentence-transformers`.

---

## 2. Geocoding & routing — **Mapbox**

Standardised on **Mapbox** (chosen over the legacy multi-provider code that used
TomTom/OpenCage/ORS). All calls are **cache-first** and **degrade gracefully** to a
local estimate when no token is set, so the product never blocks on the network.

| Capability | Mapbox product | Used by | Notes |
|---|---|---|---|
| Address/postcode → coords | **Geocoding API v6** (forward) | onboarding save, `POST /geo/geocode` | UK-biased (`country=gb`) |
| Coords → place name | **Geocoding API v6** (reverse) | `POST /geo/reverse` | |
| Single ETA | **Directions API** | `POST /geo/travel-time` | `driving-traffic` profile, **time-aware** via `depart_at` |
| One→many ETAs | **Matrix API** | fair-venue ranking, `POST /geo/matrix` | one call scores a whole shortlist |
| Reachable area | **Isochrone API** | `POST /geo/isochrone` | GeoJSON polygon |

- **Time-aware:** driving uses Mapbox's **live-traffic** profile with a departure
  time, so ETAs reflect congestion at the actual date time, not free-flow distance.
- **Multi-modal:** walking / cycling / driving per request.
- **Fallback (no token):** great-circle **haversine** distance + per-mode speed
  (`services/geo.py`). This is why `geo/geocode` returns 404 and `geo/isochrone`
  503 until a token is set — the math-only routes (`travel-time`, `matrix`,
  `fair-venues`) still work via the estimate.
- **Caching:** `geocoding_cache` and `travel_time_cache` collections (the latter
  bucketed by hour); plus an in-process cache of city venue vectors.
- **Config:** set `MAPBOX_TOKEN` in `.env`. Code: `services/geocoding.py`,
  `services/routing.py`, `services/meeting.py`.

---

## 3. Supporting infrastructure
| Concern | Tech |
|---|---|
| Database | **MongoDB** (Motor async driver), integer `_id`s via a counters collection |
| Photo storage | **MongoDB GridFS** (bucket `photos`), served with long `Cache-Control` |
| Auth | **JWT** (python-jose) access/refresh tokens; bcrypt for password users; phone-OTP (dev code) |
| Cache | **Redis** (venue lists / suggestions) — degrades gracefully if down |
| API | **FastAPI** + GZip compression |
| Venue text enrichment (seed-time only, optional) | **Gemini** or local **Ollama** (`services/gemini_enrich.py`, `services/ollama_enrich.py`) — not in the request path |

---

## 4. Cost & privacy summary
- **Matching ML:** $0 / offline (local model + linear ranker).
- **Mapbox:** pay-as-you-go with a generous free tier; every result cached, so
  repeat lookups are free. No token ⇒ haversine fallback, still functional.
- No user text is sent to a third party for matching — embeddings are computed
  locally. Only coarse location strings/coords go to Mapbox, and only on a cache
  miss.
