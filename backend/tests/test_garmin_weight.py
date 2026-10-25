import asyncio
from datetime import datetime, timedelta

from app.db import Connection, SessionLocal, User
from app.providers import garmin
from app.security import encrypt_json


def test_latest_weight_parses_grams_and_timestamp():
    kg, when = garmin.latest_weight({"weight": 72450.0, "timestampGMT": 1761379200000})
    assert kg == 72.5 and when.year == 2025
    assert garmin.latest_weight({"dateWeightList": [{"weight": 80000, "calendarDate": "2026-10-20"}]})[0] == 80.0
    assert garmin.latest_weight({}) is None
    assert garmin.latest_weight({"weight": 5}) is None  # nonsense values ignored


def _sync_with_weight(monkeypatch, user_id, kg, measured_at, options=None):
    monkeypatch.setattr(garmin, "_fetch", lambda *a: ("{}", [], [], (kg, measured_at) if a[3] else None))
    with SessionLocal() as db:
        conn = Connection(user_id=user_id, provider="garmin", token_enc=encrypt_json({"tokens": "{}"}), options=options)
        db.add(conn)
        db.commit()
        asyncio.run(garmin.sync(db, conn))
        db.delete(conn)
        db.commit()
        return db.get(User, user_id)


def test_sync_copies_weight_to_profile(monkeypatch, make_user):
    p = make_user("a@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    _sync_with_weight(monkeypatch, uid, 71.2, datetime.now() - timedelta(days=1))
    me = p.get("/api/auth/me").json()
    assert me["weight_kg"] == 71.2 and me["weight_source"] == "garmin"


def test_newer_manual_value_wins_until_newer_weigh_in(monkeypatch, make_user):
    p = make_user("a@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    p.patch("/api/me", json={"weight_kg": 70})
    user = _sync_with_weight(monkeypatch, uid, 75.0, datetime.now() - timedelta(days=2))
    assert user.weight_kg == 70 and user.weight_source == "manual"
    user = _sync_with_weight(monkeypatch, uid, 69.4, datetime.now() + timedelta(minutes=1))
    assert user.weight_kg == 69.4 and user.weight_source == "garmin"


def test_weight_option_off_leaves_profile_alone(monkeypatch, make_user):
    p = make_user("a@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    user = _sync_with_weight(monkeypatch, uid, 80.0, datetime.now(), options={"weight": False})
    assert user.weight_kg is None
