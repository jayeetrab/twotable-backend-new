Here is the complete structured status of TwoTable backend: [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/114416370/2dbf770d-f6ed-4a58-a97c-ba3a7d74341e/codebase_dump1.txt)

***

##  DONE — In Codebase & Working

### Foundation
- Auth system — register, login, refresh JWT, role guards (`dater`, `venue`, `admin`) [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/114416370/2dbf770d-f6ed-4a58-a97c-ba3a7d74341e/codebase_dump1.txt)
- Waitlist — email collection with duplicate guard [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/114416370/2dbf770d-f6ed-4a58-a97c-ba3a7d74341e/codebase_dump1.txt)
- Health check endpoint [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/114416370/2dbf770d-f6ed-4a58-a97c-ba3a7d74341e/codebase_dump1.txt)

### Venue Pipeline
- Venue lead application → admin review → promote to live venue [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/114416370/2dbf770d-f6ed-4a58-a97c-ba3a7d74341e/codebase_dump1.txt)
- Geocoding with TomTom + DB cache [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/114416370/2dbf770d-f6ed-4a58-a97c-ba3a7d74341e/codebase_dump1.txt)
- Venue slots & blackout management (CRUD) [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/114416370/2dbf770d-f6ed-4a58-a97c-ba3a7d74341e/codebase_dump1.txt)
- Groq LLM enrichment — auto-generate description + vibe tags [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/114416370/2dbf770d-f6ed-4a58-a97c-ba3a7d74341e/codebase_dump1.txt)
- Venue embeddings (pgvector, `all-MiniLM-L6-v2`) — single + bulk embed [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/114416370/2dbf770d-f6ed-4a58-a97c-ba3a7d74341e/codebase_dump1.txt)

### Matching & Suggest
- Full ANN vector search against venue embeddings [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/114416370/2dbf770d-f6ed-4a58-a97c-ba3a7d74341e/codebase_dump1.txt)
- Travel time filter via TomTom routing API [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/114416370/2dbf770d-f6ed-4a58-a97c-ba3a7d74341e/codebase_dump1.txt)
- Haversine pre-filter + Redis cache [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/114416370/2dbf770d-f6ed-4a58-a97c-ba3a7d74341e/codebase_dump1.txt)
- Blackout date exclusion [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/114416370/2dbf770d-f6ed-4a58-a97c-ba3a7d74341e/codebase_dump1.txt)
- Capacity / slot load factor check [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/114416370/2dbf770d-f6ed-4a58-a97c-ba3a7d74341e/codebase_dump1.txt)
- `POST /api/v1/venues/suggest` — full working endpoint [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/114416370/2dbf770d-f6ed-4a58-a97c-ba3a7d74341e/codebase_dump1.txt)

### Bookings
- Match create → join → confirm flow [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/114416370/2dbf770d-f6ed-4a58-a97c-ba3a7d74341e/codebase_dump1.txt)
- Booking with Stripe deposit (£10) + webhook confirmation [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/114416370/2dbf770d-f6ed-4a58-a97c-ba3a7d74341e/codebase_dump1.txt)
- Cancel booking, admin view, revenue stats [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/114416370/2dbf770d-f6ed-4a58-a97c-ba3a7d74341e/codebase_dump1.txt)

### Step 1 — User Profile
- `UserProfile` model + `UserAvailability` model [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/114416370/2dbf770d-f6ed-4a58-a97c-ba3a7d74341e/codebase_dump1.txt)
- `POST /api/v1/profile/setup` — upsert full profile [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/114416370/2dbf770d-f6ed-4a58-a97c-ba3a7d74341e/codebase_dump1.txt)
- `GET /api/v1/profile/me` — full composite profile [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/114416370/2dbf770d-f6ed-4a58-a97c-ba3a7d74341e/codebase_dump1.txt)
- `POST /api/v1/profile/availability` — set weekly availability [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/114416370/2dbf770d-f6ed-4a58-a97c-ba3a7d74341e/codebase_dump1.txt)

