"""Re-plan one day: a proposal next to the current day, used once approved."""

from datetime import date, timedelta

import pytest
from test_phase3 import STEADY, _next_monday, _scheduled, _week

from app.db import Activity, Plan, SessionLocal

DAY = {
    "weekday": "wed",
    "type": "Zwift / indoor",
    "description": "Openers: 3x1 min",
    "duration_min": 40,
    "intensity": ["Z2"],
    "workout": {"name": "Openers", "steps": STEADY},
}


@pytest.fixture()
def setup(make_user, monkeypatch):
    seen = {}

    async def fake_plan(db, viewer, athlete, facts):
        return {"summary_md": "Plan", "weeks": [_week(), _week()]}, "claude-test"

    async def fake_day(db, viewer, athlete, facts):
        seen["facts"] = facts
        return {
            "day": dict(DAY, weekday=facts["request"]["replan_day"]["weekday"]),
            "why": "Easier before the race",
        }, "m"

    monkeypatch.setattr("app.routers.plans.generate_plan", fake_plan)
    monkeypatch.setattr("app.routers.plans.generate_day", fake_day)
    athlete = make_user("a@example.com", "Ann")
    aid = athlete.get("/api/auth/me").json()["id"]
    with SessionLocal() as db:
        db.add(Activity(user_id=aid, source="strava", external_id="1", sport="Ride", start_time=date.today()))
        db.commit()
    plan = athlete.post(
        "/api/athletes/me/plans",
        json={"title": "Block", "goal": "FTP", "weeks": 2, "start_date": _next_monday().isoformat()},
    ).json()
    return athlete, aid, plan, seen


def test_day_proposal_then_approve(setup):
    athlete, aid, plan, seen = setup
    wed = (_next_monday() + timedelta(days=2)).isoformat()
    base = f"/api/athletes/me/plans/{plan['id']}"
    athlete.post(f"{base}/comments", json={"body": "Rest before the race?", "day": wed})
    r = athlete.post(f"{base}/days/{wed}/replan", json={"note": "Race on Saturday"})
    assert r.status_code == 200, r.text
    p = r.json()
    rd = seen["facts"]["request"]["replan_day"]
    assert rd["date"] == wed and rd["note"] == "Race on Saturday" and len(rd["week"]) == 6
    assert rd["comments"][0]["text"] == "Rest before the race?"
    assert p["pending"]["changes"][0]["after"]["description"] == "Openers: 3x1 min"
    assert p["pending"]["summary"] == "Easier before the race" and p["can_approve"] is True  # no coach
    before = [w.name for w in _scheduled(aid)]
    r = athlete.post(f"{base}/approve").json()
    day = next(d for w in r["weeks"] for d in w["days"] if d["date"] == wed)
    assert day["description"] == "Openers: 3x1 min" and day["workout"]["name"] == "Openers"
    assert "Openers" in [w.name for w in _scheduled(aid)] and len(_scheduled(aid)) == len(before) + 1
    assert r["history"][-2]["event"] == "day_proposed"


def test_past_locked_and_waiting_replans(setup):
    athlete, aid, plan, _ = setup
    base = f"/api/athletes/me/plans/{plan['id']}"
    mon = _next_monday()
    athlete.patch(f"{base}/days/{mon.isoformat()}", json={"locked": True})
    assert athlete.post(f"{base}/days/{mon.isoformat()}/replan", json={}).status_code == 409
    assert athlete.post(f"{base}/days/{(mon - timedelta(days=30)).isoformat()}/replan", json={}).status_code == 404
    # A full re-plan proposal waiting blocks a day re-plan (and the other way round replaces it).
    with SessionLocal() as db:
        db.get(Plan, plan["id"]).pending = {"fresh": [], "changes": []}
        db.commit()
    r = athlete.post(f"{base}/days/{(mon + timedelta(days=1)).isoformat()}/replan", json={})
    assert r.status_code == 409 and "waiting" in r.json()["detail"]


def test_the_route_picked_goes_to_the_ai_and_wins(setup):
    athlete, aid, plan, seen = setup
    link = "https://www.strava.com/routes/3234567890123456789"
    fav = athlete.post("/api/athletes/me/segments", json={"link": link, "name": "Loop B"}).json()
    sat = (_next_monday() + timedelta(days=5)).isoformat()
    base = f"/api/athletes/me/plans/{plan['id']}"
    athlete.patch(f"{base}/days/{sat}", json={"type": "Road", "segment_id": fav["id"]})
    athlete.post(f"{base}/days/{sat}/replan", json={"note": "Ride Loop B"})
    assert seen["facts"]["request"]["replan_day"]["current"]["segment_id"] == fav["id"]
    from app.coach import DAY_RULES

    assert "current.segment_id" in DAY_RULES and "win over `weekday_preferences`" in DAY_RULES
