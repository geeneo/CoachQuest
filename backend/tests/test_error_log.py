"""Error tracking (error_log.py): logged problems grouped for Admin → Errors, and the daily email."""

import asyncio
import logging
from datetime import timedelta

from test_mail import _configure, fake_smtp  # noqa: F401  (fixture)

from app import error_log
from app.db import Connection, ErrorGroup, SessionLocal, utcnow


def test_problems_grouped_and_resolved(make_user, fake_smtp):  # noqa: F811
    boss = make_user("admin@example.com", "Boss")
    _configure(boss)
    error_log.install()
    log = logging.getLogger("coachquest.test_sync")
    for uid in (3, 9):
        log.warning("Garmin sync failed for user %s: %s", uid, "timeout")
    logging.getLogger("coachquest.test_sync").info("all fine")  # not a problem
    logging.getLogger("someone.else").warning("their warning")  # not ours, not an error
    try:
        raise ValueError("boom")
    except ValueError:
        logging.getLogger("uvicorn.error").exception("Exception in ASGI application")
    data = boss.get("/api/admin/errors").json()
    by_msg = {g["message"]: g for g in data["groups"]}
    garmin = by_msg["Garmin sync failed for user 9: timeout"]
    assert garmin["count"] == 2 and garmin["level"] == "WARNING"  # one kind, counted twice
    crash = by_msg["Exception in ASGI application"]
    assert crash["level"] == "ERROR" and "ValueError: boom" in crash["traceback"]
    assert "their warning" not in by_msg and "all fine" not in by_msg

    # A stuck connection shows too, and both go in the daily email once.
    uid = boss.get("/api/auth/me").json()["id"]
    with SessionLocal() as db:
        db.add(Connection(user_id=uid, provider="garmin", token_enc="", status="error", last_error="401 Unauthorized"))
        db.commit()
    assert boss.get("/api/admin/errors").json()["connections"][0]["provider"] == "garmin"
    asyncio.run(error_log.daily())
    sent = [c for calls in fake_smtp for c in calls if c[0] == "send"]
    assert sent and sent[-1][2] == "CoachQuest: problems to look at"
    n = len(sent)
    with SessionLocal() as db:
        db.query(Connection).delete()
        db.commit()
    asyncio.run(error_log.daily())  # nothing new: no email
    assert len([c for calls in fake_smtp for c in calls if c[0] == "send"]) == n

    # Marked fixed: off the list until it happens again.
    assert boss.post(f"/api/admin/errors/{garmin['id']}/resolve").json()["open"] is False
    assert "Garmin sync failed for user 9: timeout" not in {
        g["message"] for g in boss.get("/api/admin/errors").json()["groups"]
    }
    with SessionLocal() as db:  # resolved a while ago, then it happens again
        g = db.get(ErrorGroup, garmin["id"])
        g.resolved_at = utcnow() - timedelta(minutes=5)
        db.commit()
    log.warning("Garmin sync failed for user %s: %s", 4, "timeout")
    again = {g["message"]: g for g in boss.get("/api/admin/errors").json()["groups"]}
    assert again["Garmin sync failed for user 4: timeout"]["count"] == 3
    # Only admins.
    rider = make_user("b@example.com")
    assert rider.get("/api/admin/errors").status_code == 403
