"""The Overview's 2- and 3-year periods: elevation per month, and the longer periods allowed."""

from datetime import date, datetime
from types import SimpleNamespace

from app.queries import volume_summary


def _act(day, elev):
    return SimpleNamespace(
        start_time=datetime.combine(day, datetime.min.time()),
        elevation_m=elev,
        distance_m=1000,
        duration_s=3600,
        sport="Ride",
        type_override=None,
        indoor=False,
        trainer=False,
        relative_effort=None,
        calories=None,
        kilojoules=None,
        avg_power=None,
        name="",
    )


def test_by_month_beyond_a_year():
    today = date(2026, 11, 4)
    acts = [_act(date(2025, 1, 15), 500), _act(date(2025, 1, 20), 300), _act(date(2026, 11, 1), 100)]
    s = volume_summary(acts, 730, today)
    assert s["elevation"]["by"] == "month"
    points = s["elevation"]["points"]
    assert points[0]["start"] == "2024-11-01" and points[-1]["start"] == "2026-11-01" and len(points) == 25
    assert next(p for p in points if p["start"] == "2025-01-01")["elevation_m"] == 800
    assert volume_summary(acts, 365, today)["elevation"]["by"] == "week"


def test_longer_periods_allowed(make_user):
    p = make_user("a@example.com")
    assert p.get("/api/athletes/me/fitness?days=1825").status_code == 200
    assert p.get("/api/athletes/me/wellness?days=1825").status_code == 200
    assert p.get("/api/athletes/me/summary?days=1825").status_code == 200
