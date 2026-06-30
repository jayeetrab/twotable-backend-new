# TwoTable Matching Engine

## Thesis: we rank *dates*, not people

Every other dating app ranks **people** — a one-sided list filtered by a few
attributes. TwoTable ranks **dates**: the triple **(you, a candidate, a specific
venue)**, optimised for the predicted success of a real-world dinner. Because we
own the restaurant supply and the booking, we can do — and learn from — things a
pure dating app structurally cannot.

This is the core of the innovation claim: a joint person × person × venue
recommender trained on real date outcomes.

---

## The model

### 1. Intent, not keywords (semantic layer)
Each user is compressed into one natural-language **intent document** (bio +
prompt answers + what they're looking for + values + interests) and embedded with
a sentence-transformer (`BAAI/bge-small-en-v1.5`). Compatibility is cosine
similarity of these vectors, so *"love quiet nights with a book"* matches
*"homebody who reads"* with **zero shared keywords**.
→ `services/dating_match.py: build_intent_text`, `compute_intent_vector`

### 2. Reciprocal, two-sided compatibility
We score **P(both like)**, not "do you like them". Hard gender/who-you-date
preferences must be satisfied **both ways**; soft signals (intentions, monogamy,
lifestyle, distance, recency) feed a logistic model.
→ `dating_match.reciprocal_ok`, `build_features`, `score`

### 3. Joint person × venue (the differentiator)
For each top candidate we build a **pair intent** (your tastes + theirs: budget,
cuisine, vibe, shared interests), embed it, and find the venue whose vector best
fits **both of you** and is reachable for **both** (travel decay on the farther
person). The result is a concrete suggested first date, not just a face.
→ `services/date_recommender.py: pair_date_text`, `best_venue_for_pair`

### 4. Expected date-success funnel
We don't stop at "compatible". We estimate the full funnel as a calibrated product:

```
E[success] = P(mutual like) · P(book | match) · P(great date | book)
```

A pair only books when a genuinely good shared venue exists nearby, so venue fit
and logistics enter the conversion term directly. Ranking by `E[success]` means
we optimise for *dates that actually happen and go well*.
→ `date_recommender.expected_success`

### 5. A system that learns (not a static filter)
- **Exploration** — a UCB-style bonus for rarely-shown profiles, so good matches
  aren't buried by popularity and we gather evidence on everyone.
- **Diversity** — Maximal Marginal Relevance re-ranking so the top isn't ten
  near-identical people.
→ `date_recommender.exploration_bonus`, `diversify`

### 6. Learning-to-rank from real outcomes (the moat)
Every step of the funnel is logged to `match_events`:

```
impression → like / pass → mutual_match → booked → attended → rated → rematched
```

`scripts/train_ranker.py` refits the ranker weights from these outcomes; the feed
loads the learned model automatically once enough data exists, falling back to
expert priors before then. **Because we own the venue + booking, our ground-truth
label is "did the date actually go well" — a signal no swipe-only competitor can
observe.** This is the defensible, compounding data advantage.
→ `services/events.py`, `scripts/train_ranker.py`, collection `ranker_model`

---

## What the feed returns now

Each card carries: `match_score` (P mutual), `expected_success`, the full
`funnel` breakdown, and a `suggested_venue` (best shared spot + fit). Warm
latency ≈ **0.3s** for a fully-scored, venue-matched, diversified feed.

## Why it's distinguished from competitors
- **Joint optimisation over people + venue + logistics** — nobody else recommends
  the *pair's* ideal first-date venue.
- **Outcome-grounded learning** — trained on booked/attended/rated dates, not
  swipes. Structurally unavailable to apps that don't own supply.
- **Recommender-grade behaviour** — exploration + diversity + calibrated funnel,
  vs. the static attribute filters typical of dating apps.

## Scalability path
Today: in-app cosine over the city's venues (cached), logistic ranker. Next, as
data grows: (a) a **two-tower neural retriever** with ANN (FAISS/HNSW) for
million-scale candidate generation, (b) a gradient-boosted / neural **re-ranker**
on the funnel features, (c) **per-city online learning**. The data model and
event funnel are already shaped for this.
