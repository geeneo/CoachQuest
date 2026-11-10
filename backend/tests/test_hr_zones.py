"""Training load from time in heart-rate zones for sessions without power (hr_load.py)."""

import asyncio
from datetime import datetime, timedelta

from app import hr_load
from app.db import Activity, Connection, SessionLocal, User
from app.fitness import score


def test_an_hour_at_threshold_is_100_and_hard_efforts_count_more():
    assert hr_load.intensity(1.0) == 1.0
    assert hr_load.tss({"160": 3600}, 160) == 100.0
    # The same average heart rate (140 at LTHR 160), ridden steady or as hard and easy halves.
    steady = hr_load.tss({"140": 3600}, 160)
    mixed = hr_load.tss({"120": 1800, "160": 1800}, 160)
    assert mixed > steady
    # Easy riding counts less than the average-based estimate ((140/160)² x 100 = 76.6).
    assert steady < 76.6
    assert hr_load.tss(None, 160) is None and hr_load.tss({"150": 60}, None) is None


def test_histogram_from_a_stream():
    times = [0, 1, 2, 3, 63, 64]  # a pause of 60 s counts as 30
    hrs = [100, 120, 120, 121, 150, 150]
    assert hr_load.histogram(times, hrs) == {"120": 2, "121": 1, "150": 31}


def _ride(uid, n, source, hist=None, method="hr", avg_hr=140):
    return Activity(
        user_id=uid,
        source=source,
        external_id=str(n),
        name="Ride",
        sport="Ride",
        start_time=datetime.now() - timedelta(days=n),
        duration_s=3600,
        distance_m=30000,
        elevation_m=100,
        avg_hr=avg_hr,
        tss=76.6,
        tss_method=method,
        hr_histogram=hist,
    )


def test_score_uses_zones_when_fetched(make_user):
    p = make_user("a@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    with SessionLocal() as db:
        user = db.get(User, uid)
        user.lthr_bpm = 160
        a = _ride(uid, 1, "strava")
        assert score(a, user) == (76.6, "hr")  # by the average until the stream comes
        a.hr_histogram = {"120": 1800, "160": 1800}
        tss, method = score(a, user)
        assert method == "hr zones" and tss == hr_load.tss(a.hr_histogram, 160)
        a.norm_power, user.ftp_watts = 200, 250  # power still wins
        assert score(a, user)[1] == "power"


def test_fill_fetches_streams_newest_first(make_user, monkeypatch):
    p = make_user("a@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    with SessionLocal() as db:
        db.get(User, uid).lthr_bpm = 160
        db.add(Connection(user_id=uid, provider="strava", token_enc="", status="active"))
        db.add(Connection(user_id=uid, provider="garmin", token_enc="x", status="active"))
        db.add_all([_ride(uid, 1, "strava"), _ride(uid, 2, "strava"), _ride(uid, 3, "garmin")])
        db.add(_ride(uid, 4, "strava", method="power"))  # has power: no stream needed
        db.add(_ride(uid, 5, "strava", avg_hr=None))  # no heart rate at all
        db.commit()
    asked = []

    async def fake_strava(db, conn, ext):
        asked.append(ext)
        return None if ext == "2" else ([0, 1800, 3600], [120, 160, 160])

    def fake_garmin(tokens, ids):
        return "tokens", {i: ([0, 3600], [150, 150]) for i in ids}

    monkeypatch.setattr(hr_load, "_strava_stream", fake_strava)
    monkeypatch.setattr(hr_load, "_garmin_streams", fake_garmin)
    monkeypatch.setattr(hr_load, "decrypt_json", lambda v: {"tokens": "t"})
    monkeypatch.setattr(hr_load, "encrypt_json", lambda v: "x")
    assert asyncio.run(hr_load.fill()) == 2
    assert asked == ["1", "2"]  # newest first; power and no-heart-rate sessions left out
    with SessionLocal() as db:
        by_ext = {a.external_id: a for a in db.query(Activity)}
        assert by_ext["1"].tss_method == "hr zones" and by_ext["1"].hr_histogram == {"160": 60}
        assert by_ext["2"].tss_method == "hr" and by_ext["2"].hr_tried_at  # no stream: kept, not asked again
        assert by_ext["3"].tss_method == "hr zones"
    assert asyncio.run(hr_load.fill()) == 0  # nothing left to fetch
