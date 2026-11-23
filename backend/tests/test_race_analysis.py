"""The plan against the race, and what the wind did (race_analysis.py)."""

from types import SimpleNamespace

from app import race_analysis as ra
from app.db import Activity, Race, SessionLocal
from app.providers import strava
from tests.test_race_review import RACE_DAY, _admin_on, _ride, racer  # noqa: F401 (the fixture)


def _streams(km=20, kmh=30.0, stop_at_km=10, stop_s=300, watts=200):
    """A ride at a steady speed, one sample a second, with a stop (not moving) part way."""
    t, d, moving, w, hr = [], [], [], [], []
    v = kmh / 3.6
    secs, dist, stopped = 0, 0.0, False
    while dist < km * 1000:
        t.append(secs)
        d.append(dist)
        if not stopped and dist >= stop_at_km * 1000:
            for _ in range(stop_s):  # standing still
                secs += 1
                t.append(secs)
                d.append(dist)
                moving.append(False)
                w.append(0)
                hr.append(120)
            stopped = True
        moving.append(True)
        w.append(watts if dist < km * 500 else watts + 40)  # harder in the second half
        hr.append(150)
        secs += 1
        dist += v
    return {
        k: {"data": x} for k, x in {"time": t, "distance": d, "moving": moving, "watts": w, "heartrate": hr}.items()
    }


def test_track_times_power_and_stops():
    track = ra.compact_track(_streams())
    assert track[0] == [0.0, 0, 0, None, None]
    end = track[-1]
    assert 19.9 < end[0] <= 20.1
    assert abs(end[1] - (2400 + 300)) <= 3 and abs(end[2] - 2400) <= 3  # elapsed has the stop, moving doesn't
    first, second = ra.between(track, 1, 4), ra.between(track, 15, 19)
    assert first["watts"] == 200 and second["watts"] == 240 and first["hr"] == 150
    assert abs(first["elapsed_s"] - 360) <= 2  # 3 km at 30 km/h
    assert ra.at_km(track, 25) is None  # past the end


def test_plan_against_the_race():
    track = ra.compact_track(_streams())
    plan = {
        "target_time": "0:40",
        "checkpoints": [{"km": 10.0, "elapsed": "0:20", "climbed_m": 50}, {"km": 20.0, "elapsed": "0:40"}],
        "climbs": [{"start_km": 12.0, "length_km": 3.0, "grade_pct": 4.0, "power_w": 260, "time": "0:06"}],
    }
    out = ra.plan_vs_race(plan, track)  # by the ride's clock
    first, last = out["checkpoints"]
    assert abs(first["gap_s"]) <= 3  # on plan at km 10 (the stop starts there)
    assert abs(last["gap_s"] - 300) <= 5  # 5 minutes behind at the end: the stop
    assert out["final_gap_s"] == last["gap_s"] and out["behind_from_km"] == 20.0
    moving = ra.plan_vs_race(plan, track, "moving")
    assert abs(moving["final_gap_s"]) <= 3 and moving["behind_from_km"] is None  # the stop doesn't count
    climb = out["climbs"][0]
    assert climb["target_w"] == 260 and climb["actual_w"] == 240 and abs(climb["gap_s"]) <= 2


def test_wind_costs_time_into_it_and_gives_less_back():
    race = SimpleNamespace(discipline="Road", riding="solo")
    me = SimpleNamespace(weight_kg=75)
    calm = ra.wind_effect(100_000, 3 * 3600, [0.0] * 40, race, me)
    assert calm["wind_s"] == 0
    out_back = ra.wind_effect(100_000, 3 * 3600, [25.0] * 20 + [-25.0] * 20, race, me)
    assert out_back["wind_s"] > 60  # out and back in a wind is slower than calm
    behind = ra.wind_effect(100_000, 3 * 3600, [-20.0] * 40, race, me)
    assert behind["wind_s"] < -300  # a tailwind all the way gave time
    bunch = ra.wind_effect(
        100_000, 3 * 3600, [25.0] * 20 + [-25.0] * 20, SimpleNamespace(discipline="Road", riding="bunch"), me
    )
    assert 0 < bunch["wind_s"] < out_back["wind_s"]  # sitting in costs less
    assert ra.wind_effect(10_000, 3600, [10.0], SimpleNamespace(discipline="Run", riding=None), me) is None


