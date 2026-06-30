# TwoTable API Reference

Base URL (dev): `http://127.0.0.1:8009`  ·  All app routes are under `/api/v1`.
Interactive docs (auto-generated): **`/docs`** (Swagger) and **`/redoc`**.

**Auth:** send `Authorization: Bearer <access_token>` on every protected route.
Get a token from `POST /auth/phone/verify` (dev: phone `+44 7700900123`, code
`12345`). 50 app endpoints + `/health`.

Legend: 🔓 public · 🔒 requires a user token · 🛡️ admin token.

---

## Meta
| Method | Path | | Description |
|---|---|---|---|
| GET | `/health` | 🔓 | DB ping + version. |

## Auth — `/api/v1/auth`
| Method | Path | | Body / notes |
|---|---|---|---|
| POST | `/auth/phone/start` | 🔓 | `{phone}` — begins OTP; dev returns the code. |
| POST | `/auth/phone/verify` | 🔓 | `{phone, code}` — verifies, **creates account on first use**, returns `{access_token, refresh_token}`. |
| POST | `/auth/register` | 🔓 | `{email, password, full_name?}` — email/password signup. |
| POST | `/auth/login` | 🔓 | `{email, password}` → tokens. |
| POST | `/auth/refresh` | 🔓 | `{refresh_token}` → new tokens. |
| GET | `/auth/me` | 🔒 | The user record. |
| PATCH | `/auth/me` | 🔒 | `{full_name?, ...}` — update base user fields. |

## Profile — `/api/v1/profile`
| Method | Path | | Body / notes |
|---|---|---|---|
| GET | `/profile/me` | 🔒 | **Composite**: user + profile + availability + `onboarding` (full raw answers, for re-hydration) + photo URLs. |
| POST | `/profile/setup` | 🔒 | Structured `ProfileSetupRequest` (typed fields). |
| POST | `/profile/onboarding` | 🔒 | Full free-form answer set; stored under `onboarding_raw`, geocodes location, refreshes the intent vector. |
| GET | `/profile/availability` | 🔒 | List availability slots. |
| POST | `/profile/availability` | 🔒 | `{slots:[{weekday,start_time,end_time}]}`. |
| POST | `/profile/pause` | 🔒 | Hide from discovery (reversible; uses a `paused` flag, not is_active). |
| POST | `/profile/resume` | 🔒 | Unhide. |
| DELETE | `/profile/me` | 🔒 | **Destructive** — deletes user + profile + photos + likes + connections. |

## Photos
| Method | Path | | Notes |
|---|---|---|---|
| POST | `/profile/photos` | 🔒 | `multipart/form-data` field `file` → GridFS; returns `{photo_id, url}`. |
| PUT | `/profile/photos/order` | 🔒 | `{order:[id,…]}` — must be a permutation of current ids (first = primary). |
| DELETE | `/profile/photos/{file_id}` | 🔒 | Remove a photo. |
| GET | `/photos/{file_id}` | 🔓 | Stream the image (long-lived `Cache-Control`). |

