"""The evening preview by email: tomorrow's session and a verdict on training load (evening.py)."""

import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest

from app import evening, mailer
from app.db import Activity, Plan, SessionLocal, User

TZ = "Africa/Johannesburg"  # UTC+2


def _at(day: date, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=UTC) - timedelta(hours=2)


@pytest.fixture()
def athlete(make_user, monkeypatch):
    p = make_user("a@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    settings = {
        "daily": True,
        "weekly": False,
        "email": True,
        "daily_time": "05:30",
        "sleep_wait_min": 60,
        "preview": True,
        "preview_time": "20:00",
    }
    assert p.request("PUT", "/api/me/ai-settings", json=settings).status_code == 200
    today = date.today()
    with SessionLocal() as db:
        db.get(User, uid).timezone = TZ
        for i in range(1, 40):  # steady riding, then two big days
            db.add(
                Activity(
                    user_id=uid,
                    source="strava",
                    external_id=str(i),
                    name="Ride",
                    sport="Ride",
                    start_time=datetime.combine(today - timedelta(days=i), datetime.min.time()) + timedelta(hours=7),
                    duration_s=3600,
                    distance_m=30000,
                    elevation_m=100,
                    tss=250 if i <= 2 else 50,
                )
            )
        days = [
            {
                "date": (today + timedelta(days=i)).isoformat(),
                "weekday": "mon",
                "type": "Road" if i == 1 else "Rest",
                "description": "Stellies loop, steady" if i == 1 else "",
                "duration_min": 120 if i == 1 else 0,
                "intensity": ["Z2"] if i == 1 else [],
                "locked": False,
            }
            for i in range(7)
        ]
        db.add(
            Plan(
                athlete_id=uid,
                author_id=uid,
                title="P",
                content_md="",
                model="m",
                start_date=today,
                approval="approved",
                weeks=[{"start": today.isoformat(), "phase": "Build", "focus": "", "status": "draft", "days": days}],
            )
        )
        db.commit()
    sent = []

    async def fake_send(to, subject, text, html):
        sent.append((subject, text))

    monkeypatch.setattr(mailer, "send", fake_send)
    monkeypatch.setattr(mailer, "configured", lambda: True)
    return p, uid, today, sent


def test_preview_once_in_the_evening(athlete):
    p, uid, today, sent = athlete
    asyncio.run(evening.run(_at(today, "19:55")))
    assert sent == []
    asyncio.run(evening.run(_at(today, "20:02")))
    assert len(sent) == 1
    subject, text = sent[0]
    # Tired after two 250 TSS days: form well under -30 makes tomorrow EASY on load alone.
    assert subject == "Tomorrow: EASY · Road"
    assert "Road · 120 min · Z2: Stellies loop, steady" in text and "morning note (from 05:30)" in text
    asyncio.run(evening.run(_at(today, "20:30")))
    assert len(sent) == 1  # once a day
    # Changing the settings doesn't send it again the same evening, and the bookkeeping stays hidden.
    s = p.get("/api/athletes/me/coach").json()["ai_settings"]
    assert "preview_sent_for" not in s and s["preview_time"] == "20:00"
    p.request("PUT", "/api/me/ai-settings", json={**s, "preview_time": "20:15"})
    asyncio.run(evening.run(_at(today, "20:40")))
    assert len(sent) == 1


def test_no_preview_without_email_or_switched_off(athlete):
    p, uid, today, sent = athlete
    s = p.get("/api/athletes/me/coach").json()["ai_settings"]
    p.request("PUT", "/api/me/ai-settings", json={**s, "email": False})
    asyncio.run(evening.run(_at(today, "20:05")))
    p.request("PUT", "/api/me/ai-settings", json={**s, "preview": False})
    asyncio.run(evening.run(_at(today, "20:10")))
    assert sent == []
