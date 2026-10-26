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


def test_first_week_start():
    sun, mon = date(2026, 10, 25), date(2026, 10, 26)
    assert plan_tracker.first_week_start(None, sun) == mon  # Monday weeks: next Monday
    assert plan_tracker.first_week_start(None, mon) == mon
    assert plan_tracker.first_week_start(date(2026, 11, 5), sun) == date(2026, 11, 2)
    assert plan_tracker.first_week_start(None, sun, week_start=6) == sun  # Sunday weeks start today


def test_build_weeks_for_sunday_weeks():
    weeks = plan_tracker.build_weeks([_ai_week()], date(2026, 10, 25), 1)  # a Sunday
    days = weeks[0]["days"]
    assert days[0]["weekday"] == "sun" and days[-1]["weekday"] == "sat"
    assert days[-1]["description"] == "Long ride" and days[2]["type"] == "Zwift / indoor"


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
        json={
            "without_data": True,
            "title": "DC",
            "goal": "Double Century",
            "weeks": 2,
            "start_date": start.isoformat(),
        },
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


def test_apply_preferences_rest_day_becomes_a_ride_day():
    from datetime import date as d_

    day = lambda wd, t, desc, mins, w=None: {  # noqa: E731
        "date": f"2030-01-0{wd + 1}",
        "weekday": plan_tracker.WEEKDAYS[wd],
        "type": t,
        "description": desc,
        "duration_min": mins,
        "intensity": [],
        "locked": False,
        "workout": w,
    }
    weeks = [{"days": [day(0, "Rest", "Rest.", 0), day(1, "Zwift / indoor", "SS", 60, {"name": "SS"})]}]
    changed, empty = plan_tracker.apply_preferences(
        weeks, {"mon": ["Zwift / indoor"], "tue": ["Road"]}, d_(2029, 12, 31)
    )
    mon, tue = weeks[0]["days"]
    assert (changed, empty) == (2, 1)
    assert mon["type"] == "Zwift / indoor" and "not planned yet" in mon["description"]  # not "Rest."
    assert tue["type"] == "Road" and tue["description"] == "SS" and tue["workout"] is None


def test_replan_keeps_past_and_locked_days(plan_id, monkeypatch):
    p, plan = plan_id
    seen = {}

    async def fake_replan(db, viewer, athlete, facts):
        seen.update(facts["request"])
        week = {
            "phase": "Recovery",
            "focus": "easier after illness",
            "days": [
                {"weekday": k, "type": "Walk", "description": "Easy walk", "duration_min": 40, "intensity": ["Z1"]}
                for k in plan_tracker.WEEKDAYS
            ],
        }
        return {"summary_md": "Eased off.", "weeks": [week, week]}, "claude-test"

    monkeypatch.setattr("app.routers.plans.generate_plan", fake_replan)
    base = f"/api/athletes/me/plans/{plan['id']}"
    next_sat = plan["weeks"][1]["days"][5]["date"]
    p.patch(f"{base}/days/{next_sat}", json={"locked": True})
    r = p.post(f"{base}/replan", json={"reason": "I was sick"})
    assert r.status_code == 200, r.text
    today = date.today().isoformat()
    assert seen["start_date"] == plan["weeks"][0]["start"] and seen["weeks"] == 2
    assert seen["replan"]["reason"] == "I was sick"
    assert next_sat in [d["date"] for d in seen["replan"]["keep"]]
    for old_w, new_w in zip(plan["weeks"], r.json()["weeks"], strict=True):
        for old, new in zip(old_w["days"], new_w["days"], strict=True):
            if old["date"] < today or old["date"] == next_sat:
                assert new["type"] == old["type"] and new["description"] == old["description"]
            else:
                assert new["type"] == "Walk"
    assert r.json()["weeks"][1]["phase"] == "Recovery"
    assert "Re-planned" in r.json()["content_md"]


def test_replan_merge_in_code():
    weeks = plan_tracker.build_weeks([_ai_week()], MON, 1)
    weeks[0]["days"][5]["locked"] = True
    fresh = plan_tracker.build_weeks([{"phase": "Taper", "focus": "", "days": []}], MON, 1)
    today = MON + timedelta(days=2)  # Wednesday
    assert plan_tracker.replan_from(weeks, today) == 0
    assert plan_tracker.replan_from(weeks, MON + timedelta(days=7)) == 1
    changed = plan_tracker.merge_replan(weeks, fresh, today)
    days = weeks[0]["days"]
    assert days[1]["type"] == "Zwift / indoor"  # Tuesday is past
    assert days[5]["type"] == "Road"  # Saturday is locked
    assert changed == 0 and weeks[0]["phase"] == "Taper"  # the free days were already Rest


def test_replan_trains_on_the_preferred_days(plan_id, monkeypatch):
    p, plan = plan_id
    seen = {}

    async def fake(db, viewer, athlete, facts):
        seen.update(facts["request"])
        return {"summary_md": "ok", "weeks": []}, "claude-test"

    monkeypatch.setattr("app.routers.plans.generate_plan", fake)
    # The plan was made for Tue, Thu, Sat, Sun; preferences now say Wednesday is indoor and Sunday rest.
    p.request("PUT", "/api/me/preferences", json={"weekday_prefs": {"wed": ["Zwift / indoor"], "sun": ["Rest"]}})
    p.post(f"/api/athletes/me/plans/{plan['id']}/replan", json={"reason": "Wednesday is a ride day"})
    assert seen["available_days"] == ["Tue", "Wed", "Thu", "Sat"]
