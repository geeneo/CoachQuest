"""Target time on a race: the formula estimate, and the AI coach's target CTL suggestion."""

import json
from datetime import date, timedelta

import pytest

from app.db import Activity, Race, SessionLocal, User
from app.race_estimate import estimate, format_time, parse_time


def test_parse_and_format_time():
    assert parse_time("4:30") == 16200 and parse_time("3:29:30") == 12570 and parse_time("45") == 2700
    assert parse_time("") is None and parse_time(None) is None
    assert format_time(16200) == "4:30" and format_time(12570) == "3:29:30" and format_time(None) is None
    for bad in ("4:75", "abc", "4h30"):
        with pytest.raises(ValueError):
            parse_time(bad)


def test_estimate_ride_and_run():
    rider = User(weight_kg=80, ftp_watts=250)
    road = Race(distance_km=109, elevation_m=1258, discipline="Road", target_seconds=16200)
    e = estimate(road, rider)
    assert e["kind"] == "ride" and e["avg_speed_kmh"] == 24.2
    assert 150 <= e["avg_power_w"] <= 170 and e["w_per_kg"] == round(e["avg_power_w"] / 80, 2)
    assert 0.6 < e["intensity_factor"] < 0.75 and e["tss"] > 200
    no_ftp = estimate(road, User(weight_kg=None, ftp_watts=None))
    assert "intensity_factor" not in no_ftp and "guess" in no_ftp["assumptions"][0]
    run = estimate(Race(distance_km=42.2, elevation_m=300, discipline="Run", target_seconds=12600), rider)
    assert run["kind"] == "run" and run["flat_km"] == 45.2 and run["pace_min_km"] == 4.98
    assert estimate(Race(distance_km=100, discipline="Road"), rider) is None  # no target time


@pytest.fixture()
def race(make_user):
    p = make_user("a@example.com", "Ann")
    aid = p.get("/api/auth/me").json()["id"]
    soon = (date.today() + timedelta(days=70)).isoformat()
    body = {"code": "argus", "name": "Cape Town Cycle Tour", "discipline": "Road", "target_date": soon}
    r = p.post("/api/races", json={**body, "distance_km": 109, "elevation_m": 1258})
    return p, aid, r.json()


def test_target_time_saved_with_estimate(race):
    p, _, r = race
    assert p.patch(f"/api/races/{r['id']}", json={"target_time": "4:75"}).status_code == 422
    out = p.patch(f"/api/races/{r['id']}", json={"target_time": "4:30"}).json()
    assert out["target_time"] == "4:30"
    listed = p.get("/api/athletes/me/races").json()[0]
    assert listed["estimate"]["avg_power_w"] > 0
    assert p.patch(f"/api/races/{r['id']}", json={"target_time": ""}).json()["target_time"] is None


def test_ai_suggests_target_ctl(race, monkeypatch):
    p, aid, r = race
    seen = {}

    async def fake_ask(db, viewer, athlete, system, content, output_format=None, kind="plan"):
        seen.update(facts=json.loads(content), kind=kind)
        answer = {"target_ctl": 85, "verdict": "stretch", "realistic_time": None, "why": "4:30 needs 160 W."}
        return json.dumps(answer), "claude-test"

    monkeypatch.setattr("app.race_target.ask_claude", fake_ask)
    url = f"/api/races/{r['id']}/ctl-advice"
    assert p.post(url).status_code == 409  # no target time yet
    p.patch(f"/api/races/{r['id']}", json={"target_time": "4:30"})
    assert p.post(url).status_code == 409  # no synced data yet
    with SessionLocal() as db:
        db.add(Activity(user_id=aid, source="strava", external_id="1", sport="Ride", start_time=date.today()))
        db.commit()
    advice = p.post(url).json()
    assert advice["target_ctl"] == 85 and advice["verdict"] == "stretch" and advice["for_time"] == "4:30"
    f = seen["facts"]
    assert seen["kind"] == "target" and f["race"]["target_time"] == "4:30" and f["estimate"]["kind"] == "ride"
    assert f["weeks_left"] == 10 and f["reachable_ctl"] == round(f["load"]["ctl_fitness"] + 50)
    assert f["longest_efforts_12_months"][0]["sport"] == "Ride"
    listed = p.get("/api/athletes/me/races").json()[0]
    assert listed["ctl_advice"]["target_ctl"] == 85 and listed["target_ctl"] is None  # a suggestion only
    assert p.delete(url).json()["ctl_advice"] is None


def test_only_the_athlete_asks(race, make_user):
    p, aid, r = race
    coach = make_user("c@example.com")
    g = p.post("/api/grants", json={"coach_email": "c@example.com", "scopes": ["plans"]}).json()
    coach.post(f"/api/grants/{g['id']}/accept")
    assert coach.post(f"/api/races/{r['id']}/ctl-advice").status_code == 404
    assert "estimate" not in coach.get(f"/api/athletes/{aid}/races").json()[0]  # uses the athlete's weight
