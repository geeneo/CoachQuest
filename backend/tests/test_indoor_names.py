"""Indoor sessions don't name outdoor favourites (indoor_names.py)."""

from datetime import date, timedelta

from app import indoor_names
from app.db import Plan, ScheduledWorkout, Segment, SessionLocal

STEPS = [
    {"kind": "warmup", "duration_s": 600, "power_start": 0.5, "power_end": 0.7},
    {"kind": "intervals", "repeat": 5, "on_s": 120, "off_s": 180, "on_power": 1.1, "off_power": 0.5},
    {"kind": "cooldown", "duration_s": 300, "power_start": 0.6, "power_end": 0.4},
]
NAMES = ["Kendal climb A", "Easy coffee spin", "Helshoogte", "Stellenbosch 129km Loop"]


def _indoor(name="Kendal A 5x2", description="5 x 2 min at 110% FTP as on Kendal climb A. Easy spin between."):
    return {"type": "Zwift / indoor", "description": description, "workout": {"name": name, "steps": STEPS}}


def test_names_and_descriptions_lose_the_place():
    pats = indoor_names.patterns(NAMES)
    s = _indoor()
    assert indoor_names.scrub_session(s, pats)
    assert s["workout"]["name"] == "Intervals 5×2 min"
    assert s["description"] == "5 x 2 min at 110% FTP. Easy spin between."
    s = _indoor("Helshoogte simulation", "Kendal A repeats.")
    indoor_names.scrub_session(s, pats)
    assert s["workout"]["name"] == "Intervals 5×2 min" and s["description"] == "Indoor: Intervals 5×2 min."


def test_common_words_and_outdoor_days_stay():
    pats = indoor_names.patterns(NAMES)
    s = _indoor("Easy spin 45", "Easy spin, coffee pace. Keep it in Z2.")
    assert not indoor_names.scrub_session(s, pats)  # "easy", "coffee", "spin" aren't places
    road = {"type": "Road", "description": "6 x Kendal climb A at 95-105% FTP.", "workout": None}
    assert not indoor_names.scrub_session(road, pats)
    steady = [{"kind": "steady", "duration_s": 3600, "power": 0.88}]
    assert indoor_names.plain_name(steady) == "Sweet spot 60 min"


def test_saved_plans_are_fixed_and_the_workout_renamed(make_user):
    p = make_user("a@example.com")
    aid = p.get("/api/auth/me").json()["id"]
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    with SessionLocal() as db:
        db.add(Segment(athlete_id=aid, strava_id=1, kind="segment", name="Kendal climb A"))
        days = []
        for i in range(7):
            d = monday + timedelta(days=i)
            days.append(
                {
                    "date": d.isoformat(),
                    "weekday": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][i],
                    "type": "Rest",
                    "description": "",
                    "duration_min": 0,
                    "intensity": [],
                    "locked": False,
                    "workout": None,
                }
            )
        later = next(x for x in days if x["date"] >= today.isoformat())
        later.update(_indoor(), duration_min=40)
        plan = Plan(
            athlete_id=aid,
            author_id=aid,
            title="P",
            content_md="",
            model="m",
            start_date=monday,
            weeks=[{"start": monday.isoformat(), "phase": "Build", "focus": "", "status": "draft", "days": days}],
        )
        db.add(plan)
        db.commit()
        plan_id = plan.id
        db.add(
            ScheduledWorkout(
                athlete_id=aid,
                day=date.fromisoformat(later["date"]),
                plan_id=plan_id,
                plan_managed=True,
                plan_day=date.fromisoformat(later["date"]),
                name="Kendal A 5x2",
                description=later["description"],
                steps=STEPS,
                instructions="",
            )
        )
        db.commit()
    out = p.get(f"/api/athletes/me/plans/{plan_id}").json()
    day = next(d for w in out["weeks"] for d in w["days"] if d["date"] == later["date"])
    assert day["workout"]["name"] == "Intervals 5×2 min" and "Kendal" not in day["description"]
    with SessionLocal() as db:
        sw = db.query(ScheduledWorkout).filter_by(plan_id=plan_id).one()
        assert sw.name == "Intervals 5×2 min" and "Kendal" not in sw.description


def test_tidy_after_cleaning_and_on_old_plans():
    s = {
        "type": "Zwift / indoor",
        "description": "efforts indoors (0.72 km at 6.2%, 45 m climb, about 2 min each): 5x2 min at 97-102% FTP.",
        "workout": None,
    }
    assert indoor_names.scrub_session(s, [])  # cleaned before tidy() existed: tidied now
    assert s["description"] == "Efforts indoors: 5x2 min at 97-102% FTP."
    assert not indoor_names.scrub_session(s, [])  # and left alone after that
    kept = {"type": "Zwift / indoor", "description": "Sweet spot (88-94% FTP).\n\nCool down easy.", "workout": None}
    assert not indoor_names.scrub_session(kept, [])  # brackets without a climb, and line breaks, stay
