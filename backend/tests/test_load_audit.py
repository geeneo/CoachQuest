"""Training load: the PMC's conventions, and the audit (load_audit.py) against another platform."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.db import Activity, SessionLocal, User
from app.fitness import daily_tss, pmc
from app.queries import load_curve

SA = ZoneInfo("Africa/Johannesburg")


def test_pmc_reference_formulas_and_previous_day_tsb():
    """The audit's reference: TSB from the previous day's CTL and ATL; rest days are zero-TSS days."""
    start = date(2026, 1, 1)
    days = {start: 100.0, start + timedelta(days=2): 50.0}  # day 2 is a rest day
    out = pmc(days, start, start + timedelta(days=3))
    ctl = atl = 0.0
    for p, tss in zip(out, [100.0, 0.0, 50.0, 0.0], strict=True):
        tsb = ctl - atl
        ctl += (tss - ctl) / 42
        atl += (tss - atl) / 7
        assert (p.tss, p.ctl, p.atl, p.tsb) == (tss, round(ctl, 1), round(atl, 1), round(tsb, 1))
    assert out[0].tsb == 0  # starts from 0, the day's own TSS isn't in its TSB
    assert len(out) == 4  # every day, rest days included


def test_local_dates_near_midnight():
    """A ride at 00:30 in South Africa is 22:30 UTC the day before: it counts on its local date."""
    late = datetime(2026, 11, 3, 22, 30)  # UTC
    assert daily_tss([(late, 80.0)], SA) == {date(2026, 11, 4): 80.0}
    assert daily_tss([(late, 80.0)]) == {date(2026, 11, 3): 80.0}  # without a time zone: the UTC date


def _act(uid, source, ext, start, minutes, tss, sport="Ride", **kw):
    return Activity(
        user_id=uid,
        source=source,
        external_id=ext,
        name=f"{source} {ext}",
        sport=sport,
        start_time=start,
        duration_s=minutes * 60,
        distance_m=minutes * 500,
        tss=tss,
        tss_method=kw.pop("tss_method", "power"),
        **kw,
    )


@pytest.fixture()
def athlete(make_user):
    p = make_user("natalie@example.com", "Natalie")
    uid = p.get("/api/auth/me").json()["id"]
    with SessionLocal() as db:
        u = db.get(User, uid)
        u.timezone, u.ftp_watts, u.lthr_bpm = "Africa/Johannesburg", 200, None
        db.commit()
    return p, uid


def test_duplicates_once_distinct_sessions_both(athlete):
    p, uid = athlete
    today = date.today()
    morning = datetime.combine(today - timedelta(days=2), datetime.min.time()) + timedelta(hours=5)
    with SessionLocal() as db:
        # One ride from Strava and Garmin (2 min apart): counted once.
        db.add(_act(uid, "strava", "s1", morning, 60, 70))
        db.add(_act(uid, "garmin", "g1", morning + timedelta(minutes=2), 60, 72, sport="road_biking"))
        # A second, different session the same day (afternoon run): counted too.
        db.add(_act(uid, "strava", "s2", morning + timedelta(hours=8), 40, 40, sport="Run", tss_method="duration"))
        db.commit()
    a = p.get("/api/athletes/me/load-audit?days=7").json()
    rows = {x["external_id"]: x for x in a["activities"]}
    assert rows["s1"]["status"] == "counted" and rows["g1"]["status"] == "duplicate"
    assert rows["g1"]["canonical_id"] == rows["s1"]["id"] and rows["s2"]["status"] == "counted"
    day = next(d for d in a["days"] if d["date"] == (today - timedelta(days=2)).isoformat())
    assert day["tss"] == 110 and day["activities"] == 2
    assert a["summary"]["duplicates"] == 1 and len(a["days"]) == 7  # every day, rest days too
    assert any(d["rest"] for d in a["days"])
    assert rows["s1"]["intensity"] is None  # no power on the test ride
    # The audit's CTL is the Fitness chart's.
    with SessionLocal() as db:
        curve, _ = load_curve(db, uid, 7, date.today())
    assert [(d.ctl, d.atl, d.tsb) for d in curve] == [(d["ctl"], d["atl"], d["tsb"]) for d in a["days"]]
    assert any("No LTHR" in w for w in a["warnings"])


def test_deleted_activities_and_estimates(athlete):
    p, uid = athlete
    start = datetime.combine(date.today() - timedelta(days=1), datetime.min.time()) + timedelta(hours=6)
    with SessionLocal() as db:
        db.add(_act(uid, "strava", "walk", start, 120, 100, sport="Walk", tss_method="duration"))
        db.commit()
    a = p.get("/api/athletes/me/load-audit?days=7").json()
    assert a["summary"]["by_method"][0]["method"] == "duration" and any("estimated" in w for w in a["warnings"])
    with SessionLocal() as db:
        db.query(Activity).filter_by(user_id=uid).delete()
        db.commit()
    assert p.get("/api/athletes/me/load-audit?days=7").json()["summary"]["tss"] == 0


def test_csv_and_compare_with_trainingpeaks(athlete):
    p, uid = athlete
    d1 = date.today() - timedelta(days=3)
    with SessionLocal() as db:
        db.add(_act(uid, "strava", "a", datetime.combine(d1, datetime.min.time()) + timedelta(hours=6), 60, 90))
        db.commit()
    r = p.get("/api/athletes/me/load-audit/days.csv?days=7")
    assert r.status_code == 200 and r.text.startswith("date,activities,tss,ctl,atl,tsb,rest")
    assert "external_id" in p.get("/api/athletes/me/load-audit/activities.csv?days=7").text
    # A TrainingPeaks workouts export: two workouts that day (60 TSS in all), with a byte order mark.
    tp = "﻿Title,WorkoutDay,TSS\nRide,{d},40\nCore,{d},20\n".format(d=d1.isoformat())
    c = p.post("/api/athletes/me/load-audit/compare", json={"csv": tp, "days": 7}).json()
    row = next(x for x in c["days"] if x["date"] == d1.isoformat())
    assert row == {"date": d1.isoformat(), "cq_tss": 90.0, "other_tss": 60.0, "tss_diff": 30.0}
    assert c["first_difference"] == d1.isoformat() and c["ratio"] == 1.5
    # Days in the export's range without a workout there are zeros, not skipped.
    with SessionLocal() as db:
        db.add(
            _act(
                uid,
                "strava",
                "walk",
                datetime.combine(d1 + timedelta(days=1), datetime.min.time()) + timedelta(hours=8),
                60,
                25,
                sport="Walk",
            )
        )
        db.commit()
    tp2 = tp + f"Ride,{(d1 + timedelta(days=2)).isoformat()},50\n"
    c = p.post("/api/athletes/me/load-audit/compare", json={"csv": tp2, "days": 7}).json()
    walk_day = next(x for x in c["days"] if x["date"] == (d1 + timedelta(days=1)).isoformat())
    assert walk_day == {"date": walk_day["date"], "cq_tss": 25.0, "other_tss": 0.0, "tss_diff": 25.0}
    assert c["days_compared"] == 3
    bad = p.post("/api/athletes/me/load-audit/compare", json={"csv": "a,b\n1,2\n", "days": 7})
    assert bad.status_code == 422


def test_others_need_fitness_and_activities(athlete, make_user):
    _, uid = athlete
    stranger = make_user("x@example.com")
    assert stranger.get(f"/api/athletes/{uid}/load-audit").status_code in (403, 404)


def test_compare_takes_the_trainingpeaks_zip(athlete):
    import base64
    import io
    import zipfile

    p, uid = athlete
    d1 = date.today() - timedelta(days=2)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("workouts.csv", f"Title,WorkoutDay,TSS\nRide,{d1.isoformat()},55\n")
    b64 = base64.b64encode(buf.getvalue()).decode()
    c = p.post("/api/athletes/me/load-audit/compare", json={"zip_b64": b64, "days": 7}).json()
    assert c["other_tss"] == 55 and c["days_compared"] == 1
    bad = p.post("/api/athletes/me/load-audit/compare", json={"zip_b64": "bm90IGEgemlw", "days": 7})
    assert bad.status_code == 422 and "ZIP" in bad.json()["detail"]
