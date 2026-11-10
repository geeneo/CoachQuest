"""The race pacing plan and its Garmin course files (pacing.py, /api/races/{id}/pacing)."""

import math
from types import SimpleNamespace as N

import pytest
from fit_tool.fit_file import FitFile

from app import geo, pacing
from app.db import Segment, SessionLocal

LINE = [(-33.9 + i * 0.0009, 18.4) for i in range(2001)]  # about 200 km due north


def _hill(points):
    # A 4 km climb at about 6% from km 40.
    n = len(points)
    out, h = [], 100.0
    for i in range(n):
        km = i * 200 / 1000
        if 40 <= km < 44:
            h += 12
        out.append(h)
    return out


def test_plan_spends_more_on_the_climb_and_hits_the_target():
    pts = pacing.route_points(geo.encode(LINE))
    race = N(name="DC", discipline="Road", target_seconds=7 * 3600, start_time="06:00")
    p = pacing.plan(pts, _hill(pts), race, N(weight_kg=74, ftp_watts=213), "team", 20)
    assert abs(p["_times"][-1] - (7 * 3600 - 20 * 60)) < 60  # moving time = target - stops
    assert p["finish"] == "13:00" and p["checkpoints"][-1]["clock"] == "13:00"
    assert [c["km"] for c in p["checkpoints"]][:2] == [25.0, 50.0]
    climb = p["climbs"][0]
    assert 39 <= climb["start_km"] <= 41 and 5 <= climb["grade_pct"] <= 7
    assert climb["power_w"] > p["base_power_w"]
    assert math.isclose(p["intensity_factor"], p["norm_power_w"] / 213, abs_tol=0.01)
    alone = pacing.plan(pts, _hill(pts), race, N(weight_kg=74, ftp_watts=213), "alone", 20)
    assert alone["avg_power_w"] > p["avg_power_w"]  # sharing the work in a team costs less

    fast = N(name="DC", discipline="Road", target_seconds=2 * 3600, start_time="06:00")
    with pytest.raises(pacing.PacingError):
        pacing.plan(pts, _hill(pts), fast, N(weight_kg=74, ftp_watts=213), "team", 0)


def test_course_files():
    pts = pacing.route_points(geo.encode(LINE))
    race = N(name="DC", discipline="Road", target_seconds=7 * 3600, start_time="06:00")
    p = pacing.plan(pts, _hill(pts), race, N(weight_kg=74, ftp_watts=None), "team", 0)
    fit = FitFile.from_bytes(pacing.course_fit(pts, p, "DC"))
    records = [r.message for r in fit.records if type(r.message).__name__ == "RecordMessage"]
    assert len(records) == len(pts)
    span = (records[-1].timestamp - records[0].timestamp) / 1000
    assert abs(span - 7 * 3600) < 60  # the Virtual Partner rides the plan
    gpx = pacing.course_gpx(pts, p, "DC")
    assert gpx.count("<trkpt") == len(pts) and "<wpt" in gpx and "<ele>" in gpx


def test_pacing_endpoints(make_user, monkeypatch):
    async def fake_heights(points):
        return _hill(points)

    monkeypatch.setattr(pacing, "elevations", fake_heights)
    p = make_user("a@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    race = p.post("/api/races", json={"code": "dc", "name": "Double Century", "start_time": "06:00"}).json()
    url = f"/api/races/{race['id']}/pacing"
    assert "target time" in p.get(url).json()["detail"]
    p.patch(f"/api/races/{race['id']}", json={"target_time": "7:00"})
    assert "route" in p.get(url).json()["detail"]
    with SessionLocal() as db:
        seg = Segment(athlete_id=uid, strava_id=9, kind="route", name="DC", polyline=geo.encode(LINE))
        db.add(seg)
        db.commit()
        sid = seg.id
    p.patch(f"/api/races/{race['id']}", json={"segment_id": sid})
    plan = p.get(f"{url}?group=team&stops=20").json()
    assert plan["target_time"] == "7:00" and plan["finish"] == "13:00" and plan["climbs"]
    assert "_times" not in plan and "point" not in plan["checkpoints"][0]
    fit = p.get(f"{url}.fit")
    assert fit.status_code == 200 and fit.content[8:12] == b".FIT"
    assert 'filename="dc-pacing.fit"' in fit.headers["content-disposition"]
    assert p.get(f"{url}.gpx").text.startswith("<?xml")
    assert p.get(f"{url}.pdf").status_code == 404
    other = make_user("b@example.com")
    assert other.get(url).status_code == 404


def test_riding_setting(make_user, monkeypatch):
    from app import race_estimate

    rider = N(weight_kg=74, ftp_watts=213)
    base = dict(distance_km=202, elevation_m=1100, discipline="Road", target_seconds=7 * 3600)
    solo = race_estimate.estimate(N(**base, riding="solo"), rider)
    team = race_estimate.estimate(N(**base, riding="team"), rider)
    bunch = race_estimate.estimate(N(**base, riding="bunch"), rider)
    assert solo["avg_power_w"] > team["avg_power_w"] > bunch["avg_power_w"]
    assert (
        "team" in team["assumptions"][1] and "set Riding" in race_estimate.estimate(N(**base), rider)["assumptions"][1]
    )
    assert pacing.group_of(N(riding="solo")) == "alone" and pacing.group_of(N(riding=None)) == "team"

    async def fake_heights(points):
        return _hill(points)

    monkeypatch.setattr(pacing, "elevations", fake_heights)
    p = make_user("a@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    with SessionLocal() as db:
        seg = Segment(athlete_id=uid, strava_id=9, kind="route", name="DC", polyline=geo.encode(LINE))
        db.add(seg)
        db.commit()
        sid = seg.id
    race = p.post(
        "/api/races",
        json={"code": "dc", "name": "DC", "target_time": "7:00", "segment_id": sid, "riding": "solo"},
    ).json()
    assert race["riding"] == "solo"
    assert p.get(f"/api/races/{race['id']}/pacing").json()["group"] == "alone"  # the race's own setting
    assert p.get(f"/api/races/{race['id']}/pacing?group=bunch").json()["group"] == "bunch"  # the page's choice
    assert p.patch(f"/api/races/{race['id']}", json={"riding": "peloton"}).status_code == 422
