"""The plan in Strava activity descriptions: preview, write (keeping the athlete's text), auto after sync."""

import asyncio
from datetime import datetime, time, timedelta

import pytest
from test_phase3 import _create, _next_monday, planner  # noqa: F401  (fixture)

from app import strava_notes
from app.db import Activity, Connection, SessionLocal, User, utcnow
from app.providers import strava
from app.security import encrypt_json


@pytest.fixture()
def athlete(make_user, planner, monkeypatch):  # noqa: F811
    p = make_user("a@example.com", "Ann")
    aid = p.get("/api/auth/me").json()["id"]
    _create(p)  # Tuesdays: Zwift / indoor "Tempo", 60 min
    remote = {"description": "Great morning with the club"}
    calls = []

    async def fake_get(db, conn, activity_id):
        return dict(remote)

    async def fake_update(db, conn, activity_id, changes):
        calls.append((activity_id, changes))
        remote.update(changes)
        return remote

    monkeypatch.setattr(strava, "get_activity", fake_get)
    monkeypatch.setattr(strava, "update_activity", fake_update)
    return p, aid, remote, calls


def _ride(aid, minutes, ext="111", hour=6):
    tue = _next_monday() + timedelta(days=1)
    with SessionLocal() as db:
        a = Activity(
            user_id=aid,
            source="strava",
            external_id=ext,
            sport="VirtualRide",
            start_time=datetime.combine(tue, time(hour)),
            duration_s=minutes * 60,
        )
        db.add(a)
        db.commit()
        return a.id


def _strava(aid, write=True):
    scope = "read,activity:read_all" + (",activity:write" if write else "")
    with SessionLocal() as db:
        c = Connection(
            user_id=aid,
            provider="strava",
            status="active",
            token_enc=encrypt_json({"access_token": "t", "scope": scope}),
            expires_at=utcnow() + timedelta(hours=1),
        )
        db.add(c)
        db.commit()
        return c.id


def test_preview_and_write_keep_the_athletes_text(athlete):
    p, aid, remote, calls = athlete
    act = _ride(aid, 60)
    url = f"/api/me/activities/{act}/strava-note"
    note = p.post(url + "?preview=true").json()["note"]
    assert note.splitlines() == [
        "🎯 Planned: Zwift / indoor · Tempo (1h 00m)",
        "✅ Goal met",
        "📋 Training plan by CoachQuest · testserver",
    ]
    r = p.post(url)  # Strava not linked
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_strava"
    _strava(aid, write=False)
    r = p.post(url)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "strava_write"
    assert calls == []


def test_write_then_update_without_duplicating(athlete):
    p, aid, remote, calls = athlete
    _strava(aid)
    act = _ride(aid, 30)
    url = f"/api/me/activities/{act}/strava-note"
    r = p.post(url).json()
    assert r["written"] and "⚠️ Partly done (30m of 1h 00m)" in r["note"]
    assert remote["description"].startswith("Great morning with the club\n\n🎯 Planned:")
    # A second ride that day: goal met now; the lines are replaced, not added again.
    _ride(aid, 40, ext="112", hour=17)
    p.post(url)
    assert remote["description"].count("🎯 Planned:") == 1 and "✅ Goal met" in remote["description"]
    assert remote["description"].startswith("Great morning with the club")
    tue = (_next_monday() + timedelta(days=1)).isoformat()
    listed = p.get(f"/api/athletes/me/activities?since={tue}&until={tue}").json()
    assert next(x for x in listed if x["id"] == act)["strava_note"]


def test_auto_after_sync_only_when_changed(athlete):
    p, aid, remote, calls = athlete
    cid = _strava(aid)
    _ride(aid, 60)
    with SessionLocal() as db:
        conn = db.get(Connection, cid)
        assert asyncio.run(strava_notes.auto(db, conn)) == 0  # mode is off
        db.get(User, aid).strava_notes = "auto"
        db.commit()
        assert asyncio.run(strava_notes.auto(db, conn)) == 1
        assert asyncio.run(strava_notes.auto(db, conn)) == 0  # nothing changed
    assert len(calls) == 1


def test_mode_in_profile_and_only_own_activities(athlete, make_user):
    p, aid, remote, calls = athlete
    assert p.get("/api/me/strava-notes").json() == {
        "mode": "off",
        "connected": False,
        "can_write": False,
        "host": "testserver",
    }
    assert p.patch("/api/me", json={"strava_notes": "auto"}).json()["strava_notes"] == "auto"
    assert p.patch("/api/me", json={"strava_notes": "always"}).status_code == 422
    act = _ride(aid, 60)
    other = make_user("b@example.com")
    assert other.post(f"/api/me/activities/{act}/strava-note").status_code == 404
    # Nothing planned that day (Monday is a rest day in the test plan).
    with SessionLocal() as db:
        a = db.get(Activity, act)
        a.start_time -= timedelta(days=1)
        db.commit()
    r = p.post(f"/api/me/activities/{act}/strava-note?preview=true")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_plan"


def test_authorize_asks_for_write_only_when_asked(make_user, monkeypatch):
    p = make_user("a@example.com")
    monkeypatch.setattr(strava, "app_for", lambda db, uid: strava.StravaApp("123", "s", False))
    assert "activity%3Awrite" not in p.post("/api/connections/strava/authorize").json()["url"]
    assert "activity%3Awrite" in p.post("/api/connections/strava/authorize?write=true").json()["url"]
