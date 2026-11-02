"""'We haven't seen you' emails (inactivity.py)."""

import asyncio
from datetime import date, datetime, timedelta

from app import inactivity, mailer, runtime
from app.db import Activity, Race, SessionLocal, User, utcnow
from app.db import Session as LoginSession


def _setup(monkeypatch, on="on", days="30"):
    real = runtime.get
    monkeypatch.setattr(
        runtime, "get", lambda k: on if k == "inactivity_email" else days if k == "inactivity_days" else real(k)
    )
    monkeypatch.setattr(mailer, "configured", lambda: True)
    sent = []

    async def fake_send(to, subject, text):
        sent.append((to, subject, text))

    monkeypatch.setattr(mailer, "send", fake_send)
    return sent


def _away(email, days_ago):
    """Make the user's sessions (their last visit) `days_ago` old."""
    with SessionLocal() as db:
        u = db.query(User).filter_by(email=email).one()
        for s in db.query(LoginSession).filter_by(user_id=u.id):
            s.last_seen_at = utcnow() - timedelta(days=days_ago)
        u.created_at = utcnow() - timedelta(days=400)
        db.commit()
        return u.id


def test_one_email_per_absence(make_user, monkeypatch):
    sent = _setup(monkeypatch)
    make_user("away@example.com", "Ann")
    make_user("here@example.com", "Bob")
    uid = _away("away@example.com", 40)
    _away("here@example.com", 3)
    with SessionLocal() as db:
        db.add(
            Activity(
                user_id=uid,
                source="strava",
                external_id="1",
                name="Ride",
                sport="Ride",
                start_time=datetime.now() - timedelta(days=2),
            )
        )
        db.add(Race(user_id=uid, code="dc", name="Double Century", target_date=date.today() + timedelta(days=19)))
        db.commit()
    asyncio.run(inactivity.run())
    assert [s[0] for s in sent] == ["away@example.com"]
    text = sent[0][2]
    assert "40 days ago" in text and "1 activity" in text and "Double Century: 19 days to go" in text
    assert 'Untick "Email me a reminder" under Profile' in text
    asyncio.run(inactivity.run())  # still away: not again
    assert len(sent) == 1
    # Back, and away again: a new email.
    with SessionLocal() as db:
        db.get(User, uid).inactivity_emailed_at = utcnow() - timedelta(days=45)
        db.commit()
    asyncio.run(inactivity.run())
    assert len(sent) == 2


def test_switches(make_user, monkeypatch, client):
    sent = _setup(monkeypatch)
    p = make_user("a@example.com", "Ann")
    make_user("b@example.com", "Bob")
    make_user("c@example.com", "Cid")
    for e in ("a@example.com", "b@example.com", "c@example.com"):
        _away(e, 60)
    assert p.request("PATCH", "/api/me", json={"notify_inactivity": False}).status_code == 200
    assert p.get("/api/auth/me").json()["notify_inactivity"] is False
    with SessionLocal() as db:
        db.query(User).filter_by(email="b@example.com").one().inactivity_emails = False  # the admin's switch
        db.commit()
    asyncio.run(inactivity.run())
    assert [s[0] for s in sent] == ["c@example.com"]
    _setup(monkeypatch, on="off")
    with SessionLocal() as db:
        db.query(User).filter_by(email="c@example.com").one().inactivity_emailed_at = None
        db.commit()
    assert asyncio.run(inactivity.run()) == 0