## Discovery — intent matching — `/api/v1/discovery`
| Method | Path | | Notes |
|---|---|---|---|
| GET | `/discovery/feed?limit=` | 🔒 | **Intent-ranked** candidates. Each card: `match_score`, `expected_success`, `funnel{p_mutual,p_book,p_great}`, and a `suggested_venue`. |
| POST | `/discovery/action` | 🔒 | `{target_id, action:"like"|"pass"}`; a reciprocated like returns `{matched:true, with:{…}}`. |
| GET | `/discovery/matches` | 🔒 | Mutual connections. |
| DELETE | `/discovery/matches/{user_id}` | 🔒 | Unmatch (records a pass so they don't resurface). |

## Tonight's Table — `/api/v1/tonight`
| Method | Path | | Notes |
|---|---|---|---|
| GET | `/tonight?city=` | 🔒 | Today's curated venue, opt-in state, going-count, avatars, cutoff. |
| POST | `/tonight/opt-in?city=` | 🔒 | Join tonight. |
| DELETE | `/tonight/opt-in` | 🔒 | Leave tonight. |
| GET | `/tonight/people` | 🔒 | Others in tonight, ranked by the same intent matcher. |

## Venues — `/api/v1/venues`
| Method | Path | | Notes |
|---|---|---|---|
| GET | `/venues?city=&limit=` | 🔒 | Real, date-appropriate venues with coords (Redis-cached). |
| GET | `/venues/{venue_id}` | 🔒 | One venue + slots. |
| GET | `/venues/available?date=&time=&city=&origin_lat=&origin_lng=&mode=&max_travel_min=` | 🔓 | Venues open at that slot, optionally within travel time. |
| POST | `/venues/suggest` | 🔒 | Intent → ranked venues (embedding cosine + availability/load). |
| POST | `/venues/apply` | 🔓 | `VenueLeadCreate` — a venue applies to join. |

## Bookings — `/api/v1/bookings`
| Method | Path | | Notes |
|---|---|---|---|
| POST | `/bookings/quick` | 🔒 | `{venue_id, date, time}` — simple booking (dev: auto-confirm). |
| GET | `/bookings/mine` | 🔒 | The user's bookings. |
| POST | `/bookings` | 🔒 | Full `BookingCreate`. |
| GET | `/bookings/{booking_id}` | 🔒 | One booking. |
| POST | `/bookings/{booking_id}/confirm` | 🔒 | Confirm (Stripe when configured). |
| DELETE | `/bookings/{booking_id}` | 🔒 | Cancel. |
| POST | `/bookings/matches` · `/matches/{id}` · `/matches/{id}/join` | 🔒 | Group/match-booking lifecycle. |

## Geo & Routing — `/api/v1/geo`
| Method | Path | | Body / notes |
|---|---|---|---|
| POST | `/geo/geocode` | 🔒 | `{query, country?}` → `{lat,lng,name}`. *(404 without `MAPBOX_TOKEN`.)* |
| POST | `/geo/reverse` | 🔒 | `{lat,lng}` → `{name}`. |
| POST | `/geo/travel-time` | 🔒 | `{origin:{lat,lng}, dest:{lat,lng}, mode, depart_at?}` → `{minutes}`. |
| POST | `/geo/matrix` | 🔒 | `{origin, destinations:[…], mode}` → `{minutes:[…]}`. |
| POST | `/geo/isochrone` | 🔒 | `{origin, minutes, mode}` → GeoJSON. *(503 without token.)* |
| POST | `/geo/fair-venues` | 🔒 | `{origin_a, origin_b, mode_a, mode_b, city, max_minutes?, limit?}` → venues fair+convenient for **both**. |
| GET | `/geo/fair-venues/match/{user_id}?mode=&max_minutes=` | 🔒 | Same, auto-pulling both matched users' home coords. *(422 if either lacks coords.)* |

## Admin — `/api/v1/admin` 🛡️
Venue CRUD, slots/blackouts, leads (list/approve/promote), users (list/activate/
deactivate), bookings + stats, matches, cache stats/clear, venue enrich/embed.
(Not registered in `main.py` by default — wire `admin_router` to enable.)

---

## Example: full flow with curl
```bash
B=http://127.0.0.1:8009/api/v1
# 1) login (dev)
TOK=$(curl -s -X POST $B/auth/phone/verify -H 'Content-Type: application/json' \
  -d '{"phone":"+44 7700900123","code":"12345"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
H="Authorization: Bearer $TOK"

# 2) save onboarding
curl -s -X POST $B/profile/onboarding -H "$H" -H 'Content-Type: application/json' \
  -d '{"first_name":"Dev","bio":"Quiet dinners and live jazz","interests":["Jazz","Cooking"],
       "intentions":["Serious dating"],"date_preferences":["Everyone"],"gender":"Man",
       "location":{"city":"Bristol","postcode":"BS1 5TR"}}'

# 3) ranked feed (people + suggested venue + success funnel)
curl -s $B/discovery/feed?limit=5 -H "$H"

# 4) like someone
curl -s -X POST $B/discovery/action -H "$H" -H 'Content-Type: application/json' \
  -d '{"target_id":2,"action":"like"}'

# 5) fair venue for that match
curl -s "$B/geo/fair-venues/match/2" -H "$H"
```
