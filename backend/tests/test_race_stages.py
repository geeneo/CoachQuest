"""Multi-day events: stages under a race, their totals, and what the AI coach gets."""

from datetime import date, datetime, timedelta

from app import race_stages
from app.db import Activity, SessionLocal

STAGES = [
    {"day": 1, "kind": "prologue", "name": "Prologue", "distance_km": 21, "elevation_m": 650, "terrain": "mtb"},
    {"day": 2, "kind": "stage", "name": "Queen stage", "distance_km": 95, "elevation_m": 2600, "terrain": "mtb"},
    {"day": 3, "kind": "stage", "distance_km": 110, "elevation_m": 1500, "terrain": "mixed", "start_time": "07:00"},
    {"day": 4, "kind": "rest"},
    {"day": 5, "kind": "stage", "distance_km": 70, "elevation_m": 1200, "terrain": "mtb"},
]


def _race(p, **kw):
    body = {"code": "epic", "name": "Cape Epic", "discipline": "Mountain bike", **kw}
    return p.post("/api/races", json=body).json()


def test_stages_set_the_race_totals(make_user):
    p = make_user("a@example.com")
    start = date.today() + timedelta(days=60)
    race = _race(p, target_date=start.isoformat())
    r = p.request("PUT", f"/api/races/{race['id']}/stages", json={"stages": list(reversed(STAGES))})
    assert r.status_code == 200, r.text
    out = r.json()
    assert [s["day"] for s in out["stages"]] == [1, 2, 3, 4, 5]
    assert out["stages"][1]["date"] == (start + timedelta(days=1)).isoformat()
    assert out["days"] == 5 and out["distance_km"] == 296 and out["elevation_m"] == 5950
    t = out["stage_totals"]
    assert t == {
        "days": 5,
        "race_days": 4,
        "rest_days": 1,
        "distance_km": 296,
        "elevation_m": 5950,
        "longest_day": 3,
        "hardest_day": 3,  # 110 km + 1500 m = 125 "km"; day 2: 95 + 26 = 121
    }
    # Back to a one-day race.
    out = p.request("PUT", f"/api/races/{race['id']}/stages", json={"stages": []}).json()
    assert out["stages"] == [] and out["stage_totals"] is None and out["days"] == 1


def test_stage_validation(make_user):
    p = make_user("a@example.com")
    race = _race(p)
    url = f"/api/races/{race['id']}/stages"
    for bad in (
        [{"day": 1}, {"day": 1}],
        [{"day": 0}],
        [{"day": 1, "kind": "picnic"}],
        [{"day": 1, "terrain": "sand"}],
        [{"day": 1, "start_time": "7am"}],
        [{"day": 1, "distance_km": -5}],
    ):
        assert p.request("PUT", url, json={"stages": bad}).status_code == 422, bad
    other = make_user("b@example.com")
    assert other.request("PUT", url, json={"stages": STAGES}).status_code == 404


def test_logged_rides_per_stage_and_under_way_still_upcoming(make_user, monkeypatch):
    p = make_user("a@example.com")
    aid = p.get("/api/auth/me").json()["id"]
    start = date.today() - timedelta(days=1)  # the event started yesterday
    race = _race(p, target_date=start.isoformat())
    p.request("PUT", f"/api/races/{race['id']}/stages", json={"stages": STAGES})
    with SessionLocal() as db:
        db.add(
            Activity(
                user_id=aid,
                source="strava",
                external_id="1",
                name="Prologue",
                sport="MountainBikeRide",
                start_time=datetime.combine(start, datetime.min.time()) + timedelta(hours=9),
                duration_s=5400,
                distance_m=21300,
                elevation_m=640,
            )
        )
        db.commit()
    out = p.get("/api/athletes/me/races").json()[0]
    assert out["stages"][0]["logged"] == {"km": 21.3, "elevation_m": 640, "minutes": 90, "types": ["MTB"]}
    assert "logged" not in out["stages"][1]

    seen = {}

    async def fake_generate(db, viewer, athlete, facts):
        seen.update(facts)
        return {"summary_md": "# Plan", "weeks": []}, "claude-test"

    monkeypatch.setattr("app.routers.plans.generate_plan", fake_generate)
    p.post("/api/athletes/me/plans", json={"without_data": True, "title": "t", "goal": "g"})
    epic = seen["upcoming_races"][0]
    assert epic["code"] == "epic" and len(epic["stages"]) == 5 and epic["stage_totals"]["hardest_day"] == 3
    from app.coach import SYSTEM_PROMPT

    assert "multi-day event" in SYSTEM_PROMPT and race_stages.PROMPT_RULE in SYSTEM_PROMPT
