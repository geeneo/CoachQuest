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


def _setup(make_user, ride_min=90):
    p = make_user("c@example.com")
    aid = p.get("/api/auth/me").json()["id"]
    today = date.today()
    with SessionLocal() as db:
        for i in range(1, 40):
            db.add(
                Activity(
                    user_id=aid,
                    source="strava",
                    external_id=f"r{i}",
                    name="Ride",
                    sport="Ride",
                    start_time=datetime.combine(today - timedelta(days=i), datetime.min.time()) + timedelta(hours=7),
                    duration_s=ride_min * 60,
                    distance_m=30000,
                    elevation_m=300,
                    tss=60,
                )
            )
        db.add(Race(user_id=aid, code="dc", name="Double Century", target_date=today + timedelta(days=12)))
        db.commit()
    return p, aid, today


def test_make_these_changes(make_user):
    p, aid, today = _setup(make_user, ride_min=60)  # a usual week of 420 min
    _plan(
        aid,
        today,
        {
            1: ("Road", 90),
            4: ("Strength", 30),  # 8 days out: dropped
            5: ("Road", 180),  # the week before race week: 300 min against 85% of 420 (357) is fine
            9: ("Road", 150),  # race week: over 90 min
            10: ("Road", 120),  # race week: over 90 min
            11: ("Road", 60),
            12: ("Race", 480),
        },
    )
    with SessionLocal() as db:  # a locked day stays as it is
        plan = db.query(Plan).one()
        weeks = [dict(w, days=[dict(d) for d in w["days"]]) for w in plan.weeks]
        weeks[1]["days"][3]["locked"] = True  # day 10
        plan.weeks = weeks
        db.commit()
    t = p.get("/api/athletes/me/coach/taper").json()
    by_day = {c["date"]: c for c in t["changes"]}
    d = lambda i: (today + timedelta(days=i)).isoformat()  # noqa: E731
    # Race week is 330 min against 60% of 420 (252): after the 90 min cap, day 11 is trimmed too.
    assert set(by_day) == {d(4), d(9), d(11)}
    assert by_day[d(4)]["after"]["planned"] == "Rest" and "no strength 8 days" in by_day[d(4)]["why"]
    assert by_day[d(4)]["before"]["planned"] == "Strength"
    assert by_day[d(9)]["after"]["minutes"] <= 90 and by_day[d(9)]["before"]["minutes"] == 150
    assert t["form_with_changes"] >= t["form_now"]

    assert p.post("/api/athletes/me/coach/taper/apply").json()["changed"] == len(by_day)
    with SessionLocal() as db:
        days = {x["date"]: x for w in db.query(Plan).one().weeks for x in w["days"]}
    assert days[d(4)]["type"] == "Rest" and days[d(9)]["duration_min"] <= 90
    assert "Shortened for the taper" in days[d(9)]["description"]
    assert days[d(10)]["duration_min"] == 120  # locked
    assert days[d(12)]["type"] == "Race" and days[d(1)]["duration_min"] == 90
    # Done: nothing more to change, and race week fits a usual week.
    assert p.get("/api/athletes/me/coach/taper").json()["changes"] == []


def test_week_volume_cut(make_user):
    p, aid, today = _setup(make_user, ride_min=30)  # a usual week of 210 min
    _plan(aid, today, {4: ("Road", 120), 5: ("Road", 120), 1: ("Road", 60)})  # the week before race week
    t = p.get("/api/athletes/me/coach/taper").json()
    # Days -13..-7 from the race (today-1 .. today+5) aren't all ahead, so only race week is judged: nothing.
    assert t["changes"] == []
    p2 = make_user("d@example.com")
    aid2 = p2.get("/api/auth/me").json()["id"]
    with SessionLocal() as db:
        for i in range(1, 30):
            db.add(
                Activity(
                    user_id=aid2,
                    source="strava",
                    external_id=f"s{i}",
                    name="Ride",
                    sport="Ride",
                    start_time=datetime.combine(today - timedelta(days=i), datetime.min.time()) + timedelta(hours=7),
                    duration_s=1800,
                    distance_m=10000,
                    elevation_m=0,
                    tss=30,
                )
            )
        db.add(Race(user_id=aid2, code="dc", name="DC", target_date=today + timedelta(days=7)))
        db.commit()
    # Race week (days 1-6): 160 min against 60% of a usual 210 (126); today is the week before.
    _plan(aid2, today, {0: ("Road", 80), 2: ("Road", 80), 4: ("Road", 80)})
    t = p2.get("/api/athletes/me/coach/taper").json()
    total = sum(c["after"]["minutes"] for c in t["changes"])
    assert len(t["changes"]) == 2 and total <= 130 and all(c["after"]["minutes"] >= 30 for c in t["changes"])
