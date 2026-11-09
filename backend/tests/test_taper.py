"""Taper mode for the morning readiness note (taper.py): the last two weeks before a race."""

import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from app import assessments, taper
from app.db import Activity, Plan, Race, SessionLocal, WellnessDay

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _w(days_ago, hrv=56, rhr=56):
    return SimpleNamespace(
        day=date.today() - timedelta(days=days_ago),
        hrv_ms=hrv,
        resting_hr=rhr,
        sleep_s=8 * 3600,
        sleep_score=83,
        body_battery_max=80,
    )


def test_form_counts_sooner_in_a_taper():
    nights = [_w(i, hrv=44) for i in range(30, -1, -1)]
    assert assessments.readiness_verdict(nights, -18.5)[0] == "go"
    verdict, reasons, _ = assessments.readiness_verdict(nights, -18.5, race_in_days=12)
    assert verdict == "easy" and "race 12 days away" in reasons[0]
    assert assessments.readiness_verdict(nights, -10, race_in_days=12)[0] == "go"


def test_projection_sheds_fatigue():
    # 12 rest days from fitness 61 / fatigue 83: fatigue drops much faster than fitness.
    p = taper.project(61, 83, [0] * 12)
    assert p["ctl"] < 61 and p["atl"] < 20 and p["tsb"] > 10
    assert taper.project(50, 50, [50] * 5) == {"ctl": 50.0, "atl": 50.0, "tsb": 0.0}


def _plan(aid, start, sessions):
    """sessions: {day offset: (type, minutes)} over 14 days; the rest are rest days."""
    weeks = []
    for w in range(2):
        days = []
        for i in range(7):
            day = start + timedelta(days=w * 7 + i)
            kind, minutes = sessions.get(w * 7 + i, ("Rest", 0))
            days.append(
                {
                    "date": day.isoformat(),
                    "weekday": WEEKDAYS[day.weekday()],
                    "type": kind,
                    "description": "",
                    "duration_min": minutes,
                    "intensity": ["Z2"] if kind not in ("Rest", "Strength") else [],
                    "locked": False,
                }
            )
        weeks.append(
            {
                "start": (start + timedelta(days=w * 7)).isoformat(),
                "phase": "Taper",
                "focus": "",
                "status": "draft",
                "days": days,
            }
        )
    with SessionLocal() as db:
        db.add(
            Plan(
                athlete_id=aid,
                author_id=aid,
                title="P",
                content_md="",
                model="m",
                start_date=start,
                approval="approved",
                weeks=weeks,
            )
        )
        db.commit()


def test_daily_note_in_a_taper(make_user, monkeypatch):
    p = make_user("a@example.com")
    aid = p.get("/api/auth/me").json()["id"]
    today = date.today()
    with SessionLocal() as db:
        for i in range(1, 60):
            db.add(WellnessDay(user_id=aid, day=today - timedelta(days=i), hrv_ms=44, resting_hr=56))
            db.add(
                Activity(
                    user_id=aid,
                    source="strava",
                    external_id=str(i),
                    name="Ride",
                    sport="Ride",
                    start_time=datetime.combine(today - timedelta(days=i), datetime.min.time()) + timedelta(hours=7),
                    duration_s=5400,
                    distance_m=45000,
                    elevation_m=300,
                    tss=200 if i <= 2 else 60,  # two long rides at the weekend
                )
            )
        db.add(WellnessDay(user_id=aid, day=today, hrv_ms=56, resting_hr=56))
        db.add(Race(user_id=aid, code="dc", name="Double Century", distance_km=205, target_date=today + timedelta(12)))
        db.commit()
    _plan(
        aid,
        today,
        {
            0: ("Strength", 30),
            1: ("Road", 90),
            4: ("Strength", 30),  # 8 days before the race
            5: ("Road", 180),
            6: ("Road", 60),
            9: ("Road", 150),  # 3 days before the race
            11: ("Road", 30),
            12: ("Race", 480),
        },
    )
    seen = {}

    async def fake_ask(db, viewer, ath, system, content, output_format=None, kind=None):
        seen["system"], seen["facts"] = system, json.loads(content)
        return "**Easy today.**", "claude-test"

    monkeypatch.setattr(assessments, "ask_claude", fake_ask)
    r = p.post("/api/athletes/me/coach/assessments", json={"kind": "daily"})
    assert r.status_code == 200, r.text
    assert seen["system"] == assessments.TAPER_PROMPT
    t = seen["facts"]["taper"]
    assert t["race"]["days_to_go"] == 12 and len(t["days"]) == 12 and t["days"][0]["label"] == taper.label(today)
    assert t["days"][0]["planned"] == "Strength" and t["days"][2]["planned"] == "Rest"
    flags = " ".join(t["flags"])
    assert "strength 8 days before the race" in flags
    assert "150 min in race week" in flags and "strength 12 days" not in flags
    assert t["projection"]["race_morning"]["tsb"] > 0
    assert t["go_no_go"]["easy_if_resting_hr_above"] == 60
    # Form under the taper threshold after the weekend makes the day easy, even with good recovery.
    assert r.json()["verdict"] == "easy" and seen["facts"]["load"]["tsb"] < taper.TIRED_TSB


def test_no_taper_far_from_the_race(make_user, monkeypatch):
    p = make_user("a@example.com")
    aid = p.get("/api/auth/me").json()["id"]
    with SessionLocal() as db:
        db.add(Race(user_id=aid, code="dc", name="DC", target_date=date.today() + timedelta(days=30)))
        db.add(
            Activity(
                user_id=aid,
                source="strava",
                external_id="1",
                name="Ride",
                sport="Ride",
                start_time=datetime.now() - timedelta(days=1),
                duration_s=3600,
                distance_m=30000,
                elevation_m=100,
                tss=60,
            )
        )
        db.commit()
    seen = {}

    async def fake_ask(db, viewer, ath, system, content, output_format=None, kind=None):
        seen["system"], seen["facts"] = system, json.loads(content)
        return "**Go.**", "claude-test"

    monkeypatch.setattr(assessments, "ask_claude", fake_ask)
    assert p.post("/api/athletes/me/coach/assessments", json={"kind": "daily"}).status_code == 200
    assert seen["system"] == assessments.READINESS_PROMPT and "taper" not in seen["facts"]
