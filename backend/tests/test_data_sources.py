"""'Where your data comes from': one app per kind, asked when a second app is linked."""

from app.db import Connection, SessionLocal
from app.security import encrypt_json


def _link(uid, provider, **options):
    with SessionLocal() as db:
        token = encrypt_json({"access_token": "t", "scope": "CALENDAR:WRITE"})
        db.add(Connection(user_id=uid, provider=provider, token_enc=token, options=options or None))
        db.commit()


def test_asked_once_two_apps_are_linked(make_user):
    p = make_user("rider@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    _link(uid, "strava")
    s = p.get("/api/connections").json()["sources"]
    assert s["linked"] == ["strava"] and s["needs_confirm"] is False
    _link(uid, "garmin", activities=True, wellness=True)
    s = p.get("/api/connections").json()["sources"]
    assert s["needs_confirm"] is True and p.get("/api/athletes/me").json()["sources_need_confirm"] is True
    assert s["from"] == {"activities": ["strava", "garmin"], "wellness": ["garmin"]}  # rides come in twice
    assert s["choices"] == {"activities": ["strava", "garmin"], "wellness": ["garmin"]}

    r = p.request("PUT", "/api/connections/sources", json={"activities": "strava", "wellness": "garmin"})
    s = r.json()["sources"]
    assert s["from"] == {"activities": ["strava"], "wellness": ["garmin"]} and s["needs_confirm"] is False
    garmin = next(c for c in r.json()["connections"] if c["provider"] == "garmin")
    assert garmin["options"]["activities"] is False and garmin["options"]["weight"] is True  # other data stays
    assert p.get("/api/athletes/me").json()["sources_need_confirm"] is False

    # Linking a third app asks again.
    _link(uid, "intervals_icu")
    s = p.get("/api/connections").json()["sources"]
    assert s["needs_confirm"] is True and s["choices"]["wellness"] == ["garmin", "intervals_icu"]
    assert s["from"]["activities"] == ["strava"]  # Intervals.icu imports start off


def test_picks_must_be_linked_apps(make_user):
    p = make_user("rider@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    _link(uid, "strava")
    _link(uid, "garmin")
    bad = p.request("PUT", "/api/connections/sources", json={"activities": "garmin", "wellness": "strava"})
    assert bad.status_code == 422  # Strava has no wellness
    r = p.request("PUT", "/api/connections/sources", json={"activities": "garmin", "wellness": None})
    assert r.json()["sources"]["from"] == {"activities": ["garmin"], "wellness": []}
