"""Connections: the sleep / HRV source, and the reminder to pick a main activity source."""

from app.db import Connection, SessionLocal
from app.security import encrypt_json


def _link(uid, provider, **options):
    with SessionLocal() as db:
        token = encrypt_json({"access_token": "t", "scope": "ACTIVITY:READ,WELLNESS:READ,CALENDAR:WRITE"})
        db.add(Connection(user_id=uid, provider=provider, token_enc=token, options=options or None))
        db.commit()


def test_reminder_until_a_main_source_is_picked(make_user):
    p = make_user("rider@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    _link(uid, "strava")
    assert p.get("/api/connections").json()["sources"]["needs_primary"] is False  # one app: nothing to mix up
    _link(uid, "garmin", activities=True, wellness=True)
    s = p.get("/api/connections").json()["sources"]
    assert s["linked"] == ["strava", "garmin"] and s["needs_primary"] is True
    assert p.get("/api/athletes/me").json()["sources_need_confirm"] is True
    assert p.request("PUT", "/api/connections/activity-source", json={"provider": "strava"}).status_code == 200
    assert p.get("/api/connections").json()["sources"]["needs_primary"] is False
    assert p.get("/api/athletes/me").json()["sources_need_confirm"] is False


def test_sleep_and_hrv_from_one_app(make_user):
    p = make_user("rider@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    _link(uid, "garmin", activities=False, wellness=True, weight=True)
    _link(uid, "intervals_icu", wellness=True)
    w = p.get("/api/connections").json()["sources"]["wellness"]
    assert w == {"from": ["garmin", "intervals_icu"], "choices": ["garmin", "intervals_icu"]}  # twice
    r = p.request("PUT", "/api/connections/wellness-source", json={"provider": "garmin"}).json()
    assert r["wellness"]["from"] == ["garmin"]
    garmin = next(c for c in p.get("/api/connections").json()["connections"] if c["provider"] == "garmin")
    assert garmin["options"]["weight"] is True  # other Garmin data stays as it was
    assert p.request("PUT", "/api/connections/wellness-source", json={"provider": "strava"}).status_code == 422
    r = p.request("PUT", "/api/connections/wellness-source", json={"provider": None}).json()
    assert r["wellness"]["from"] == []