### Step 2 — Social Signals
- `UserSocialConnection` + `UserSocialSignal` models [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/114416370/2dbf770d-f6ed-4a58-a97c-ba3a7d74341e/codebase_dump1.txt)
- Spotify pipeline — top artists, tracks, audio features → signals [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/114416370/2dbf770d-f6ed-4a58-a97c-ba3a7d74341e/codebase_dump1.txt)
- Instagram pipeline — captions + images via Groq Vision → signals [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/114416370/2dbf770d-f6ed-4a58-a97c-ba3a7d74341e/codebase_dump1.txt)
- `POST /api/v1/profile/connect/spotify` [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/114416370/2dbf770d-f6ed-4a58-a97c-ba3a7d74341e/codebase_dump1.txt)
- `POST /api/v1/profile/connect/instagram` [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/114416370/2dbf770d-f6ed-4a58-a97c-ba3a7d74341e/codebase_dump1.txt)
- `POST /api/v1/profile/social/resync/{platform}` [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/114416370/2dbf770d-f6ed-4a58-a97c-ba3a7d74341e/codebase_dump1.txt)
- `GET /api/v1/profile/social/connections` [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/114416370/2dbf770d-f6ed-4a58-a97c-ba3a7d74341e/codebase_dump1.txt)
- `GET /api/v1/profile/social/signals` [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/114416370/2dbf770d-f6ed-4a58-a97c-ba3a7d74341e/codebase_dump1.txt)

### Admin Panel
- Full CRUD: users, venues, leads, bookings, matches [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/114416370/2dbf770d-f6ed-4a58-a97c-ba3a7d74341e/codebase_dump1.txt)
- Cache stats + clear [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/114416370/2dbf770d-f6ed-4a58-a97c-ba3a7d74341e/codebase_dump1.txt)
- Venue enrich-all + embed-all [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/114416370/2dbf770d-f6ed-4a58-a97c-ba3a7d74341e/codebase_dump1.txt)

***

## CODE GIVEN — NOT YET ADDED TO PROJECT

These were built in this conversation but haven't been copy-pasted into your files yet:

| # | What | Files Affected |
|---|------|---------------|
| 1 | `UserEmbedding` model | `app/models/user_embedding.py` *(new)* |
| 2 | User embedding service | `app/services/user_embeddings.py` *(new)* |
| 3 | `POST /profile/embed` + `GET /profile/embed` | `app/api/v1/profile.py` |
| 4 | `EmbedMetaRead` schema | `app/schemas/profile.py` |
| 5 | Spotify OAuth full flow | `app/api/v1/spotify_auth.py` *(new)* |
| 6 | Register `spotify_auth_router` | `app/main.py` |
| 7 | Spotify config vars | `app/core/config.py` + `.env` |
| 8 | `user_embedding` import | `alembic/env.py` |
| 9 | Migration `add_user_embeddings` | Run `alembic revision + upgrade` |

***

##  NOT BUILT YET — Remaining Work

### Step 3 completion
- [ ] Auto-trigger `upsert_user_embedding()` inside `setup_profile` after commit
- [ ] Auto-trigger `upsert_user_embedding()` inside `connect_spotify` after pipeline

### Step 4 — People Matching Engine
- [ ] `compute_compatibility_score(user_a, user_b)` — weighted scoring across: relationship goal, energy, budget, communication style, availability overlap, music similarity
- [ ] `GET /api/v1/match/candidates` — return ranked list of compatible users
- [ ] `find_similar_users()` wired into an endpoint

### Step 5 — Personality Archetype
- [ ] LLM pass over onboarding answers → assign archetype (The Nester, The Romantic etc.)
- [ ] `personality_archetype` field on `UserProfile`
- [ ] Feed archetype into venue suggest scoring

### Step 6 — AI Date Planner
- [ ] Free text input endpoint `POST /api/v1/plan`
- [ ] Intent parser (Groq LLM) → extracts mood, budget, city, date, multi-stop
- [ ] Chains into `/venues/suggest` automatically
- [ ] OpenTable / Resy booking API integration

### Step 7 — Post-Match Experience
- [ ] Icebreaker generator — Groq call on match confirm
- [ ] `GET /api/v1/match/{id}/icebreaker`

### Step 8 — Behavioural Signals
- [ ] `user_events` table — track venue views, search queries, accept/decline
- [ ] Weekly embedding refresh job using event data

### Infrastructure
- [ ] Spotify OAuth credentials added to `.env`
- [ ] Groq API key added to `.env` and verified working
- [ ] Frontend `FRONTEND_REDIRECT_URL` set correctly

***

## Priority Order — What to Do Next

```
TODAY    →  Add the 9 pending copy-paste items (Step 3 + Spotify OAuth)
NEXT     →  Step 4: Compatibility scoring + match candidates endpoint
THEN     →  Step 5: Personality archetype LLM pass
AFTER    →  Step 6: AI Date Planner (your biggest differentiator)
LATER    →  Steps 7 & 8: Icebreaker + behavioural signals
```



What makes TwoTable different
Most dating apps sell profiles. You're selling an experience — the date itself, at a curated venue, personalised to both people. That's your moat. Everything below should reinforce that.

1 — Deeper Intent Analysis (what you described)
Instead of just asking "what do you want in a partner", use NLP to extract latent intent from everything the user gives you.
​

