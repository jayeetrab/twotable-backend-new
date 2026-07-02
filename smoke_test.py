"""
End-to-end smoke test for the TwoTable API.

Logs in with the dev account, then exercises every router (auth, profile, photos,
discovery + intent matcher, tonight, venues, bookings, geo/routing). Prints a
PASS/FAIL line per call and a summary.

Usage:
    python smoke_test.py                      # against http://127.0.0.1:8009
    BASE=https://your-host python smoke_test.py
    python smoke_test.py --destructive        # also test account-delete (uses a throwaway login)

Requires the server running and httpx (already a project dependency).
"""
from __future__ import annotations

import io
import os
import sys

import httpx

BASE = os.environ.get("BASE", "http://127.0.0.1:8009") + "/api/v1"
DEV_PHONE = "+44 7700900123"
DEV_CODE = "12345"
DESTRUCTIVE = "--destructive" in sys.argv

_passed = _failed = 0


def check(name, resp, ok=(200, 201, 204)):
    global _passed, _failed
    good = resp.status_code in ok
    _passed += good
    _failed += not good
    mark = "PASS" if good else "FAIL"
    print(f"  [{mark}] {name:<42} {resp.status_code}")
    return resp


def tiny_jpeg() -> bytes:
    # Minimal valid 1x1 JPEG so the upload path is exercised without a real asset.
    import base64
    return base64.b64decode(
        "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEB"
        "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/wAALCAABAAEBAREA/8QAFAABAAAA"
        "AAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AfwD/2Q==")


