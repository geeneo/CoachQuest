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
    monkeypatch.setattr(garmin, "_fetch", lambda *a: ("{}", [], [], (kg, measured_at) if a[3] else None, None))
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


def test_saving_the_profile_for_another_field_keeps_garmins_weight(monkeypatch, make_user):
    p = make_user("a@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    _sync_with_weight(monkeypatch, uid, 54.7, datetime.now() - timedelta(hours=3))
    # The Profile form sends every field: the weight unchanged, the FTP new.
    p.patch("/api/me", json={"weight_kg": 54.7, "ftp_watts": 213})
    me = p.get("/api/auth/me").json()
    assert me["weight_source"] == "garmin"
    # A weigh-in older than the save but newer than the last one still comes through.
    user = _sync_with_weight(monkeypatch, uid, 54.2, datetime.now() - timedelta(hours=1))
    assert user.weight_kg == 54.2 and user.weight_source == "garmin"


def test_weigh_ins_by_day():
    from datetime import date

    body = {
        "dateWeightList": [
            {"calendarDate": "2026-11-07", "weight": 55100.0, "date": 1},
            {"calendarDate": "2026-11-08", "weight": 54900.0, "date": 2},
            {"calendarDate": "2026-11-08", "weight": 54700.0, "date": 3},  # later that day: kept
            {"calendarDate": "2026-11-09", "weight": 5.0},  # nonsense
        ]
    }
    assert garmin.weigh_ins(body) == {date(2026, 11, 7): 55.1, date(2026, 11, 8): 54.7}
    summaries = {
        "dailyWeightSummaries": [
            {"summaryDate": "2026-11-08", "latestWeight": {"calendarDate": "2026-11-08", "weight": 54700}}
        ]
    }
    assert garmin.weigh_ins(summaries) == {date(2026, 11, 8): 54.7}
    assert garmin.weigh_ins(None) == {}


def test_weight_line_on_the_wellness_chart(monkeypatch, make_user):
    from datetime import date

    p = make_user("a@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    today = date.today()
    asked = []

    def fake_fetch(*a):
        asked.append(a[6])
        rows = [
            {"day": today - timedelta(days=3), "weight_kg": 55.0},
            {"day": today, "resting_hr": 44, "weight_kg": 54.7},
        ]
        return "{}", rows, [], (54.7, datetime.now()) if a[3] else None, None

    monkeypatch.setattr(garmin, "_fetch", fake_fetch)
    with SessionLocal() as db:
        conn = Connection(user_id=uid, provider="garmin", token_enc=encrypt_json({"tokens": "{}"}))
        db.add(conn)
        db.commit()
        asyncio.run(garmin.sync(db, conn))
        assert asked[0] == today - timedelta(days=garmin.WEIGHT_HISTORY_DAYS)  # the first time: two years back
        asyncio.run(garmin.sync(db, conn))
        assert asked[1] > today - timedelta(days=5)  # then since the last sync
    rows = {r["day"]: r for r in p.get("/api/athletes/me/wellness?days=7").json()}
    assert rows[(today - timedelta(days=3)).isoformat()]["weight_kg"] == 55.0
    assert rows[today.isoformat()]["weight_kg"] == 54.7 and rows[today.isoformat()]["resting_hr"] == 44
    # A weight typed in on the Profile goes on today's line too.
    p.patch("/api/me", json={"weight_kg": 54.2})
    rows = {r["day"]: r for r in p.get("/api/athletes/me/wellness?days=7").json()}
    assert rows[today.isoformat()]["weight_kg"] == 54.2
