"""Plans that schedule their own workouts, stored completion, and planned vs actual."""

from datetime import date, datetime, timedelta

import pytest

from app import assessments, coach, compliance
from app.db import Activity, ScheduledWorkout, SessionLocal, User

STEADY = [{"kind": "steady", "duration_s": 3600, "power": 0.8}]
HARD = [
    {"kind": "warmup", "duration_s": 600, "power_start": 0.5, "power_end": 0.75},
    {"kind": "intervals", "repeat": 4, "on_s": 300, "on_power": 1.05, "off_s": 300, "off_power": 0.5},
    {"kind": "cooldown", "duration_s": 600, "power_start": 0.6, "power_end": 0.4},
]


def _week(tue_steps=STEADY, thu_steps=HARD):
    return {
        "phase": "Build",
        "focus": "indoor work",
        "days": [
            {
                "weekday": "tue",
                "type": "Zwift / indoor",
                "description": "Tempo",
                "duration_min": 60,
                "intensity": ["Z3"],
                "workout": {"name": "Tempo hour", "steps": tue_steps},
            },
            {
                "weekday": "thu",
                "type": "Zwift / indoor",
                "description": "Threshold",
                "duration_min": 60,
                "intensity": [],
                "workout": {"name": "4x5 threshold", "steps": thu_steps},
            },
            {
                "weekday": "sat",
                "type": "Road",
                "description": "Long ride",
                "duration_min": 180,
                "intensity": ["Z2"],
                "workout": None,
            },
        ],
    }


@pytest.fixture()
def planner(monkeypatch):
    weeks = {"value": [_week(), _week()]}

    async def fake_generate(db, viewer, athlete, facts):
        return {"summary_md": "Plan", "weeks": weeks["value"]}, "claude-test"

    monkeypatch.setattr("app.routers.plans.generate_plan", fake_generate)
    return weeks


def _next_monday():
    t = date.today()
    return t + timedelta(days=7 - t.weekday())


