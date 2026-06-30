# TwoTable Backend — Documentation

| Doc | What's in it |
|---|---|
| [MODELS.md](MODELS.md) | Every ML model + external API we use (embeddings, ranker, **Mapbox** geocoding/routing), why, cost & privacy. |
| [API.md](API.md) | Full API reference — all 50 endpoints, auth, bodies, a runnable curl flow. |
| [TESTING.md](TESTING.md) | How to test everything: smoke test, Swagger, Postman, curl recipes (users, restaurants, geo), DB census. |
| [../MATCHING.md](../MATCHING.md) | Design of the intent-matching engine (the matching innovation). |
| [../GEO.md](../GEO.md) | Design of the fair meeting-point routing engine (the geo innovation). |

## TL;DR
- **Matching:** local transformer embeddings (`BAAI/bge-small-en-v1.5`) for semantic
  *intent* + a learning-to-rank logistic model + an expected-date-success funnel +
  exploration/diversity. Ranks *dates* (person × venue), not just people.
- **Geo:** **Mapbox** (Geocoding v6, Directions w/ live traffic, Matrix, Isochrone),
  cache-first, with a haversine fallback. Powers a two-sided *fair meeting-point*
  optimiser unique to a dating-restaurant product.
- **Stack:** FastAPI · MongoDB (+GridFS) · Redis · JWT.

## Run + test in 30 seconds
```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8009   # start
python smoke_test.py                                          # test everything
# open http://127.0.0.1:8009/docs for interactive Swagger
```
