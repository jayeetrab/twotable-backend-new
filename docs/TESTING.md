# Testing Guide

How to verify the whole backend — every endpoint, the matching, the venues/users
data, and the geo engine.

---

## 0. Prerequisites
```bash
cd ~/Documents/GitHub/twotable-backend-new
# start the API
python -m uvicorn app.main:app --host 127.0.0.1 --port 8009
# health check
curl -s http://127.0.0.1:8009/health      # {"status":"ok","version":"1.0.0"}
```
Dev login: phone **`+44 7700900123`**, code **`12345`** (any phone works with the dev
code; the account is created on first verify).

---

## 1. Automated — run the whole API at once ✅ recommended
```bash
python smoke_test.py
# → 32 passed, 0 failed
```
- Exercises every router (auth, profile, photos, discovery/matching, tonight,
  venues, bookings, geo). Cleans up after itself. Non-zero exit on failure (CI-ready).
- `BASE=https://your-host python smoke_test.py` to test a deployed/ngrok host.
- `python smoke_test.py --destructive` also tests account deletion (throwaway login).
- Expected non-200s: `geo/geocode → 404`, `geo/isochrone → 503` (no Mapbox token),
  `fair-venues/match → 422` (target has no coords). These turn green once a token is
  set and the target has a saved location.

## 2. Interactive — Swagger UI
Open **http://127.0.0.1:8009/docs** → **Authorize** → paste a token → "Try it out"
on any endpoint. Schemas and examples are auto-generated. (`/redoc` for a reference view.)

## 3. Postman
Import `postman/collections/TwoTable Backend.postman_collection.json`. Run
**Auth — Phone (OTP) → Phone Verify** first; it auto-saves the token into
`{{token}}` for every other request. Or run headless:
```bash
newman run "postman/collections/TwoTable Backend.postman_collection.json"
```

---

## 4. Manual recipes (curl)

Set up a token once:
```bash
B=http://127.0.0.1:8009/api/v1
TOK=$(curl -s -X POST $B/auth/phone/verify -H 'Content-Type: application/json' \
  -d '{"phone":"+44 7700900123","code":"12345"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
H="Authorization: Bearer $TOK"
```

### Check users (daters)
The discovery feed is the user-facing "who exists" view — it returns other daters,
**ranked by the intent matcher**:
```bash
curl -s "$B/discovery/feed?limit=10" -H "$H" | python3 -m json.tool
# each profile: name, age, occupation, interests, photos,
#               match_score, expected_success, funnel{…}, suggested_venue{…}
```
Verify a like → match flow:
```bash
curl -s -X POST $B/discovery/action -H "$H" -H 'Content-Type: application/json' \
  -d '{"target_id":2,"action":"like"}'
curl -s "$B/discovery/matches" -H "$H"
```

### Check restaurants (venues)
```bash
curl -s "$B/venues?city=Bristol&limit=5" -H "$H" | python3 -m json.tool   # list
curl -s "$B/venues/1" -H "$H"                                              # one venue + slots
# availability at a slot:
curl -s "$B/venues/available?date=2026-07-01&time=19:30:00&city=Bristol" -H "$H"
# intent → ranked venues (semantic):
curl -s -X POST $B/venues/suggest -H "$H" -H 'Content-Type: application/json' \
  -d '{"stage":"first date","mood":"cozy","energy":"low","budget":"medium","city":"Bristol"}'
```

### Check the geo / fair-meeting engine
```bash
curl -s -X POST $B/geo/fair-venues -H "$H" -H 'Content-Type: application/json' -d '{
  "origin_a":{"lat":51.4545,"lng":-2.5879},"origin_b":{"lat":51.4645,"lng":-2.61},
  "mode_a":"drive","mode_b":"walk","city":"Bristol","limit":5}' | python3 -m json.tool
# → venues ranked by fairness + convenience, with each person's ETA
```

### Tonight's Table
```bash
curl -s "$B/tonight?city=Bristol" -H "$H"          # today's pick + going-count
curl -s -X POST "$B/tonight/opt-in?city=Bristol" -H "$H"
curl -s "$B/tonight/people" -H "$H"                # others in, intent-ranked
```

---

## 5. Inspect the data directly (counts / sanity)
Quick DB census without the API:
```bash
python3 - <<'PY'
import asyncio
from app.db import mongo
async def census():
    mongo.connect(); db = mongo.get_db()
    print("users:        ", await db[mongo.USERS].count_documents({}))
    print("  daters:     ", await db[mongo.USERS].count_documents({"role":"dater"}))
    print("  onboarded:  ", await db[mongo.USERS].count_documents({"full_name":{"$nin":[None,""]}}))
    print("profiles:     ", await db[mongo.PROFILES].count_documents({}))
    print("  w/ vectors: ", await db[mongo.PROFILES].count_documents({"intent_vector":{"$exists":True}}))
    print("venues_app:   ", await db[mongo.VENUES].count_documents({}))
    print("  embedded:   ", await db[mongo.VENUES].count_documents({"embedding":{"$exists":True}}))
    print("likes:        ", await db[mongo.LIKES].count_documents({}))
    print("connections:  ", await db[mongo.CONNECTIONS].count_documents({}))
    print("match_events: ", await db["match_events"].count_documents({}))
    mongo.close()
asyncio.run(census())
PY
```
(Use **MongoDB Compass** with your `MONGODB_URI` for a GUI.)

---

## 6. Activate the full Mapbox path
The geo engine runs on a haversine fallback by default. To test **live**
geocoding / traffic ETAs / isochrones:
1. Put `MAPBOX_TOKEN=<your token>` in `.env`.
2. Restart the server.
3. Re-run `python smoke_test.py` — `geo/geocode` and `geo/isochrone` now return `200`.

## 7. Train / verify the learning ranker
```bash
python -m app.scripts.train_ranker
# < 30 outcomes → keeps expert priors (expected early on).
# Once enough swipes/dates exist it writes learned weights to `ranker_model`,
# and the feed loads them automatically.
```