def _create(p, **extra):
    r = p.post(
        "/api/athletes/me/plans",
        json={"title": "Block", "goal": "FTP", "weeks": 2, "start_date": _next_monday().isoformat(), **extra},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _scheduled(uid):
    with SessionLocal() as db:
        return db.query(ScheduledWorkout).filter_by(athlete_id=uid).order_by(ScheduledWorkout.day).all()


def _uid(p):
    return p.get("/api/auth/me").json()["id"]


# ---- The schema Claude fills in ----


def test_plan_schema_is_strict():
    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False, node
                assert set(node["required"]) <= set(node["properties"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    schema = coach.plan_schema()["schema"]
    walk(schema)
    day = schema["properties"]["weeks"]["items"]["properties"]["days"]["items"]
    assert "workout" in day["required"]
    assert "structured `workout`" in coach.SYSTEM_PROMPT


# ---- Plans schedule their indoor workouts ----


def test_plan_puts_indoor_workouts_on_calendar(make_user, planner):
    p = make_user("a@example.com")
    plan = _create(p)
    rows = _scheduled(_uid(p))
    mon = _next_monday()
    assert [(r.day, r.name) for r in rows] == [
        (mon + timedelta(1), "Tempo hour"),
        (mon + timedelta(3), "4x5 threshold"),
        (mon + timedelta(8), "Tempo hour"),
        (mon + timedelta(10), "4x5 threshold"),
    ]
    assert all(r.plan_id == plan["id"] and r.plan_managed and r.description in ("Tempo", "Threshold") for r in rows)
    day = plan["weeks"][0]["days"][1]
    assert day["workout"]["name"] == "Tempo hour" and day["workout"]["steps"][0]["power"] == 0.8
    cal = p.get(f"/api/athletes/me/calendar?start={mon}&end={mon + timedelta(6)}").json()
    assert cal["days"][1]["workouts"][0]["from_plan"] is True


def test_invalid_or_switched_off_workouts_are_not_scheduled(make_user, planner):
    planner["value"] = [_week(thu_steps=[{"kind": "steady", "duration_s": 600, "power": 9}])]
    p = make_user("a@example.com")
    _create(p, weeks=1)
    assert [r.name for r in _scheduled(_uid(p))] == ["Tempo hour"]
    q = make_user("b@example.com")
    _create(q, weeks=1, structured_workouts=False)
    assert _scheduled(_uid(q)) == []


def test_day_edits_and_swaps_follow_the_plan(make_user, planner):
    p = make_user("a@example.com")
    plan = _create(p)
    base = f"/api/athletes/me/plans/{plan['id']}"
    mon = _next_monday()
    tue, wed = (mon + timedelta(1)).isoformat(), (mon + timedelta(2)).isoformat()
    # No longer an indoor day: its workout comes off the calendar; back again: it returns.
    p.patch(f"{base}/days/{tue}", json={"type": "Road"})
    assert tue not in [r.day.isoformat() for r in _scheduled(_uid(p))]
    p.patch(f"{base}/days/{tue}", json={"type": "Zwift / indoor"})
    assert tue in [r.day.isoformat() for r in _scheduled(_uid(p))]
    # Swapping moves the workout with the session.
    p.post(f"{base}/swap", json={"a": tue, "b": wed})
    days = {r.day.isoformat(): r.name for r in _scheduled(_uid(p))}
    assert days.get(wed) == "Tempo hour" and tue not in days


def test_replan_updates_plan_workouts_but_not_hand_edited_ones(make_user, planner):
    p = make_user("a@example.com")
    plan = _create(p)
    mon = _next_monday()
    rows = _scheduled(_uid(p))
    # The athlete moves Thursday's workout to Friday by hand.
    thu = next(r for r in rows if r.day == mon + timedelta(3))
    p.patch(f"/api/athletes/me/workouts/{thu.id}", json={"day": (mon + timedelta(4)).isoformat()})
    planner["value"] = [
        _week(tue_steps=[{"kind": "steady", "duration_s": 2700, "power": 0.7}]),
        _week(tue_steps=[{"kind": "steady", "duration_s": 2700, "power": 0.7}]),
    ]
    r = p.post(f"/api/athletes/me/plans/{plan['id']}/replan", json={"reason": "less time"})
    assert r.status_code == 200, r.text
    rows = _scheduled(_uid(p))
    tue = next(x for x in rows if x.day == mon + timedelta(1))
    assert tue.steps[0]["duration_s"] == 2700
    # Hand-moved workout stays on Friday, and Thursday gets no second copy.
    assert [x.day for x in rows if x.name == "4x5 threshold"] == [mon + timedelta(4), mon + timedelta(10)]
    assert len(rows) == 4


def test_deleting_a_plan_removes_its_upcoming_workouts(make_user, planner):
    p = make_user("a@example.com")
    plan = _create(p)
    mon = _next_monday()
    keep = _scheduled(_uid(p))[0]
    p.patch(f"/api/athletes/me/workouts/{keep.id}", json={"name": "My own now"})
    p.delete(f"/api/athletes/me/plans/{plan['id']}")
    rows = _scheduled(_uid(p))
    assert [(r.name, r.plan_id) for r in rows] == [("My own now", None)] and rows[0].day == mon + timedelta(1)


def test_plan_workouts_are_delivered(make_user, planner, monkeypatch):
    import httpx

    from app import runtime
    from app.delivery import intervals_icu as icu
    from tests.test_sync import FakeIntervals, _connect

    fake = FakeIntervals()
    monkeypatch.setattr(icu, "transport", httpx.MockTransport(fake.handler))
    monkeypatch.setitem(runtime._overrides, "intervals_client_id", "app")
    monkeypatch.setitem(runtime._overrides, "intervals_client_secret", "secret-secret")
    p = make_user("a@example.com")
    _connect(_uid(p))
    p.request("PUT", "/api/me/platforms", json={"auto": {"intervals_icu": True}})
    _create(p)
    assert sorted(c[2][0]["name"] for c in fake.upserts()) == ["4x5 threshold"] * 2 + ["Tempo hour"] * 2


# ---- Completion ----


def _ride(uid, day, minutes, ext, name="Morning Ride", sport="VirtualRide", **kw):
    with SessionLocal() as db:
        a = Activity(
            user_id=uid,
            source="strava",
            external_id=ext,
            name=name,
            sport=sport,
            start_time=datetime.combine(day, datetime.min.time()) + timedelta(hours=kw.pop("hour", 7)),
            duration_s=minutes * 60,
            distance_m=30000,
            **kw,
        )
        db.add(a)
        db.commit()
        return a.id


def _schedule(p, day, name, steps=STEADY):
    return p.post("/api/athletes/me/workouts", json={"day": day.isoformat(), "name": name, "steps": steps}).json()


def _cal_day(p, day):
    return p.get(f"/api/athletes/me/calendar?start={day}&end={day}").json()["days"][0]


def test_matching_prefers_the_ride_named_like_the_workout(make_user):
    p = make_user("a@example.com")
    uid = _uid(p)
    day = date.today() - timedelta(days=2)
    a = _schedule(p, day, "Sweet Spot")
    b = _schedule(p, day, "Recovery spin", [{"kind": "steady", "duration_s": 1800, "power": 0.5}])
    commute = _ride(uid, day, 30, "1", name="Commute", sport="Ride", hour=6)
    zwift = _ride(uid, day, 62, "2", name="Zwift - Sweet Spot in Watopia", hour=18)
    ws = {w["id"]: w for w in _cal_day(p, day)["workouts"]}
    assert ws[a["id"]]["actual"]["activities"][0]["id"] == zwift and ws[a["id"]]["status"] == "done"
    assert ws[b["id"]]["actual"]["activities"][0]["id"] == commute
    with SessionLocal() as db:
        assert db.get(ScheduledWorkout, a["id"]).activity_id == zwift  # stored, not just shown


def test_manual_pick_none_and_auto(make_user):
    p = make_user("a@example.com")
    uid = _uid(p)
    day = date.today() - timedelta(days=3)
    w = _schedule(p, day, "Tempo")
    other = _schedule(p, day + timedelta(1), "Other")
    late = _ride(uid, day + timedelta(1), 60, "9", name="Late upload")
    # Automatically it matches the next day's workout; the athlete says it was really Tempo.
    assert _cal_day(p, day + timedelta(1))["workouts"][0]["actual"]["activities"][0]["id"] == late
    cands = p.get(f"/api/athletes/me/workouts/{w['id']}/candidates").json()
    assert [c["id"] for c in cands] == [late] and cands[0]["used_by"] == "Other"
    p.patch(f"/api/athletes/me/workouts/{w['id']}", json={"activity_id": late})
    assert _cal_day(p, day)["workouts"][0]["match"] == "manual"
    assert _cal_day(p, day)["workouts"][0]["status"] == "done"
    assert _cal_day(p, day + timedelta(1))["workouts"][0]["status"] == "missed"  # one ride, one workout
    # "Not done" sticks; "auto" hands it back to matching.
    p.patch(f"/api/athletes/me/workouts/{w['id']}", json={"match": "none"})
    assert _cal_day(p, day)["workouts"][0]["status"] == "missed"
    p.patch(f"/api/athletes/me/workouts/{other['id']}", json={"match": "auto"})
    assert _cal_day(p, day + timedelta(1))["workouts"][0]["status"] == "done"
    assert p.patch(f"/api/athletes/me/workouts/{w['id']}", json={"activity_id": 999999}).status_code == 404


# ---- Planned vs actual ----


def test_compliance_week(make_user):
    p = make_user("a@example.com")
    uid = _uid(p)
    p.patch("/api/me", json={"ftp_watts": 250})
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    if today.weekday() < 3:  # need three days already past in this week
        monday -= timedelta(days=7)
    done = _schedule(p, monday, "Tempo")  # planned 1 h at 0.8 -> NP 200 W
    _ride(uid, monday, 60, "a", avg_power=170, norm_power=172, avg_hr=140, tss=50)
    _schedule(p, monday + timedelta(1), "Short one")
    _ride(uid, monday + timedelta(1), 30, "b", norm_power=200)
    _schedule(p, monday + timedelta(2), "Missed one")
    skipped = _schedule(p, monday + timedelta(2), "Skipped one")
    p.patch(f"/api/athletes/me/workouts/{skipped['id']}", json={"status": "skipped"})
    report = p.get("/api/athletes/me/compliance?weeks=2").json()
    week = next(w for w in report["weeks"] if w["week_start"] == monday.isoformat())
    assert (week["done"], week["partial"], week["missed"], week["skipped"]) == (1, 1, 1, 1)
    assert week["compliance_pct"] == round(100 * (60 + 30) / 180)
    tempo = next(w for w in week["workouts"] if w["id"] == done["id"])
    assert tempo["planned_np"] == 200 and tempo["actual_np"] == 172 and tempo["power_pct"] == 86
    assert tempo["flags"] == ["under_target"] and week["under_target"] == 1 and week["short"] == 1


def test_compliance_respects_scopes(make_user):
    athlete = make_user("a@example.com", "Athlete")
    uid = _uid(athlete)
    athlete.patch("/api/me", json={"ftp_watts": 250})
    coach = make_user("c@example.com", "Coach")
    g = athlete.post("/api/grants", json={"coach_email": "c@example.com", "scopes": ["plans"]}).json()
    coach.post(f"/api/grants/{g['id']}/accept")
    day = date.today() - timedelta(days=1)
    _schedule(athlete, day, "Tempo")
    _ride(uid, day, 60, "x", norm_power=210, tss=60)
    weeks = coach.get(f"/api/athletes/{uid}/compliance?weeks=2").json()["weeks"]
    w = next(x for x in weeks for y in x["workouts"])["workouts"][0]
    assert w["status"] == "done" and w["completion_pct"] == 100
    assert "actual_np" not in w and "planned_np" not in w and "actual_tss" not in weeks[0]


def test_weekly_review_gets_compliance(make_user):
    p = make_user("a@example.com")
    uid = _uid(p)
    today = date.today()
    monday = today - timedelta(days=today.weekday()) - timedelta(days=7)
    _schedule(p, monday + timedelta(1), "Tempo")
    with SessionLocal() as db:
        user = db.get(User, uid)
        facts = assessments.weekly_facts(db, user, {"plans", "activities"}, monday)
    wc = facts["workout_compliance"]
    assert wc["missed"] == 1 and wc["workouts"][0]["name"] == "Tempo"
    assert "workout_compliance" in assessments.WEEKLY_PROMPT
    # The helper also works without any workouts.
    with SessionLocal() as db:
        empty = compliance.week(db, db.get(User, uid), {"plans"}, monday - timedelta(days=7))
    assert empty["scheduled"] == 0 and empty["compliance_pct"] is None
