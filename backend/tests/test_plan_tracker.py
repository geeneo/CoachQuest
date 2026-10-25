from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app import plan_tracker
from app.db import Activity, SessionLocal

MON = date(2026, 10, 19)


def _ai_week():
    return {
        "phase": "Build",
        "focus": "build toward DC",
        "days": [
            {
                "weekday": "tue",
                "type": "Zwift / indoor",
                "description": "Hill repeats",
                "duration_min": 65,
                "intensity": ["95-105% FTP"],
            },
            {"weekday": "sat", "type": "Road", "description": "Long ride", "duration_min": 120, "intensity": ["Z2"]},
            {"weekday": "sat", "type": "Run", "description": "duplicate", "duration_min": 30, "intensity": []},
        ],
    }


def test_build_weeks_dates_and_fills_rest():
    weeks = plan_tracker.build_weeks([_ai_week()], MON, 2)
    assert [w["start"] for w in weeks] == ["2026-10-19", "2026-10-26"]
    days = weeks[0]["days"]
    assert [d["date"] for d in days][:2] == ["2026-10-19", "2026-10-20"]
    assert days[0]["type"] == "Rest" and days[1]["type"] == "Zwift / indoor"
    assert days[5]["description"] == "Long ride"  # first Saturday entry wins
    assert all(d["type"] == "Rest" for d in weeks[1]["days"])  # Claude gave only one week


def test_first_monday():
    assert plan_tracker.first_monday(None, date(2026, 10, 25)) == date(2026, 10, 26)  # Sunday -> next Monday
    assert plan_tracker.first_monday(None, date(2026, 10, 26)) == date(2026, 10, 26)
    assert plan_tracker.first_monday(date(2026, 11, 5), date(2026, 10, 25)) == date(2026, 11, 2)


def _act(day, minutes):
    return SimpleNamespace(
        start_time=datetime.combine(day, datetime.min.time()) + timedelta(hours=7),
        duration_s=minutes * 60,
        distance_m=40000,
        elevation_m=500,
        relative_effort=80,
        avg_power=150,
        avg_hr=130,
        name="Ride",
        sport="Ride",
        indoor=False,
        type_override=None,
    )


def test_statuses():
    weeks = plan_tracker.build_weeks([_ai_week()], MON, 1)
    acts = [_act(MON + timedelta(days=5), 130), _act(MON + timedelta(days=0), 40)]  # Sat long ride, Mon extra
    today = MON + timedelta(days=5)  # Saturday
    w = plan_tracker.with_actuals(weeks, acts, today)[0]
    status = {d["weekday"]: d["status"] for d in w["days"]}
    assert status["mon"] == "extra" and status["tue"] == "missed" and status["sat"] == "goal_met"
    assert status["sun"] == "planned" and w["is_current"]
    short = plan_tracker.with_actuals(weeks, [_act(MON + timedelta(days=5), 60)], today)[0]
    assert short["days"][5]["status"] == "partial"


@pytest.fixture()
def plan_id(make_user, monkeypatch):
    async def fake_generate(db, viewer, athlete, facts):
        return {"summary_md": "Summary", "weeks": [_ai_week(), _ai_week()]}, "claude-test"

    monkeypatch.setattr("app.routers.plans.generate_plan", fake_generate)
    p = make_user("a@example.com")
    start = date.today() - timedelta(days=date.today().weekday())  # this Monday
    r = p.post(
        "/api/athletes/me/plans",
        json={"title": "DC", "goal": "Double Century", "weeks": 2, "start_date": start.isoformat()},
    )
    assert r.status_code == 200, r.text
    return p, r.json()


def test_created_plan_is_structured_and_current(plan_id):
    p, plan = plan_id
    assert plan["structured"] and len(plan["weeks"]) == 2 and plan["weeks"][0]["is_current"]
    assert p.get("/api/athletes/me/plans/current").json()["id"] == plan["id"]


def test_edit_lock_swap(plan_id):
    p, plan = plan_id
    base = f"/api/athletes/me/plans/{plan['id']}"
    tue, sat = plan["weeks"][1]["days"][1]["date"], plan["weeks"][1]["days"][5]["date"]
    r = p.patch(f"{base}/days/{tue}", json={"description": "Kendal climb x7", "intensity": ["95-105% FTP", " "]})
    day = r.json()["weeks"][1]["days"][1]
    assert day["description"] == "Kendal climb x7" and day["intensity"] == ["95-105% FTP"]
    assert p.patch(f"{base}/days/{tue}", json={"type": "Skydiving"}).status_code == 422
    r = p.post(f"{base}/swap", json={"a": tue, "b": sat})
    days = r.json()["weeks"][1]["days"]
    assert days[1]["type"] == "Road" and days[5]["description"] == "Kendal climb x7"
    p.patch(f"{base}/days/{sat}", json={"locked": True})
    assert p.post(f"{base}/swap", json={"a": tue, "b": sat}).status_code == 409


def test_missed_reason_and_logged_activity(plan_id):
    p, plan = plan_id
    uid = p.get("/api/auth/me").json()["id"]
    mon = date.fromisoformat(plan["weeks"][0]["start"])
    with SessionLocal() as db:
        db.add(
            Activity(
                user_id=uid,
                source="strava",
                external_id="x",
                name="Long ride",
                sport="Ride",
                start_time=datetime.combine(mon + timedelta(days=5), datetime.min.time()) + timedelta(hours=7),
                duration_s=7800,
                distance_m=120700,
                elevation_m=1213,
            )
        )
        db.commit()
    base = f"/api/athletes/me/plans/{plan['id']}"
    tue = plan["weeks"][0]["days"][1]["date"]
    r = p.patch(f"{base}/days/{tue}", json={"missed_reason": "work-trip"})
    sat = r.json()["weeks"][0]["days"][5]
    assert r.json()["weeks"][0]["days"][1]["missed_reason"] == "work-trip"
    if date.today() >= mon + timedelta(days=5):
        assert sat["status"] == "goal_met" and sat["actual"]["km"] == 120.7


def test_apply_preferences_only_future_unlocked(plan_id):
    p, plan = plan_id
    p.request("PUT", "/api/me/preferences", json={"weekday_prefs": {"tue": ["Rest"], "sat": ["MTB"]}})
    base = f"/api/athletes/me/plans/{plan['id']}"
    next_sat = plan["weeks"][1]["days"][5]["date"]
    p.patch(f"{base}/days/{next_sat}", json={"locked": True})
    r = p.post(f"{base}/apply-preferences").json()
    nxt = r["weeks"][1]["days"]
    assert nxt[1]["type"] == "Rest" and nxt[5]["type"] == "Road"  # Saturday locked, kept
