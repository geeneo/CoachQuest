"""After a race (race_review.py): the ride, the post-race update, earlier years, segments, weather and other
riders."""

from datetime import date, datetime, timedelta

import pytest

from app import geo, race_review, weather
from app.db import Activity, Grant, Race, SessionLocal, User
from app.providers import strava

RACE_DAY = date(2026, 10, 4)
# A 60 km out-and-back line heading east then back west, about 30 km each way.
OUT = [(-33.9, 18.4 + i * 0.033) for i in range(11)]
LINE = geo.encode(OUT + list(reversed(OUT))[1:])
OTHER_LINE = geo.encode([(-26.1, 28.0 + i * 0.06) for i in range(11)])  # somewhere else entirely


def _ride(uid, ext, day, km=60.0, moving=7200, elapsed=7800, line=LINE, source="strava", hour=5, **kw):
    start = datetime.combine(day, datetime.min.time()) + timedelta(hours=hour)  # 07:00 in South Africa
    return Activity(
        user_id=uid,
        source=source,
        external_id=ext,
        name=f"ride {ext}",
        sport="Ride",
        start_time=start,
        duration_s=moving,
        elapsed_s=elapsed,
        distance_m=km * 1000,
        elevation_m=600,
        tss=150,
        tss_method="power",
        avg_power=kw.pop("avg_power", 220),
        norm_power=kw.pop("norm_power", 235),
        avg_hr=150,
        polyline=line,
        **kw,
    )


def _detail(seg_times: dict[int, int], temp=None) -> dict:
    return {
        "segments": [
            {
                "id": sid,
                "name": f"Climb {sid}",
                "distance_m": 2000,
                "grade": 5.0,
                "climb": 3,
                "elapsed_s": t,
                "moving_s": t,
                "start_index": sid,
                "watts": 280,
                "hr": 165,
                "pr_rank": None,
            }
            for sid, t in seg_times.items()
        ],
        "laps": [],
        "avg_temp": temp,
        "elapsed_s": None,
        "moving_s": None,
        "fetched_at": "2026-10-05T00:00:00",
    }


@pytest.fixture()
def racer(make_user):
    p = make_user("rider@example.com", "Rider")
    uid = p.get("/api/auth/me").json()["id"]
    with SessionLocal() as db:
        u = db.get(User, uid)
        u.timezone, u.ftp_watts = "Africa/Johannesburg", 250
        race = Race(
            user_id=uid, code="k2c", name="Knysna Classic", distance_km=60, target_date=RACE_DAY, discipline="Road"
        )
        db.add(race)
        db.commit()
        rid = race.id
    return p, uid, rid


def test_strava_keeps_elapsed_time(racer):
    _, uid, _ = racer
    item = {
        "id": 99,
        "name": "Race",
        "sport_type": "Ride",
        "start_date": "2026-10-04T05:00:00Z",
        "moving_time": 7200,
        "elapsed_time": 7900,
        "distance": 60000,
    }
    with SessionLocal() as db:
        strava._upsert(db, db.get(User, uid), item)
        db.commit()
        a = db.query(Activity).filter_by(user_id=uid, external_id="99").one()
        assert (a.duration_s, a.elapsed_s) == (7200, 7900)


def test_review_ride_earlier_years_and_segments(racer):
    p, uid, rid = racer
    with SessionLocal() as db:
        db.add(_ride(uid, "r26", RACE_DAY, detail=_detail({1: 600, 2: 300}, temp=19)))
        db.add(_ride(uid, "short", RACE_DAY, km=12, moving=1800, elapsed=1900, hour=4))  # a warm-up the same day
        # Earlier years: 2025 the same course (faster on climb 1), 2024 a different line, 2023 a month off.
        db.add(_ride(uid, "r25", date(2025, 10, 5), moving=7000, elapsed=7300, detail=_detail({1: 580, 2: 320})))
        db.add(_ride(uid, "x24", date(2024, 10, 6), line=OTHER_LINE))
        db.add(_ride(uid, "x23", date(2023, 11, 20)))
        db.commit()
    r = p.get(f"/api/athletes/me/races/{rid}/review").json()
    ride = r["ride"]
    assert ride["external_id"] == "r26"  # the race, not the warm-up
    assert (ride["elapsed_s"], ride["moving_s"], ride["stopped_s"]) == (7800, 7200, 600)
    assert ride["speed_moving"] == 30.0 and ride["device_temp"] == 19
    assert {c["distance_km"] for c in r["candidates"]} == {60.0, 12.0}
    assert [e["year"] for e in r["earlier"]] == [2025]
    assert r["earlier"][0]["ctl_before"] is not None
    segs = {s["id"]: s for s in r["segments"]}
    assert segs[1]["times"]["2026"]["elapsed_s"] == 600 and segs[1]["best"] == "2025"
    assert segs[1]["vs_best_before"] == 20 and segs[2]["vs_best_before"] == -20


