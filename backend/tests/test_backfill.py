import asyncio
from datetime import date, datetime, timedelta

import httpx
import pytest

from app import backfill
from app.db import Activity, Connection, SessionLocal, WellnessDay
from app.providers import garmin, strava
from app.security import encrypt_json

SECRET = "ab" * 20
REAL_CLIENT = httpx.AsyncClient  # before any test patches it


def _resp(status=200, usage="10,100", limit="200,2000"):
    return httpx.Response(status, headers={"X-RateLimit-Usage": usage, "X-RateLimit-Limit": limit})


NOW = datetime(2026, 10, 25, 9, 7)


def test_resume_time_from_rate_limit_headers():
    assert strava._resume_time(_resp(), NOW) is None
    assert strava._resume_time(_resp(usage="180,500"), NOW) == datetime(2026, 10, 25, 9, 15)
    assert strava._resume_time(_resp(usage="10,1800"), NOW) == datetime(2026, 10, 26, 0, 5)
    assert strava._resume_time(_resp(status=429, usage="200,600"), NOW) == datetime(2026, 10, 25, 9, 15)
    read = httpx.Response(200, headers={"X-ReadRateLimit-Usage": "80,10", "X-ReadRateLimit-Limit": "100,1000"})
    assert strava._resume_time(read, NOW) == datetime(2026, 10, 25, 9, 15)


def _strava_conn(user_id):
    with SessionLocal() as db:
        conn = Connection(
            user_id=user_id,
            provider="strava",
            token_enc=encrypt_json({"access_token": "a", "refresh_token": "r", "client_id": "777"}),
            expires_at=datetime(2100, 1, 1),
        )
        db.add(conn)
        db.add(Activity(user_id=user_id, source="strava", external_id="new", start_time=datetime(2026, 5, 1)))
        db.commit()
        return conn.id


def _fake_strava_pages(monkeypatch, pages, usage="10,100"):
    """Each request returns the next page; records the `before` cursor it was asked for."""
    asked = []

    def handler(request):
        asked.append(int(request.url.params["before"]))
        items = pages.pop(0) if pages else []
        return httpx.Response(200, json=items, headers={"X-RateLimit-Usage": usage, "X-RateLimit-Limit": "200,2000"})

    monkeypatch.setattr(
        strava.httpx, "AsyncClient", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler), **kw)
    )
    return asked


def _item(i, day):
    return {"id": i, "name": f"Ride {i}", "sport_type": "Ride", "start_date": f"{day}T06:00:00Z", "moving_time": 3600}


@pytest.fixture()
def athlete(make_user):
    p = make_user("a@example.com")
    p.request("PUT", "/api/connections/strava/app", json={"client_id": "777", "client_secret": SECRET})
    return p, p.get("/api/auth/me").json()["id"]


def test_strava_backfill_runs_to_target(monkeypatch, athlete):
    p, uid = athlete
    conn_id = _strava_conn(uid)
    _fake_strava_pages(monkeypatch, [[_item(1, "2026-03-01"), _item(2, "2026-02-01")], [_item(3, "2025-12-01")], []])
    r = p.post("/api/connections/strava/backfill", json={"since": "2025-06-01"})
    assert r.status_code == 200, r.text
    asyncio.run(backfill.run(conn_id))
    with SessionLocal() as db:
        conn = db.get(Connection, conn_id)
        assert conn.backfill["status"] == "done" and conn.backfill["stored"] == 3
        assert db.query(Activity).filter(Activity.user_id == uid).count() == 4


