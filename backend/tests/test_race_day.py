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


def test_race_after_the_plan_ends_adds_the_race_day(setup):
    p, plan, race, (course, _), _ = setup
    base = f"/api/athletes/me/plans/{plan['id']}"
    last = plan["weeks"][-1]["days"][-1]["date"]
    race_date = (date.fromisoformat(last) + timedelta(days=1)).isoformat()  # the day after the plan ends
    p.patch(f"/api/races/{race['id']}", json={"target_date": race_date, "segment_id": course, "target_time": "8:30"})
    out = p.post(f"{base}/race-day", json={"race_id": race["id"]}).json()
    assert len(out["weeks"]) == 3 and out["weeks"][-1]["phase"] == "Race"
    d = _day(out, race_date)
    assert d["type"] == "Race" and d["locked"] and d["race"]["name"] == "Double Century"
    assert d["segment"]["name"] == "DC course" and d["duration_min"] == 510
    assert d["description"] == "Double Century: race day. Start 06:00."
    after = _day(out, (date.fromisoformat(race_date) + timedelta(days=1)).isoformat())
    assert after["type"] == "Rest" and after["description"] == "Recovery after the race."

    # Too far after the plan, or before it: a new plan is the way.
    far = (date.fromisoformat(last) + timedelta(days=60)).isoformat()
    p.patch(f"/api/races/{race['id']}", json={"target_date": far})
    r = p.post(f"{base}/race-day", json={"race_id": race["id"]})
    assert r.status_code == 422 and "make a new plan" in r.json()["detail"]


def test_race_tag_on_the_route(setup):
    p, plan, race, (course, short), sat = setup
    assert "race" in p.get("/api/athletes/me/segments").json()["uses"]
    p.patch(f"/api/races/{race['id']}", json={"segment_id": course})
    fav = {f["id"]: f for f in p.get("/api/athletes/me/segments").json()["favourites"]}
    assert "race" in fav[course]["uses"] and fav[course]["races"] == ["Double Century"]
    assert fav[short]["races"] == [] and "race" not in (fav[short]["uses"] or [])
    # Tagged by hand too, like any other use.
    r = p.patch(f"/api/athletes/me/segments/{short}", json={"uses": ["long ride", "race"]})
    assert r.status_code == 200 and r.json()["uses"] == ["long ride", "race"]
