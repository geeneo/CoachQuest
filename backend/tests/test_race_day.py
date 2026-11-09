"""A plan day linked to one of the athlete's races, and a race's route (one of their saved routes)."""

from datetime import date, timedelta

import pytest

from app.db import Segment, SessionLocal
from tests.test_plan_tracker import _ai_week


@pytest.fixture()
def setup(make_user, monkeypatch):
    async def fake_generate(db, viewer, athlete, facts):
        return {"summary_md": "Summary", "weeks": [_ai_week(), _ai_week()]}, "claude-test"

    monkeypatch.setattr("app.routers.plans.generate_plan", fake_generate)
    p = make_user("a@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    start = date.today() - timedelta(days=date.today().weekday())
    plan = p.post(
        "/api/athletes/me/plans",
        json={"without_data": True, "title": "DC", "goal": "DC", "weeks": 2, "start_date": start.isoformat()},
    ).json()
    with SessionLocal() as db:
        loop = Segment(athlete_id=uid, strava_id=11, kind="route", name="DC course", distance_m=205000)
        other = Segment(athlete_id=uid, strava_id=12, kind="route", name="Short loop", distance_m=40000)
        db.add_all([loop, other])
        db.commit()
        ids = loop.id, other.id
    sat = plan["weeks"][1]["days"][5]["date"]
    race = p.post(
        "/api/races",
        json={"code": "dc", "name": "Double Century", "distance_km": 205, "target_date": sat, "start_time": "06:00"},
    ).json()
    return p, plan, race, ids, sat


def _day(plan, day):
    return next(d for w in plan["weeks"] for d in w["days"] if d["date"] == day)


def test_race_route_and_race_day(setup, make_user):
    p, plan, race, (course, short), sat = setup
    # The race's route: one of the athlete's saved routes.
    assert p.patch(f"/api/races/{race['id']}", json={"segment_id": 99999}).status_code == 422
    assert p.patch(f"/api/races/{race['id']}", json={"segment_id": course}).json()["segment_id"] == course

    # Linking a day to the race makes it a locked Race day that rides the race's route.
    base = f"/api/athletes/me/plans/{plan['id']}"
    out = p.patch(f"{base}/days/{sat}", json={"race_id": race["id"]}).json()
    d = _day(out, sat)
    assert d["type"] == "Race" and d["locked"] and d["race_id"] == race["id"]
    assert d["race"]["name"] == "Double Century" and d["race"]["start_time"] == "06:00"
    assert d["segment"]["name"] == "DC course"

    # Another route picked on the race moves the linked plan day along.
    p.patch(f"/api/races/{race['id']}", json={"segment_id": short})
    assert _day(p.get(f"{base}").json(), sat)["segment"]["name"] == "Short loop"

    # A route on the day itself, and back to an ordinary day.
    d = _day(p.patch(f"{base}/days/{sat}", json={"segment_id": course}).json(), sat)
    assert d["segment"]["name"] == "DC course" and d["race_id"] == race["id"]
    d = _day(p.patch(f"{base}/days/{sat}", json={"type": "Road"}).json(), sat)
    assert d["race_id"] is None and "race" not in d

    # Someone else's race can't be linked.
    other = make_user("b@example.com")
    theirs = other.post("/api/races", json={"code": "x", "name": "X"}).json()
    assert p.patch(f"{base}/days/{sat}", json={"race_id": theirs["id"]}).status_code == 422
