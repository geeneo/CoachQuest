"""The morning note at the athlete's own time, once last night's sleep is in (morning.py)."""

import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest

from app import assessments, mailer, morning
from app.db import Activity, Assessment, SessionLocal, User, WellnessDay

TZ = "Africa/Johannesburg"  # UTC+2


def _at(day: date, hhmm: str) -> datetime:
    """A Johannesburg local time as UTC."""
    h, m = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=UTC) - timedelta(hours=2)


@pytest.fixture()
def athlete(make_user, monkeypatch):
    p = make_user("a@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    r = p.request(
        "PUT",
        "/api/me/ai-settings",
        json={"daily": True, "weekly": False, "email": True, "daily_time": "05:30", "sleep_wait_min": 60},
    )
    assert r.status_code == 200 and r.json()["daily_time"] == "05:30"
    today = date.today()
    with SessionLocal() as db:
        db.get(User, uid).timezone = TZ
        for i in range(1, 31):
            db.add(WellnessDay(user_id=uid, day=today - timedelta(days=i), hrv_ms=60, resting_hr=50, sleep_s=27000))
        db.add(
            Activity(
                user_id=uid,
                source="strava",
                external_id="1",
                name="Ride",
                sport="Ride",
                start_time=datetime.now() - timedelta(days=1),
                duration_s=3600,
                distance_m=30000,
                elevation_m=100,
                tss=60,
            )
        )
        db.commit()
    sent, calls = [], []

    async def fake_ask(db, viewer, ath, system, content, output_format=None, kind=None):
        calls.append(content)
        return "**Go.**", "claude-test"

    async def fake_send(to, subject, text, html):
        sent.append(subject)

    monkeypatch.setattr(assessments, "ask_claude", fake_ask)
    monkeypatch.setattr(mailer, "send", fake_send)
    monkeypatch.setattr(mailer, "configured", lambda: True)
    morning._last_sync.clear()
    return uid, today, sent, calls


def _sleep(uid, day, hrv=60):
    with SessionLocal() as db:
        db.add(WellnessDay(user_id=uid, day=day, hrv_ms=hrv, resting_hr=50, sleep_s=27000))
        db.commit()


def test_waits_for_the_time_then_the_sleep(athlete):
    uid, today, sent, calls = athlete
    asyncio.run(morning.run(_at(today, "05:15")))  # before their time
    asyncio.run(morning.run(_at(today, "05:35")))  # their time, no sleep data yet: waits
    assert sent == [] and calls == []
    _sleep(uid, today)
    asyncio.run(morning.run(_at(today, "05:50")))  # the sleep came in: sent
    assert sent == ["Today: GO"] and len(calls) == 1
    asyncio.run(morning.run(_at(today, "06:30")))  # once a day
    assert len(calls) == 1
    with SessionLocal() as db:
        a = db.query(Assessment).one()
        assert a.period_start == today and a.author_id is None and a.facts["numbers"]["last_night"] == today.isoformat()


def test_sends_without_sleep_after_the_wait_then_updates(athlete):
    uid, today, sent, calls = athlete
    asyncio.run(morning.run(_at(today, "06:00")))
    assert sent == []
    asyncio.run(morning.run(_at(today, "06:31")))  # 05:30 + 60 min wait passed: training load alone
    assert sent == ["Today: GO"]
    # Last night's data arrives later, with HRV well down: the verdict changes, so a short update email.
    _sleep(uid, today, hrv=40)
    asyncio.run(morning.run(_at(today, "07:10")))
    assert sent[-1] == "Update: today is REST, not GO" and len(calls) == 2
    asyncio.run(morning.run(_at(today, "07:40")))
    assert len(calls) == 2


def test_late_data_with_the_same_verdict_sends_nothing_more(athlete):
    uid, today, sent, calls = athlete
    asyncio.run(morning.run(_at(today, "06:31")))
    _sleep(uid, today)
    asyncio.run(morning.run(_at(today, "07:00")))
    assert sent == ["Today: GO"] and len(calls) == 2  # the note is rewritten in the app, no second email


def test_settings_validated(athlete, make_user):
    p = make_user("b@example.com")
    bad = {"daily": True, "weekly": False, "email": False, "daily_time": "25:00"}
    assert p.request("PUT", "/api/me/ai-settings", json=bad).status_code == 422
    assert p.get("/api/athletes/me/coach").json()["ai_settings"]["daily_time"] == "06:30"
