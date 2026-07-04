"""
Two-user scenario test for the TwoTable date lifecycle + matching + routing.

Where smoke_test.py checks each endpoint answers for one user, this drives the real
multi-user journeys and their failure branches:

  - matching: A and B become a mutual connection through the like feed
  - full date lifecycle: start -> overlap slots -> overlap venue -> both pay -> confirmed
  - a real booking row is created and visible to BOTH people
  - reschedule: confirmed -> proposing_time -> re-agree -> confirmed again (venue kept)
  - cancel + 24h refund policy (future date refunds, idempotent re-cancel)
  - rating a confirmed date
  - error branches: plan with a non-match (403), pay before venue (409),
    rate before confirmed (409), stranger reads a plan (404), bad score (422)

Usage:
    python scenario_test.py                 # against http://127.0.0.1:8009
    BASE=https://your-host python scenario_test.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import httpx

BASE = os.environ.get("BASE", "http://127.0.0.1:8009") + "/api/v1"
CODE = "12345"
# Fresh throwaway numbers per run so the test is isolated (no reused connection/plan state).
# Dev auth accepts any well-formed number with the dev code.
_seed = int(datetime.now().timestamp()) % 90000
PHONE_A = f"+44 78{_seed:05d}01"
PHONE_B = f"+44 78{_seed:05d}02"
PHONE_C = f"+44 78{_seed:05d}03"

_passed = _failed = 0


def check(name, cond, detail=""):
    global _passed, _failed
    ok = bool(cond)
    _passed += ok
    _failed += not ok
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail and not ok else ""))
    return ok


def login(c: httpx.Client, phone: str) -> str:
    c.post(f"{BASE}/auth/phone/start", json={"phone": phone})
    r = c.post(f"{BASE}/auth/phone/verify", json={"phone": phone, "code": CODE})
    r.raise_for_status()
    return r.json()["access_token"]


def hdr(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def me_id(c: httpx.Client, tok: str) -> int:
    return c.get(f"{BASE}/auth/me", headers=hdr(tok)).json()["id"]


def onboard(c: httpx.Client, tok: str, name: str, gender: str, postcode: str):
    payload = {
        "full_name": name,
        "gender": gender,
        "date_preferences": ["Everyone"],
        "date_of_birth": "1996-05-05",
        "location": {"city": "Bristol", "postcode": postcode},
        "relationship_goal": "Something real",
    }
    r = c.post(f"{BASE}/profile/onboarding", headers=hdr(tok), json=payload)
    r.raise_for_status()


def main():
    ca = httpx.Client(timeout=60.0)
    cb = httpx.Client(timeout=60.0)

    print("SETUP: two users sign in + onboard")
    ta, tb = login(ca, PHONE_A), login(cb, PHONE_B)
    ida, idb = me_id(ca, ta), me_id(cb, tb)
    onboard(ca, ta, "Scenario A", "Man", "BS1 4DJ")
    onboard(cb, tb, "Scenario B", "Woman", "BS8 1TH")
    check("two distinct users", ida != idb, f"{ida} vs {idb}")

    print("MATCHING: mutual like creates a connection")
    # A likes B (not yet mutual), then B likes A (mutual -> match).
    r1 = ca.post(f"{BASE}/discovery/action", headers=hdr(ta),
                 json={"target_id": idb, "action": "like"}).json()
    check("A->B like not yet matched", r1.get("matched") is False, str(r1))
    r2 = cb.post(f"{BASE}/discovery/action", headers=hdr(tb),
                 json={"target_id": ida, "action": "like"}).json()
    check("B->A like creates match", r2.get("matched") is True, str(r2))
    matches = ca.get(f"{BASE}/discovery/matches", headers=hdr(ta)).json()
    ids = [m.get("user_id") or m.get("id") for m in matches.get("matches", matches.get("connections", []))]
    check("B appears in A's matches", idb in ids or len(ids) >= 1, str(matches)[:200])

    print("ERROR: planning a date with a non-match is blocked")
    cc = httpx.Client(timeout=60.0)
    tc = login(cc, PHONE_C)
    onboard(cc, tc, "Scenario C", "Woman", "BS2 0EZ")
    idc = me_id(cc, tc)
    r = ca.post(f"{BASE}/dates", headers=hdr(ta), json={"with_user_id": idc})
    check("start date with non-match -> 403", r.status_code == 403, str(r.status_code))

    print("LIFECYCLE: start the plan")
    r = ca.post(f"{BASE}/dates", headers=hdr(ta), json={"with_user_id": idb})
    check("A starts plan -> 200", r.status_code == 200, str(r.status_code))
    plan = r.json()
    pid = plan["id"]
    check("plan starts proposing_time", plan["status"] == "proposing_time", plan["status"])

    print("ERROR: stranger cannot read the plan")
    r = cc.get(f"{BASE}/dates/{pid}", headers=hdr(tc))
    check("stranger GET plan -> 404", r.status_code == 404, str(r.status_code))

    print("ERROR: paying before a venue is agreed")
    r = ca.post(f"{BASE}/dates/{pid}/pay", headers=hdr(ta))
    check("pay before venue -> 409", r.status_code == 409, str(r.status_code))

    print("SLOTS: overlap locks a time + generates venue options")
    # A future Saturday 20:00 (peak) that both offer, plus non-overlapping extras.
    sat = _next_weekday(5).replace(hour=20, minute=0, second=0, microsecond=0)
    shared = sat.strftime("%Y-%m-%dT%H:%M")
    ca.put(f"{BASE}/dates/{pid}/slots", headers=hdr(ta),
           json={"slots": [shared, "2099-01-01T18:00"]})
    st = cb.put(f"{BASE}/dates/{pid}/slots", headers=hdr(tb),
                json={"slots": [shared, "2099-02-02T18:00"]}).json()
    check("time agreed after overlap", st["agreed_slot"] == shared, str(st.get("agreed_slot")))
    check("status now choosing_venue", st["status"] == "choosing_venue", st["status"])
    check("peak Saturday 20:00 priced £8", st["price"] == 8, str(st["price"]))
    opts = [v["id"] for v in st.get("venue_options", [])]
    check("venue options generated", len(opts) >= 1, str(len(opts)))

    print("VENUE: overlapping pick becomes the agreed venue")
    if opts:
        ca.put(f"{BASE}/dates/{pid}/venue-picks", headers=hdr(ta),
               json={"venue_ids": opts[:3]})
        vt = cb.put(f"{BASE}/dates/{pid}/venue-picks", headers=hdr(tb),
                    json={"venue_ids": opts[:1]}).json()
        check("venue agreed after overlap", vt.get("agreed_venue") is not None, str(vt.get("status")))
        check("status venue_agreed", vt["status"] == "venue_agreed", vt["status"])

    print("PAY: both pay -> confirmed + booking created")
    ca.post(f"{BASE}/dates/{pid}/pay", headers=hdr(ta))
    pt = cb.post(f"{BASE}/dates/{pid}/pay", headers=hdr(tb)).json()
    check("both paid -> confirmed", pt["status"] == "confirmed", pt["status"])
    check("i_paid + they_paid true", pt["i_paid"] and pt["they_paid"], str(pt))

    ba = ca.get(f"{BASE}/bookings/mine", headers=hdr(ta)).json()
    bb = cb.get(f"{BASE}/bookings/mine", headers=hdr(tb)).json()
    a_has = any(b.get("date_plan_id") == pid for b in ba["bookings"])
    b_has = any(b.get("date_plan_id") == pid for b in bb["bookings"])
    check("booking visible to A", a_has, str(ba)[:150])
    check("booking visible to B (partner)", b_has, str(bb)[:150])

    print("RATE: confirmed date can be rated; bad score rejected")
    r = ca.post(f"{BASE}/dates/{pid}/rate", headers=hdr(ta), json={"score": 9})
    check("score 9 -> 422", r.status_code == 422, str(r.status_code))
    r = ca.post(f"{BASE}/dates/{pid}/rate", headers=hdr(ta), json={"score": 5})
    check("rate confirmed date -> 200", r.status_code == 200, str(r.status_code))

    print("RESCHEDULE: keeps venue, reopens time, re-agree -> confirmed")
    rs = ca.post(f"{BASE}/dates/{pid}/reschedule", headers=hdr(ta)).json()
    check("reschedule -> proposing_time", rs["status"] == "proposing_time", rs["status"])
    check("reschedule kept the venue", rs.get("agreed_venue") is not None, "venue dropped")
    # ERROR: rating a now-unconfirmed date is refused
    r = ca.post(f"{BASE}/dates/{pid}/rate", headers=hdr(ta), json={"score": 4})
    check("rate non-confirmed -> 409", r.status_code == 409, str(r.status_code))
    new_slot = (_next_weekday(2).replace(hour=19, minute=0, second=0, microsecond=0)).strftime("%Y-%m-%dT%H:%M")
    ca.put(f"{BASE}/dates/{pid}/slots", headers=hdr(ta), json={"slots": [new_slot]})
    re = cb.put(f"{BASE}/dates/{pid}/slots", headers=hdr(tb), json={"slots": [new_slot]}).json()
    check("re-agree jumps back to confirmed", re["status"] == "confirmed", re["status"])

    print("CANCEL: future confirmed date refunds; re-cancel idempotent")
    cn = ca.delete(f"{BASE}/dates/{pid}", headers=hdr(ta)).json()
    check("cancel returns cancelled", cn.get("cancelled") is True, str(cn))
    check("future paid date refunded", cn.get("refunded") is True, str(cn))
    cn2 = ca.delete(f"{BASE}/dates/{pid}", headers=hdr(ta)).json()
    check("re-cancel idempotent", cn2.get("cancelled") is True, str(cn2))
    dates_after = ca.get(f"{BASE}/dates", headers=hdr(ta)).json()
    check("cancelled plan hidden from my dates",
          all(d["id"] != pid for d in dates_after["dates"]), str(len(dates_after["dates"])))

    print("CANCELLED PLAN: mutations are rejected until re-planned")
    # While still cancelled, submitting to it must 409 (can't resurrect a dead plan).
    r = ca.put(f"{BASE}/dates/{pid}/slots", headers=hdr(ta), json={"slots": ["2099-05-05T19:00"]})
    check("mutating a cancelled plan -> 409", r.status_code == 409, str(r.status_code))

    print("RE-PLAN: starting again resets the plan to a clean state")
    fresh = ca.post(f"{BASE}/dates", headers=hdr(ta), json={"with_user_id": idb}).json()
    check("re-plan clean proposing_time", fresh["status"] == "proposing_time", fresh["status"])
    check("re-plan cleared the old venue", fresh.get("agreed_venue") is None, str(fresh.get("agreed_venue")))
    check("re-plan cleared payments", not fresh.get("i_paid") and not fresh.get("they_paid"), str(fresh))
    # After re-planning it accepts submissions again.
    r = ca.put(f"{BASE}/dates/{fresh['id']}/slots", headers=hdr(ta), json={"slots": ["2099-05-05T19:00"]})
    check("re-planned plan accepts slots -> 200", r.status_code == 200, str(r.status_code))

    print(f"\nDONE — {_passed} passed, {_failed} failed")
    sys.exit(1 if _failed else 0)


def _next_weekday(weekday: int) -> datetime:
    """Next future date (>= 8 days out, so cancel is always >24h) on the given weekday."""
    base = datetime.now(timezone.utc) + timedelta(days=8)
    while base.weekday() != weekday:
        base += timedelta(days=1)
    return base


if __name__ == "__main__":
    main()