What to extract from onboarding answers:
Attachment style — anxious, secure, avoidant (detectable from how they write)

Communication style — deep talker vs light banter vs adventurous

Relationship readiness — casual, intentional, long-term

Dream partner archetype — derived from their answers, not just checkboxes

How to implement it:
Add a Groq LLM pass over the user's full onboarding answers at profile setup:

text
"ideal_first_date": "cosy, unhurried, good conversation over wine"
"dealbreaker": "people who are on their phone"
"values_in_partner": "emotional intelligence, ambition, warmth"
→ LLM extracts: ["emotionally mature", "present", "ambitious", "intimate not performative"]
→ Store as personality_archetype_tags in UserProfile
→ Feed into embedding

2 — Behavioural Signals (no social media needed)
These are signals from how the user uses the app itself:
​

Signal	What it reveals
Which venues they browse longest	True aesthetic preference
Which suggested dates they accept vs decline	Real vs stated preferences
Time of day they're active	When they actually want to date
How fast they respond to matches	Engagement level / serious intent
What free text they type in venue search	Mood and intent in real time
This becomes a feedback loop — every interaction makes the next recommendation smarter. Hinge's version of this produced 26% more matches and 2.5x more conversations.

How to implement:
Add a user_events table:

python
class UserEvent(Base):
    __tablename__ = "user_events"
    user_id:     int   # who
    event_type:  str   # "venue_view", "match_accept", "match_decline", "search"
    payload:     dict  # JSONB — venue_id, search_text, time_spent_ms etc.
    created_at:  datetime
Feed these into the embedding refresh pipeline weekly.

3 — Compatibility Scoring Between Two Users
Right now embeddings find users with similar tastes. But compatibility ≠ similarity. A deep talker matches better with another deep talker — but an introvert might complement an extrovert for venue choice.
​

Compatibility dimensions to score:
Dimension	How to score
Music/aesthetic overlap	Cosine similarity of Spotify signals
Communication style	Exact match (deep_talker ↔ deep_talker)
Energy level	Complementary scoring (high ↔ medium works, high ↔ low doesn't)
Relationship goal	Hard filter — must align
Availability overlap	Jaccard similarity of user_availability slots
Budget alignment	Within 1 band (mid ↔ premium = ok, budget ↔ luxury = no)
Build a compute_compatibility_score(user_a, user_b) function that returns a weighted float 0.0–1.0. This is your matching engine's core.

4 — The AI Date Planner (your textbox idea) ✅ Build this
This is genuinely differentiated. No other dating app does this. Here's exactly how it works:

text
User types: "I want a cosy dinner date in Bristol on Saturday evening,
             maybe somewhere with live jazz, mid-range price, followed
             by drinks nearby"
        ↓
AI Agent parses intent:
  - mood: cosy
  - genre: jazz
  - date: Saturday
  - budget: mid
  - city: Bristol
  - multi-stop: dinner + drinks
        ↓
Agent calls /venues/suggest with those params
        ↓
Returns: "Casa Mia (jazz, intimate, mid) → Hyde & Co (cocktail bar, 5 min walk)"
        ↓
Agent offers to book both
        ↓
Calls venue booking API / OpenTable / Resy API
        ↓
Confirms reservation in-app
APIs to call for booking:
Service	API	Free?
OpenTable	Restaurant booking API	Free for partners
Resy	Resy API	Free for partners
Fever	Experiences + events	Partner programme
Ticketmaster	Events / cinema	Free developer API
Vue / Odeon	Cinema tickets	No public API — scrape or email
For cinema specifically — Ticketmaster API is free and covers most UK cinema events. Vue has no public API but you can use their website's undocumented endpoints as a last resort.

5 — Personality Archetype System
Instead of showing raw compatibility scores, give users a fun identity like dating apps that retain users:
​

Archetype	Profile
The Curator	Loves hidden gem restaurants, thoughtful planner
The Adventurer	Spontaneous, tries new cuisines, high energy
The Nester	Cosy pubs, board games, low noise, deep conversation
The Social Butterfly	Lively bars, group-friendly, buzzy atmosphere
The Romantic	Candlelit dinners, wine bars, intimate venues
Derive this from their profile + social signals using a Groq LLM pass. Show it on their profile. Use it in venue matching — "The Nester" gets different suggestions than "The Adventurer" even if their explicit prefs are similar.

6 — Conversation Icebreaker Generator
After two users match, generate a personalised opening based on their shared signals:
​

text
"You both love jazz and Italian food —
 ask them about the best meal they've ever had"
Or:

text
"Your Spotify energy levels are similar but your aesthetics
 differ — that tension makes for great first date conversation"
One Groq call per match. Zero extra infrastructure.