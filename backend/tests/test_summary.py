from datetime import date, datetime, timedelta
from types import SimpleNamespace

from app.activity_types import category
from app.db import Activity, SessionLocal
from app.queries import volume_summary

TODAY = date(2026, 10, 25)  # a Sunday


def _a(days_ago, sport="Ride", km=50, elev=500, hours=2, re=None, kj=None, cal=None, indoor=False, override=None):
    return SimpleNamespace(
        start_time=datetime.combine(TODAY - timedelta(days=days_ago), datetime.min.time()) + timedelta(hours=7),
        sport=sport,
        distance_m=km * 1000,
        elevation_m=elev,
        duration_s=int(hours * 3600),
        relative_effort=re,
        kilojoules=kj,
        calories=cal,
        indoor=indoor,
        type_override=override,
    )


def test_categories():
    assert category(_a(0, "VirtualRide")) == "Virtual"
    assert category(_a(0, "Ride", indoor=True)) == "Virtual"
    assert category(_a(0, "EMountainBikeRide")) == "E-MTB"
    assert category(_a(0, "mountain_biking")) == "MTB"
    assert category(_a(0, "Ride", override="E-MTB")) == "E-MTB"
    assert category(_a(0, "Kitesurf")) == "Other"


def test_volume_summary_totals_and_mix():
    acts = [
        _a(1, "Ride", km=100, elev=1000, hours=4, re=150, kj=2000),
        _a(3, "VirtualRide", km=30, elev=300, hours=1, re=60, kj=600, indoor=True),
        _a(5, "Run", km=10, elev=100, hours=1, cal=700),
        _a(40, "Ride", km=80, elev=800, hours=3),  # outside 30 days
    ]
    s = volume_summary(acts, 30, TODAY)
    assert s["count"] == 3 and s["distance_km"] == 140 and s["elevation_m"] == 1400
    assert s["outdoor_elevation_m"] == 1100  # virtual ride excluded
    assert s["moving_hours"] == 6 and s["calories"] == 3300 and s["avg_relative_effort"] == 105
    assert [m["category"] for m in s["mix"]] == ["Road", "Virtual", "Run"]
    weeks = s["weekly_elevation"]
    assert len(weeks) == 12 and weeks[-1] == {"week_start": "2026-10-19", "elevation_m": 1400}
    assert weeks[-6] == {"week_start": "2026-09-14", "elevation_m": 800}  # the ride 40 days ago


def test_summary_endpoint_needs_activities_scope(make_user):
    athlete = make_user("a@example.com")
    coach = make_user("c@example.com")
    aid = athlete.get("/api/auth/me").json()["id"]
    with SessionLocal() as db:
        db.add(
            Activity(
                user_id=aid,
                source="strava",
                external_id="1",
                sport="Ride",
                start_time=datetime.now() - timedelta(days=1),
                distance_m=42000,
                elevation_m=420,
            )
        )
        db.commit()
    assert athlete.get("/api/athletes/me/summary?days=7").json()["distance_km"] == 42
    assert coach.get(f"/api/athletes/{aid}/summary").status_code == 404


def test_weekly_elevation_with_sunday_weeks():
    acts = [_a(0, elev=300), _a(1, elev=200)]  # Sunday 25 Oct and Saturday 24 Oct
    monday_weeks = volume_summary(acts, 7, TODAY)["weekly_elevation"]
    sunday_weeks = volume_summary(acts, 7, TODAY, week_start=6)["weekly_elevation"]
    assert monday_weeks[-1] == {"week_start": "2026-10-19", "elevation_m": 500}
    assert sunday_weeks[-1] == {"week_start": "2026-10-25", "elevation_m": 300}
    assert sunday_weeks[-2] == {"week_start": "2026-10-18", "elevation_m": 200}
