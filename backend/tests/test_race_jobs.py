"""After race days, in the background (race_jobs.py): the review's Strava fetches done ahead, and the
day-after reminder to write the post-race update."""

import asyncio
from datetime import timedelta

import pytest

from app import mailer, race_jobs
from app.db import Activity, Connection, Race, SessionLocal, User
from app.providers import strava
from tests.test_race_review import RACE_DAY, _ride, racer  # noqa: F401 (the fixture)

DAY_AFTER = RACE_DAY + timedelta(days=1)


@pytest.fixture()
def strava_and_mail(monkeypatch):
    calls, sent = [], []

    async def fake_detail(db, conn, ext):
        calls.append(ext)
        return {"segment_efforts": [{"segment": {"id": 1, "name": "Climb"}, "elapsed_time": 600}]}

    async def fake_send(to, subject, text):
        sent.append((to, subject, text))

    monkeypatch.setattr(strava, "activity_detail", fake_detail)
    monkeypatch.setattr(mailer, "send", fake_send)
    monkeypatch.setattr(mailer, "configured", lambda: True)
    return calls, sent


def _setup(uid):
    with SessionLocal() as db:
        db.add(_ride(uid, "race", RACE_DAY))
        db.add(Connection(user_id=uid, provider="strava", token_enc="x", status="active"))
        db.commit()


def test_fetches_ahead_and_reminds_once(racer, strava_and_mail):  # noqa: F811
    p, uid, rid = racer
    calls, sent = strava_and_mail
    _setup(uid)
    out = asyncio.run(race_jobs.run(DAY_AFTER))
    assert out == {"fetched": 1, "reminded": 1} and calls == ["race"]
    with SessionLocal() as db:
        assert db.query(Activity).filter_by(external_id="race").one().detail["segments"][0]["id"] == 1
        assert db.get(Race, rid).reminded_at is not None
    to, subject, text = sent[0]
    assert to == "rider@example.com" and "Knysna Classic" in subject and f"/races/{rid}/review" in text
    # Again later that day: nothing fetched twice, no second email.
    assert asyncio.run(race_jobs.run(DAY_AFTER)) == {"fetched": 1, "reminded": 0}
    assert calls == ["race"] and len(sent) == 1


def test_no_reminder_when_written_switched_off_or_too_late(racer, strava_and_mail):  # noqa: F811
    p, uid, rid = racer
    calls, sent = strava_and_mail
    _setup(uid)
    p.request("PUT", f"/api/races/{rid}/result", json={"official_time": "2:10"})
    asyncio.run(race_jobs.run(DAY_AFTER))
    assert sent == []  # already written
    p.request("PUT", f"/api/races/{rid}/result", json={"official_time": ""})
    with SessionLocal() as db:
        db.get(User, uid).notify_races = False
        db.commit()
    asyncio.run(race_jobs.run(DAY_AFTER))
    assert sent == []  # switched off in Profile
    with SessionLocal() as db:
        db.get(User, uid).notify_races = True
        db.commit()
    asyncio.run(race_jobs.run(DAY_AFTER + timedelta(days=2)))
    assert sent == []  # not the day after any more (still fetched)
    asyncio.run(race_jobs.run(RACE_DAY + timedelta(days=10)))
    assert calls == ["race"]  # long past: left alone


def test_profile_switch(racer):  # noqa: F811
    p, uid, rid = racer
    assert p.get("/api/auth/me").json()["notify_races"] is True
    r = p.request("PATCH", "/api/me", json={"notify_races": False})
    assert r.status_code == 200, r.text
    assert p.get("/api/auth/me").json()["notify_races"] is False