def test_pacing_endpoint(racer, monkeypatch):  # noqa: F811
    from app.db import Connection
    from app.routers import races as races_router

    p, uid, rid = racer
    with SessionLocal() as db:
        db.add(_ride(uid, "me", RACE_DAY, km=20, moving=2400, elapsed=2700))
        db.add(Connection(user_id=uid, provider="strava", token_enc="x", status="active"))
        race = db.get(Race, rid)
        race.target_seconds, race.segment_id = 2400, 1
        db.commit()

    async def fake_get(db, conn, path, params=None):
        assert path.endswith("/streams")
        return _streams()

    stops_asked = []

    async def fake_pacing(db, race, user, group, stops):
        stops_asked.append(stops)
        return [], {
            "target_time": "0:40",
            "checkpoints": [{"km": 20.0, "elapsed": "0:40"}],
            "climbs": [],
            "stops_min": stops,
        }

    monkeypatch.setattr(strava, "_get", fake_get)
    monkeypatch.setattr(races_router, "_pacing", fake_pacing)
    r = p.get(f"/api/athletes/me/races/{rid}/review/pacing").json()
    # No official time: by moving time (no stops in the plan), so the 5-minute stop doesn't count.
    assert r["available"] is True and r["basis"] == "moving" and stops_asked == [0]
    assert abs(r["checkpoints"][0]["gap_s"]) <= 5
    r = p.get(f"/api/athletes/me/races/{rid}/review/pacing?basis=elapsed").json()
    assert stops_asked[-1] == 5 and abs(r["checkpoints"][0]["gap_s"] - 300) <= 5  # the ride's clock
    with SessionLocal() as db:
        a = db.query(Activity).filter_by(external_id="me").one()
        assert a.detail["track"][-1][0] > 19.9  # kept: a second look doesn't ask Strava again

    async def no_more(*a, **k):
        raise AssertionError("fetched twice")

    monkeypatch.setattr(strava, "_get", no_more)
    assert p.get(f"/api/athletes/me/races/{rid}/review/pacing").json()["available"] is True
    # An official time: by the race's clock from the neutral zone's end; the choice and km can be saved.
    p.request("PUT", f"/api/races/{rid}/result", json={"official_time": "0:35:00"})
    r = p.get(f"/api/athletes/me/races/{rid}/review/pacing").json()
    assert r["basis"] == "official" and r["start_found"] is True and 4.9 <= r["start_km"] <= 5.1  # 10 min in
    saved = p.request("PUT", f"/api/races/{rid}/result", json={"pace_basis": "official", "neutral_km": 2.0})
    assert saved.json()["neutral_km"] == 2.0
    r = p.get(f"/api/athletes/me/races/{rid}/review/pacing").json()
    assert r["start_km"] == 2.0 and r["start_found"] is False
    p.request("PUT", f"/api/races/{rid}/result", json={"official_time": "1:30:00", "neutral_km": None})
    r = p.get(f"/api/athletes/me/races/{rid}/review/pacing").json()
    assert r["basis"] == "elapsed" and "longer than your ride" in r["notes"][0]
    # Without a target time there's nothing to compare.
    with SessionLocal() as db:
        db.get(Race, rid).target_seconds = None
        db.commit()
    r = p.get(f"/api/athletes/me/races/{rid}/review/pacing").json()
    assert r["available"] is False and "target time" in r["why"]


def test_debrief_facts_saved_and_for_the_coach(racer, make_user, monkeypatch):  # noqa: F811
    """The debrief gets the review's numbers (other riders without names), is kept with the race, and its
    key points reach the AI coach with the race's results."""
    import json
    from datetime import date

    from app import race_debrief, race_review
    from app.db import Grant

    p, uid, rid = racer
    friend = make_user("friend@example.com", "Thandi")
    fid = friend.get("/api/auth/me").json()["id"]
    with SessionLocal() as db:
        db.add(_ride(uid, "me", RACE_DAY))
        db.add(_ride(fid, "f1", RACE_DAY, elapsed=7500))
        db.add(Grant(athlete_id=fid, coach_id=uid, scopes=["activities"], role="friend", status="active"))
        db.commit()
    p.request("PUT", f"/api/races/{rid}/result", json={"official_time": "2:10", "nutrition": "Two gels only"})
    seen = {}

    async def fake_claude(db, viewer, athlete, system, content, output_format=None, kind="plan"):
        seen["facts"], seen["kind"] = json.loads(content), kind
        return json.dumps({"debrief_md": "**Solid ride.** Eat more.", "key_points": ["Eat every 30 min"]}), "m"

    async def no_weather(db, a, today):
        return None

    monkeypatch.setattr(race_debrief, "ask_claude", fake_claude)
    monkeypatch.setattr(race_debrief, "require_data", lambda db, a: None)
    monkeypatch.setattr(race_review, "weather_for", no_weather)
    r = p.request("POST", f"/api/races/{rid}/debrief")
    assert r.status_code == 200, r.text
    assert r.json()["key_points"] == ["Eat every 30 min"] and seen["kind"] == "debrief"
    f = seen["facts"]
    assert f["race_ride"]["elapsed_s"] == 7800 and f["post_race_update"]["nutrition"] == "Two gels only"
    assert "Thandi" not in json.dumps(f) and {s["who"] for s in f["standings"]} == {"the athlete", "another rider"}
    review = p.get(f"/api/athletes/me/races/{rid}/review").json()
    assert review["result"]["debrief"]["md"].startswith("**Solid")
    with SessionLocal() as db:
        out = race_review.recent_results(db, uid, date(2026, 11, 23))
    assert out[0]["debrief_points"] == ["Eat every 30 min"]
    # Someone else's race: not found.
    assert friend.request("POST", f"/api/races/{rid}/debrief").status_code == 404