def test_post_race_update_pick_ride_and_standings(racer):
    p, uid, rid = racer
    with SessionLocal() as db:
        db.add(_ride(uid, "r26", RACE_DAY))
        db.add(_ride(uid, "r26b", RACE_DAY, km=58, hour=10))
        db.commit()
        other = db.query(Activity).filter_by(external_id="r26b").one().id
    body = {
        "activity_id": other,
        "official_time": "2:09:30",
        "position": 41,
        "field_size": 380,
        "category": "M40",
        "category_position": 7,
        "feeling": 4,
        "went_well": "Paced the climb well",
        "nutrition": "2 bottles, 3 gels",
        "riders": [{"name": "Pieter", "time": "2:05:00", "category": "M40"}, {"name": "Anna", "time": "2:15"}],
    }
    res = p.request("PUT", f"/api/races/{rid}/result", json=body)
    assert res.status_code == 200, res.text
    assert res.json()["official_time"] == "2:09:30" and res.json()["riders"][1]["time"] == "2:15"
    r = p.get(f"/api/athletes/me/races/{rid}/review").json()
    assert r["ride"]["external_id"] == "r26b"  # the athlete's pick
    with SessionLocal() as db:
        assert db.get(Activity, other).race_id == rid
    names = [(s["name"], s["gap_s"]) for s in r["standings"]]
    assert names == [("Pieter", -270), ("You", 0), ("Anna", 330)]
    # A session that isn't on the race's day can't be picked.
    with SessionLocal() as db:
        db.add(_ride(uid, "later", RACE_DAY + timedelta(days=3)))
        db.commit()
        later = db.query(Activity).filter_by(external_id="later").one().id
    assert p.request("PUT", f"/api/races/{rid}/result", json={"activity_id": later}).status_code == 422
    assert p.request("PUT", f"/api/races/{rid}/result", json={"official_time": "abc"}).status_code == 422
    # Clearing a field: sent empty.
    assert "went_well" not in p.request("PUT", f"/api/races/{rid}/result", json={"went_well": ""}).json()


def test_other_athletes_who_share_and_rode_it(racer, make_user):
    p, uid, rid = racer
    friend = make_user("friend@example.com", "Thandi")
    fid = friend.get("/api/auth/me").json()["id"]
    stranger = make_user("stranger@example.com", "Stranger")
    sid = stranger.get("/api/auth/me").json()["id"]
    with SessionLocal() as db:
        db.add(_ride(uid, "me", RACE_DAY))
        db.add(_ride(fid, "f1", RACE_DAY, elapsed=7500))  # shares with the rider, same course
        db.add(_ride(sid, "s1", RACE_DAY, elapsed=7000))  # same race, doesn't share
        db.add(Grant(athlete_id=fid, coach_id=uid, scopes=["activities"], role="friend", status="active"))
        db.commit()
    r = p.get(f"/api/athletes/me/races/{rid}/review").json()
    assert [o["name"] for o in r["others"]] == ["Thandi"]
    assert [(s["name"], s["gap_s"]) for s in r["standings"]] == [("Thandi", -300), ("You", 0)]


def test_coach_reads_but_gets_no_other_riders(racer, make_user):
    p, uid, rid = racer
    coach = make_user("coach@example.com", "Coach")
    cid = coach.get("/api/auth/me").json()["id"]
    with SessionLocal() as db:
        db.add(_ride(uid, "me", RACE_DAY))
        db.add(Grant(athlete_id=uid, coach_id=cid, scopes=["plans", "activities"], role="coach", status="active"))
        db.commit()
    r = coach.get(f"/api/athletes/{uid}/races/{rid}/review")
    assert r.status_code == 200 and r.json()["own"] is False and r.json()["others"] == []
    assert coach.request("PUT", f"/api/races/{rid}/result", json={"position": 3}).status_code == 404


def test_race_day_weather_head_and_tailwind(racer, monkeypatch):
    """Wind from the east all morning: the way out (east) is into it, the way back has it behind."""
    p, uid, rid = racer
    with SessionLocal() as db:
        db.add(_ride(uid, "me", RACE_DAY))
        db.commit()
        aid = db.query(Activity).filter_by(external_id="me").one().id

    async def fake_history(points, day, today):
        times = [f"{day.isoformat()}T{h:02d}:00" for h in range(24)]
        hourly = {
            "time": times,
            "wind_speed_10m": [25] * 24,
            "wind_direction_10m": [90] * 24,
            "wind_gusts_10m": [40] * 24,
            "temperature_2m": [18] * 24,
            "precipitation": [0] * 24,
            "weather_code": [1] * 24,
        }
        return [hourly for _ in points]

    monkeypatch.setattr(weather, "history", fake_history)
    w = p.get(f"/api/athletes/me/races/{rid}/review/weather").json()[str(aid)]
    assert w["first_half"] == "headwind" and w["second_half"] == "tailwind"
    assert w["wind_kmh"] == 25 and w["wind_from"] == "E" and w["gusts_kmh"] == 40


def test_compact_detail_from_strava():
    d = race_review.compact_detail(
        {
            "elapsed_time": 7800,
            "moving_time": 7200,
            "average_temp": 21,
            "segment_efforts": [
                {
                    "segment": {
                        "id": 5,
                        "name": "Big climb",
                        "distance": 3000,
                        "average_grade": 6.1,
                        "climb_category": 3,
                    },
                    "elapsed_time": 700,
                    "moving_time": 690,
                    "start_index": 900,
                    "average_watts": 290,
                    "device_watts": True,
                    "average_heartrate": 168.4,
                },
                {"segment": {"id": 4, "name": "Sprint"}, "elapsed_time": 30, "start_index": 100},
            ],
            "laps": [{"name": "Lap 1", "elapsed_time": 3900}],
        }
    )
    assert [s["id"] for s in d["segments"]] == [4, 5]  # in the order they're ridden
    assert d["segments"][1]["watts"] == 290 and d["segments"][1]["hr"] == 168
    assert d["laps"] == [] and d["avg_temp"] == 21  # one lap is no laps


def test_recent_results_for_the_ai_coach(racer):
    p, uid, rid = racer
    p.request("PUT", f"/api/races/{rid}/result", json={"official_time": "2:10", "next_time": "Eat earlier"})
    with SessionLocal() as db:
        out = race_review.recent_results(db, uid, date(2026, 11, 23))
    assert out == [{"race": "Knysna Classic", "date": "2026-10-04", "next_time": "Eat earlier", "official_s": 7800}]
