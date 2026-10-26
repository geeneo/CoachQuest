"""Disabling or pausing an account: nothing runs for it, coaches see it as paused, data stays."""

import asyncio

from test_sync import _athlete, _schedule, fake  # noqa: F401  (fixture)

from app import sync_engine
from app.db import AuthEvent, ExternalWorkout, SessionLocal, SyncJob, User

PW = "correct horse battery"


def test_admin_disables_with_reason(make_user):
    admin = make_user("admin@example.com", "Admin")
    ann = make_user("ann@example.com", "Ann")
    coach = make_user("coach@example.com", "Cobus")
    aid = ann.get("/api/auth/me").json()["id"]
    g = ann.post("/api/grants", json={"coach_email": "coach@example.com", "scopes": ["activities", "plans"]}).json()
    coach.post(f"/api/grants/{g['id']}/accept")
    admin.request("PATCH", f"/api/admin/users/{aid}", json={"is_active": False, "disabled_reason": "Unpaid"})
    row = next(u for u in admin.get("/api/admin/users").json() if u["id"] == aid)
    assert row["is_active"] is False and row["disabled_reason"] == "Unpaid" and row["disabled_at"]
    r = ann.post("/api/auth/login", json={"email": "ann@example.com", "password": PW})
    assert r.status_code == 403 and "paused" in r.json()["detail"]
    # The coach sees the athlete as paused, without access to the data.
    dash = coach.get("/api/coach/dashboard").json()
    assert dash[0]["disabled"] is True and dash[0]["flags"] == ["account paused"]
    assert coach.get("/api/athletes").json()[0]["disabled"] is True
    assert coach.get(f"/api/athletes/{aid}/activities").status_code == 404
    # Turned back on: everything as before.
    admin.request("PATCH", f"/api/admin/users/{aid}", json={"is_active": True})
    assert coach.get(f"/api/athletes/{aid}/activities").status_code == 200
    row = next(u for u in admin.get("/api/admin/users").json() if u["id"] == aid)
    assert row["disabled_reason"] is None


def test_last_admin_stays(make_user):
    admin = make_user("admin@example.com", "Admin")
    other = make_user("other@example.com", "Other")
    oid = other.get("/api/auth/me").json()["id"]
    admin.request("PATCH", f"/api/admin/users/{oid}", json={"is_admin": True})
    with SessionLocal() as db:
        db.query(User).filter_by(email="admin@example.com").one().is_active = False  # only "other" is left
        db.commit()
    assert other.post("/api/auth/pause", json={"confirm_email": "other@example.com"}).status_code == 400


def test_user_pauses_own_account(make_user):
    p = make_user("rider@example.com", "Rider")
    assert p.post("/api/auth/pause", json={"confirm_email": "wrong@example.com"}).status_code == 422
    assert p.post("/api/auth/pause", json={"confirm_email": "rider@example.com"}).json() == {"ok": True}
    with SessionLocal() as db:
        u = db.query(User).filter_by(email="rider@example.com").one()
        assert not u.is_active and u.disabled_by_self and u.disabled_reason == "Paused by themselves"
        assert db.query(AuthEvent).filter_by(event="paused_self").count() == 1
    assert p.get("/api/auth/me").status_code == 401  # signed out


def test_workouts_wait_while_disabled(make_user, fake):  # noqa: F811
    a, uid = _athlete(make_user, fake)
    _schedule(a, 1)
    asyncio.run(sync_engine.run_due())
    sent = len(fake.upserts())
    with SessionLocal() as db:
        user = db.get(User, uid)
        user.is_active = False
        for m in db.query(ExternalWorkout).filter_by(athlete_id=uid):
            m.content_hash = ""  # changed: has to go again
        db.commit()
        sync_engine.send_upcoming(db, user, "intervals_icu", "test")
    asyncio.run(sync_engine.run_due())
    assert len(fake.upserts()) == sent  # waits while disabled
    with SessionLocal() as db:
        assert db.query(SyncJob).filter_by(athlete_id=uid, status="queued").count() == 1
        db.get(User, uid).is_active = True
        db.commit()
    asyncio.run(sync_engine.run_due())
    assert len(fake.upserts()) == sent + 1
