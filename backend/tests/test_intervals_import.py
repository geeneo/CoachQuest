"""Choosing what to import from Intervals.icu, against a fake Intervals.icu."""

from datetime import date, datetime, timedelta

import httpx
import pytest

from app import runtime
from app.db import Activity, Connection, SessionLocal, WellnessDay
from app.delivery import intervals_icu as icu
from app.security import encrypt_json
from tests.test_sync import FakeIntervals

TODAY = date.today()


def _icu_activity(i, day, source="GARMIN_CONNECT", **kw):
    return {
        "id": f"i{i}",
        "start_date": f"{day.isoformat()}T05:30:00Z",
        "start_date_local": f"{day.isoformat()}T07:30:00",
        "type": "VirtualRide",
        "name": f"Zwift ride {i}",
        "moving_time": 3600,
        "distance": 30000.0,
        "total_elevation_gain": 250.0,
        "average_heartrate": 140,
        "icu_average_watts": 190,
        "icu_weighted_avg_watts": 205,
        "icu_training_load": 62,
        "icu_joules": 684000,
        "trainer": True,
        "source": source,
        **kw,
    }


@pytest.fixture()
def fake(monkeypatch):
    f = FakeIntervals()
    monkeypatch.setattr(icu, "transport", httpx.MockTransport(f.handler))
    monkeypatch.setitem(runtime._overrides, "intervals_client_id", "app")
    monkeypatch.setitem(runtime._overrides, "intervals_client_secret", "secret-secret")
    return f


@pytest.fixture()
def rider(make_user):
    a = make_user("rider@example.com")
    uid = a.get("/api/auth/me").json()["id"]
    with SessionLocal() as db:
        db.add(
            Connection(
                user_id=uid,
                provider="intervals_icu",
                external_id="i4242",
                token_enc=encrypt_json({"access_token": "tok", "scope": icu.SCOPE}),
            )
        )
        db.commit()
    return a, uid


def _activities(uid):
    with SessionLocal() as db:
        return db.query(Activity).filter_by(user_id=uid).order_by(Activity.start_time).all()


def test_imports_are_off_until_chosen(rider, fake):
    a, uid = rider
    fake.activities = [_icu_activity(1, TODAY - timedelta(days=1))]
    r = a.post("/api/connections/intervals_icu/sync")
    assert r.status_code == 200 and r.json()["fetched"] == 0
    assert [c for c in fake.calls if c[0] == "GET"] == []


def test_activities_import(rider, fake):
    a, uid = rider
    fake.activities = [
        _icu_activity(1, TODAY - timedelta(days=1)),
        _icu_activity(2, TODAY - timedelta(days=2), source="STRAVA"),  # not passed on by Intervals.icu
    ]
    r = a.request("PATCH", "/api/connections/intervals_icu/options", json={"activities": True})
    assert r.status_code == 200 and r.json()["options"] == {"activities": True, "wellness": False}
    acts = _activities(uid)
    assert [x.external_id for x in acts] == ["i1"]
    x = acts[0]
    assert x.source == "intervals_icu" and x.sport == "VirtualRide" and x.indoor
    assert x.start_time == datetime.combine(TODAY - timedelta(days=1), datetime.min.time()) + timedelta(
        hours=5, minutes=30
    )
    assert (x.norm_power, x.avg_power, x.tss, x.kilojoules) == (205, 190, 62, 684.0)
    get = next(c for c in fake.calls if c[0] == "GET")
    assert get[1].startswith("/api/v1/athlete/0/activities?oldest=")
    # Shows on My training, once even when Strava has the same ride.
    shown = a.get("/api/athletes/me/activities?days=7").json()
    assert [s["name"] for s in shown] == ["Zwift ride 1"]
    with SessionLocal() as db:
        db.add(
            Activity(
                user_id=uid,
                source="strava",
                external_id="s1",
                name="Strava copy",
                sport="VirtualRide",
                start_time=x.start_time + timedelta(minutes=2),
                duration_s=3600,
            )
        )
        db.commit()
    assert [s["name"] for s in a.get("/api/athletes/me/activities?days=7").json()] == ["Strava copy"]
    # Turning it off hides them; deleting removes only Intervals.icu's.
    a.request("PATCH", "/api/connections/intervals_icu/options", json={"activities": False})
    a.delete("/api/connections/intervals_icu/data/activities")
    assert [x.source for x in _activities(uid)] == ["strava"]


def test_wellness_fills_what_garmin_leaves(rider, fake):
    a, uid = rider
    d1, d2 = TODAY - timedelta(days=2), TODAY - timedelta(days=1)
    with SessionLocal() as db:
        db.add(WellnessDay(user_id=uid, day=d1, resting_hr=48, hrv_ms=None, source="garmin"))
        db.commit()
    fake.wellness = [
        {"id": d1.isoformat(), "restingHR": 52, "hrv": 71.0, "sleepSecs": 27000},
        {"id": d2.isoformat(), "restingHR": 50, "hrv": 65.0, "sleepScore": 81, "steps": 9000},
    ]
    a.request("PATCH", "/api/connections/intervals_icu/options", json={"wellness": True})
    with SessionLocal() as db:
        rows = {w.day: w for w in db.query(WellnessDay).filter_by(user_id=uid)}
    assert rows[d1].resting_hr == 48 and rows[d1].hrv_ms == 71.0 and rows[d1].source == "garmin"  # Garmin wins
    assert rows[d2].source == "intervals_icu" and rows[d2].sleep_score == 81 and rows[d2].steps == 9000
    days = {w["day"]: w for w in a.get("/api/athletes/me/wellness?days=7").json()}
    assert d2.isoformat() in days
    # Off: Intervals.icu's days are hidden, Garmin's stay.
    a.request("PATCH", "/api/connections/intervals_icu/options", json={"wellness": False})
    days = {w["day"] for w in a.get("/api/athletes/me/wellness?days=7").json()}
    assert d1.isoformat() in days and d2.isoformat() not in days


def test_lost_access_marks_the_connection(rider, fake):
    a, uid = rider
    fake.fail_next(401)
    r = a.request("PATCH", "/api/connections/intervals_icu/options", json={"activities": True})
    assert r.status_code == 200
    conn = next(c for c in a.get("/api/connections").json()["connections"] if c["provider"] == "intervals_icu")
    assert conn["status"] == "error" and "Reconnect" in conn["last_error"]


def test_disconnect_with_purge(rider, fake):
    a, uid = rider
    fake.activities = [_icu_activity(1, TODAY - timedelta(days=1))]
    a.request("PATCH", "/api/connections/intervals_icu/options", json={"activities": True})
    assert len(_activities(uid)) == 1
    a.delete("/api/connections/intervals?purge=true")
    assert _activities(uid) == []


def test_strava_and_garmin_tools_stay_their_own(rider, fake):
    a, uid = rider
    assert a.post("/api/connections/intervals_icu/backfill", json={"since": "2025-01-01"}).status_code == 404
    assert a.request("PATCH", "/api/connections/intervals_icu/options", json={"weight": True}).status_code == 422