def main():
    c = httpx.Client(timeout=60.0)

    print("AUTH")
    check("POST auth/phone/start", c.post(f"{BASE}/auth/phone/start", json={"phone": DEV_PHONE}))
    r = check("POST auth/phone/verify", c.post(f"{BASE}/auth/phone/verify",
                                               json={"phone": DEV_PHONE, "code": DEV_CODE}))
    token = r.json()["access_token"]
    H = {"Authorization": f"Bearer {token}"}
    check("GET  auth/me", c.get(f"{BASE}/auth/me", headers=H))
    check("PATCH auth/me", c.patch(f"{BASE}/auth/me", headers=H, json={"full_name": "Dev Tester"}))

    print("PROFILE")
    check("GET  profile/me", c.get(f"{BASE}/profile/me", headers=H))
    check("POST profile/onboarding", c.post(f"{BASE}/profile/onboarding", headers=H, json={
        "first_name": "Dev", "bio": "I love quiet dinners and live jazz.",
        "interests": ["Jazz", "Cooking", "Hiking"], "intentions": ["Serious dating"],
        "date_preferences": ["Everyone"], "gender": "Man",
        "location": {"city": "Bristol", "postcode": "BS1 5TR"},
        "facts": {"drink": ["Sometimes"], "smokeCigarette": ["No"]},
        "prompts": [{"key": "my_ideal_sunday", "answer": "Coffee, a long walk, then cooking."}],
    }))
    check("GET  profile/availability", c.get(f"{BASE}/profile/availability", headers=H))
    check("POST profile/pause", c.post(f"{BASE}/profile/pause", headers=H))
    check("POST profile/resume", c.post(f"{BASE}/profile/resume", headers=H))

    print("PHOTOS (upload -> reorder -> delete)")
    up = check("POST profile/photos", c.post(f"{BASE}/profile/photos", headers=H,
              files={"file": ("t.jpg", io.BytesIO(tiny_jpeg()), "image/jpeg")}))
    if up.status_code == 200:
        pid = up.json()["photo_id"]
        # Reorder needs the FULL current set (a permutation), so read it back first.
        me = c.get(f"{BASE}/profile/me", headers=H).json()
        ids = [u.rsplit("/", 1)[-1] for u in me.get("photos", [])]
        check("PUT  profile/photos/order", c.put(f"{BASE}/profile/photos/order",
              headers=H, json={"order": list(reversed(ids))}))
        check("DEL  profile/photos/{id}", c.delete(f"{BASE}/profile/photos/{pid}", headers=H), ok=(204,))

    print("DISCOVERY (intent matcher)")
    feed = check("GET  discovery/feed", c.get(f"{BASE}/discovery/feed?limit=5", headers=H))
    profiles = feed.json().get("profiles", []) if feed.status_code == 200 else []
    if profiles:
        target = profiles[0]["user_id"]
        check("POST discovery/action (like)", c.post(f"{BASE}/discovery/action",
              headers=H, json={"target_id": target, "action": "like"}))
        check("GET  discovery/matches", c.get(f"{BASE}/discovery/matches", headers=H))
        check("DEL  discovery/matches/{id}", c.delete(f"{BASE}/discovery/matches/{target}", headers=H))

    print("TONIGHT'S TABLE")
    check("GET  tonight", c.get(f"{BASE}/tonight?city=Bristol", headers=H))
    check("POST tonight/opt-in", c.post(f"{BASE}/tonight/opt-in?city=Bristol", headers=H))
    check("GET  tonight/people", c.get(f"{BASE}/tonight/people", headers=H))
    check("DEL  tonight/opt-in", c.delete(f"{BASE}/tonight/opt-in", headers=H))

    print("VENUES")
    vl = check("GET  venues", c.get(f"{BASE}/venues?city=Bristol&limit=5", headers=H))
    venues = vl.json().get("venues", []) if vl.status_code == 200 else []
    if venues:
        vid = venues[0]["id"]
        check("GET  venues/{id}", c.get(f"{BASE}/venues/{vid}", headers=H))
        check("POST bookings/quick", c.post(f"{BASE}/bookings/quick", headers=H,
              json={"venue_id": vid, "date": "2026-07-01", "time": "19:30:00"}), ok=(200, 201))
    check("GET  bookings/mine", c.get(f"{BASE}/bookings/mine", headers=H))
    check("GET  venues/available", c.get(
        f"{BASE}/venues/available?date=2026-07-01&time=19:30:00&city=Bristol", headers=H))

    print("GEO + ROUTING")
    check("POST geo/geocode", c.post(f"{BASE}/geo/geocode", headers=H,
          json={"query": "Bristol"}), ok=(200, 404))  # 404 if no Mapbox token
    check("POST geo/reverse", c.post(f"{BASE}/geo/reverse", headers=H,
          json={"lat": 51.4545, "lng": -2.5879}))
    check("POST geo/travel-time", c.post(f"{BASE}/geo/travel-time", headers=H, json={
        "origin": {"lat": 51.4545, "lng": -2.5879}, "dest": {"lat": 51.4584, "lng": -2.5972}}))
    check("POST geo/matrix", c.post(f"{BASE}/geo/matrix", headers=H, json={
        "origin": {"lat": 51.4545, "lng": -2.5879},
        "destinations": [{"lat": 51.4584, "lng": -2.5972}, {"lat": 51.46, "lng": -2.60}]}))
    check("POST geo/isochrone", c.post(f"{BASE}/geo/isochrone", headers=H, json={
        "origin": {"lat": 51.4545, "lng": -2.5879}, "minutes": 15}), ok=(200, 503))
    check("POST geo/fair-venues", c.post(f"{BASE}/geo/fair-venues", headers=H, json={
        "origin_a": {"lat": 51.4545, "lng": -2.5879}, "origin_b": {"lat": 51.4645, "lng": -2.61},
        "mode_a": "drive", "mode_b": "walk", "city": "Bristol", "limit": 3}))
    check("GET  geo/fair-venues/match/{id}", c.get(
        f"{BASE}/geo/fair-venues/match/1", headers=H), ok=(200, 422))  # 422 if coords missing
    if venues:
        check("GET  geo/travel-options/{venue_id}", c.get(
            f"{BASE}/geo/travel-options/{venues[0]['id']}", headers=H), ok=(200, 404, 422))

    if DESTRUCTIVE:
        print("DESTRUCTIVE (throwaway account)")
        rr = c.post(f"{BASE}/auth/phone/verify", json={"phone": "+44 7000000099", "code": DEV_CODE})
        th = {"Authorization": f"Bearer {rr.json()['access_token']}"}
        check("DEL  profile/me (throwaway)", c.delete(f"{BASE}/profile/me", headers=th))

    print(f"\nDONE — {_passed} passed, {_failed} failed")
    c.close()
    sys.exit(1 if _failed else 0)


if __name__ == "__main__":
    main()
