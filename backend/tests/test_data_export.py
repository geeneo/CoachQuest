"""Anonymised data for improving CoachQuest (data_export.py, Admin → Data)."""

import csv
import io
import zipfile
from datetime import date, datetime, timedelta

from app import data_export
from app.db import Activity, Plan, SessionLocal, User, WellnessDay


def _super(make_user):
    p = make_user("boss@example.com", "Boss")
    with SessionLocal() as db:
        u = db.query(User).filter_by(email="boss@example.com").one()
        u.is_admin = u.is_super_admin = True
        db.commit()
    return p


def _setup(make_user):
    a = make_user("natalie@example.com", "Natalie Example")
    aid = a.get("/api/auth/me").json()["id"]
    day = date.today() - timedelta(days=10)
    with SessionLocal() as db:
        u = db.get(User, aid)
        u.ftp_watts, u.weight_kg, u.birth_date, u.goal = 210, 61.4, date(1985, 6, 1), "Win the DC with Pieter"
        for src, ext, tss in (("garmin", "g1", 80), ("strava", "s1", 90), ("strava", "s2", 40)):
            db.add(
                Activity(
                    user_id=aid,
                    source=src,
                    external_id=ext,
                    name="Ride with Pieter to Stellenbosch",
                    sport="Ride" if src == "strava" else "road_biking",
                    start_time=datetime.combine(day, datetime.min.time()) + timedelta(hours=6 if ext != "s2" else 15),
                    duration_s=3600,
                    distance_m=30000,
                    tss=tss,
                    tss_method="power",
                )
            )
        db.add(WellnessDay(user_id=aid, day=day, resting_hr=44, hrv_ms=70.2, sleep_s=7 * 3600, source="garmin"))
        db.add(
            Plan(
                athlete_id=aid,
                author_id=aid,
                title="DC plan for Natalie",
                content_md="",
                model="m",
                start_date=day,
                weeks=[
                    {
                        "start": day.isoformat(),
                        "phase": "Build",
                        "focus": "",
                        "status": "draft",
                        "days": [
                            {
                                "date": (day + timedelta(days=i)).isoformat(),
                                "weekday": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][
                                    (day + timedelta(days=i)).weekday()
                                ],
                                "type": "Road" if i == 0 else "Rest",
                                "description": "Long ride with Pieter",
                                "duration_min": 60 if i == 0 else 0,
                                "intensity": ["Z2"] if i == 0 else [],
                                "locked": False,
                            }
                            for i in range(7)
                        ],
                    }
                ],
            )
        )
        db.commit()
    return a, aid, day


def test_anonymised_and_without_strava(make_user):
    boss = _super(make_user)
    a, aid, day = _setup(make_user)
    d = boss.get("/api/admin/data").json()
    acts = [x for x in d["preview"]["activities"] if x["user"] == data_export.code(aid)]
    assert [x["source"] for x in acts] == ["garmin"]  # Strava's two left out
    assert d["strava_left_out"] == 2
    u = next(x for x in d["preview"]["users"] if x["user"] == data_export.code(aid))
    assert u["weight_kg"] == 60 and u["age_band"].endswith("9") and "goal" not in u
    moved = date.fromisoformat(acts[0]["date"])
    assert (moved - day).days % 7 == 0 and acts[0]["weekday"] == day.strftime("%a")
    plan = next(x for x in d["preview"]["plan_days"] if x["user"] == data_export.code(aid) and x["type"] == "Road")
    assert plan["status"] == "goal_met" and plan["done_tss"] == 80  # from the Garmin ride only
    # Nothing that names anyone anywhere in the download.
    r = boss.get("/api/admin/data/export.zip")
    assert r.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert set(z.namelist()) == {
        "README.txt",
        "users.csv",
        "activities.csv",
        "load.csv",
        "plan_days.csv",
        "wellness.csv",
        "assessments.csv",
    }
    text = " ".join(z.read(n).decode() for n in z.namelist())
    for secret in ("Natalie", "Pieter", "Stellenbosch", "natalie@example.com", "Win the DC"):
        assert secret not in text
    rows = list(csv.DictReader(io.StringIO(z.read("wellness.csv").decode())))
    assert rows[0]["resting_hr"] == "44" and rows[0]["sleep_h"] == "7.0"


def test_opt_out_and_who_may(make_user):
    boss = _super(make_user)
    a, aid, _ = _setup(make_user)
    a.request("PATCH", "/api/me", json={"data_analysis": False})
    d = boss.get("/api/admin/data").json()
    assert data_export.code(aid) not in {x["user"] for x in d["preview"]["users"]} and d["users_opted_out"] == 1
    assert a.get("/api/admin/data").status_code == 403
    assert a.get("/api/admin/data/export.zip").status_code == 403
    assert data_export.code(aid) == data_export.code(aid) != data_export.code(aid + 1)