def test_strava_backfill_pauses_and_resumes(monkeypatch, athlete):
    p, uid = athlete
    conn_id = _strava_conn(uid)
    _fake_strava_pages(monkeypatch, [[_item(1, "2026-03-01")]], usage="190,500")
    p.post("/api/connections/strava/backfill", json={"since": "2025-06-01"})  # runs the first step
    asyncio.run(backfill.run(conn_id))  # a second call must not continue a paused run
    with SessionLocal() as db:
        bf = db.get(Connection, conn_id).backfill
        assert bf["status"] == "waiting" and bf["resume_at"] and bf["cursor"].startswith("2026-03-01")
        conn = db.get(Connection, conn_id)
        conn.backfill = {**bf, "resume_at": (datetime.now() - timedelta(minutes=1)).isoformat()}
        db.commit()
    asked = _fake_strava_pages(monkeypatch, [[_item(2, "2025-08-01")], []])
    asyncio.run(backfill.resume_due())
    with SessionLocal() as db:
        assert db.get(Connection, conn_id).backfill["status"] == "done"
    assert datetime.utcfromtimestamp(asked[0]).date() == date(2026, 3, 1)  # resumed where it paused


def test_backfill_validation_and_cancel(athlete, monkeypatch):
    async def no_run(conn_id):
        pass

    monkeypatch.setattr(backfill, "run", no_run)  # keep the import from actually starting
    p, uid = athlete
    _strava_conn(uid)
    assert p.post("/api/connections/strava/backfill", json={"since": "2008-01-01"}).status_code == 422
    # Data from 2026-05-01 onwards is already there.
    assert p.post("/api/connections/strava/backfill", json={"since": "2026-06-01"}).status_code == 422
    p.post("/api/connections/strava/backfill", json={"since": "2025-01-01"})
    assert p.post("/api/connections/strava/backfill", json={"since": "2025-01-01"}).status_code == 409
    r = p.delete("/api/connections/strava/backfill")
    assert r.json()["backfill"]["status"] == "cancelled"


def test_garmin_backfill_steps_back_two_weeks(monkeypatch, make_user):
    p = make_user("g@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    calls = []

    def fake_fetch(tokens, wellness_days, activity_range, want_weight, want_thresholds=False):
        calls.append((len(wellness_days), activity_range))
        rows = [{"day": d, "resting_hr": 50} for d in wellness_days]
        return "{}", rows, [], None, None

    monkeypatch.setattr(garmin, "_fetch", fake_fetch)
    monkeypatch.setattr(backfill, "GARMIN_PAUSE_S", 0)
    today = date.today()
    with SessionLocal() as db:
        conn = Connection(user_id=uid, provider="garmin", token_enc=encrypt_json({"tokens": "{}"}))
        db.add(conn)
        db.add(WellnessDay(user_id=uid, day=today - timedelta(days=30)))
        db.commit()
        conn_id = conn.id
    target = today - timedelta(days=60)
    r = p.post("/api/connections/garmin/backfill", json={"since": target.isoformat()})
    assert r.status_code == 200, r.text
    asyncio.run(backfill.run(conn_id))
    with SessionLocal() as db:
        assert db.get(Connection, conn_id).backfill["status"] == "done"
        assert db.query(WellnessDay).filter(WellnessDay.user_id == uid).count() == 31
    assert [c[0] for c in calls] == [14, 14, 2]


def test_refresh_fills_new_fields_on_stored_activities(monkeypatch, athlete):
    p, uid = athlete
    conn_id = _strava_conn(uid)  # has one stored activity from 2026-05-01, without speed
    item = {**_item("new", "2026-05-01"), "average_speed": 7.5, "average_cadence": 88, "kilojoules": 1500}
    _fake_strava_pages(monkeypatch, [[item], []])
    r = p.post("/api/connections/strava/refresh")
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        a = db.query(Activity).filter_by(user_id=uid, external_id="new").one()
        assert (a.avg_speed_ms, a.avg_cadence, a.kilojoules) == (7.5, 88, 1500)
        conn = db.get(Connection, conn_id)
        assert conn.backfill["status"] == "done" and conn.backfill["mode"] == "refresh"
        assert conn.options["fields_version"] == backfill.FIELDS_VERSION


def test_refresh_outdated_runs_once(monkeypatch, athlete):
    _, uid = athlete
    conn_id = _strava_conn(uid)
    with SessionLocal() as db:
        assert backfill.refresh_outdated(db) == [conn_id]
        db.get(Connection, conn_id).backfill = {"status": "done"}
        db.commit()
        assert backfill.refresh_outdated(db) == []  # already at the current fields version