def test_stage_race_day_by_day(racer, monkeypatch):  # noqa: F811
    """Each day of a stage race is reviewed on its own: its ride, earlier years and standings; a rest day
    isn't a stage; picking a stage's ride leaves the event's update alone; a stage's debrief is its own."""
    import json
    from datetime import date, timedelta

    from app import race_debrief, race_review

    p, uid, rid = racer
    with SessionLocal() as db:
        race = db.get(Race, rid)
        race.stages = [
            {"day": 1, "kind": "stage", "name": "Prologue", "distance_km": 60.0},
            {"day": 2, "kind": "rest"},
            {"day": 3, "kind": "stage", "name": "Queen stage", "distance_km": 60.0},
        ]
        race.days = 3
        db.add(_ride(uid, "d1", RACE_DAY))
        db.add(_ride(uid, "d1b", RACE_DAY, km=58, hour=11))
        db.add(_ride(uid, "d3", RACE_DAY + timedelta(days=2), elapsed=8100))
        db.add(_ride(uid, "d3-2025", date(2025, 10, 5), elapsed=8000))
        db.commit()
    p.request("PUT", f"/api/races/{rid}/result", json={"official_time": "8:00:00"})
    one = p.get(f"/api/athletes/me/races/{rid}/review?stage=1").json()
    three = p.get(f"/api/athletes/me/races/{rid}/review?stage=3").json()
    assert [s["day"] for s in one["stages"]] == [1, 3]  # the rest day isn't one
    assert one["ride"]["external_id"] == "d1" and one["stage"]["name"] == "Prologue"
    assert three["ride"]["external_id"] == "d3" and [e["year"] for e in three["earlier"]] == [2025]
    assert three["standings"][0]["time_s"] == 8100  # the day's elapsed time, not the event's official time
    assert p.get(f"/api/athletes/me/races/{rid}/review?stage=2").status_code == 404
    # Pick the other ride for day 1: the event's update stays.
    with SessionLocal() as db:
        other = db.query(Activity).filter_by(external_id="d1b").one().id
    r = p.request("PUT", f"/api/races/{rid}/result?stage=1", json={"activity_id": other})
    assert r.status_code == 200 and r.json()["official_time"] == "8:00"
    assert p.get(f"/api/athletes/me/races/{rid}/review?stage=1").json()["ride"]["external_id"] == "d1b"
    assert p.request("PUT", f"/api/races/{rid}/result?stage=1", json={"position": 3}).status_code == 422
    assert p.get(f"/api/athletes/me/races/{rid}/review/pacing?stage=3").json()["available"] is False

    async def fake_claude(db, viewer, athlete, system, content, output_format=None, kind="plan"):
        assert json.loads(content)["race_ride"]["elapsed_s"] == 8100
        return json.dumps({"debrief_md": "Day 3 went well.", "key_points": ["Recover between days"]}), "m"

    async def no_weather(db, a, today):
        return None

    monkeypatch.setattr(race_debrief, "ask_claude", fake_claude)
    monkeypatch.setattr(race_debrief, "require_data", lambda db, a: None)
    monkeypatch.setattr(race_review, "weather_for", no_weather)
    assert p.request("POST", f"/api/races/{rid}/debrief?stage=3").status_code == 200
    res = p.get(f"/api/athletes/me/races/{rid}/review?stage=3").json()["result"]
    assert res["stage_debriefs"]["3"]["md"] == "Day 3 went well." and "debrief" not in res


def test_official_clock_starts_after_the_neutral_zone():
    """The official time is shorter than the ride: timing started where the ride's clock read its finish
    minus the official time. Checkpoints before that are left out, and the plan from there is scaled to the
    target time."""
    track = ra.compact_track(_streams(stop_s=0))  # 20 km at 30 km/h: 40 minutes
    plan = {
        "checkpoints": [
            {"km": 5.0, "elapsed": "0:10"},
            {"km": 10.0, "elapsed": "0:20"},
            {"km": 20.0, "elapsed": "0:40"},
        ],
        "climbs": [{"start_km": 2.0, "length_km": 1.0, "grade_pct": 4.0, "power_w": 250, "time": "0:02"}],
    }
    start_km = ra.km_at_elapsed(track, 2400 - 1800)  # official 30:00: timing from 10 minutes in
    assert 4.9 <= start_km <= 5.1
    at = ra.at_km(track, start_km)
    out = ra.plan_vs_race(plan, track, "official", {"km": start_km, "elapsed": at[1], "moving": at[2]}, 1800)
    assert [c["km"] for c in out["checkpoints"]] == [10.0, 20.0] and out["start_km"] == start_km
    last = out["checkpoints"][-1]
    assert last["planned_s"] == 1800 and abs(last["gap_s"]) <= 5  # the target time, met
    assert out["climbs"][0]["neutral"] is True
