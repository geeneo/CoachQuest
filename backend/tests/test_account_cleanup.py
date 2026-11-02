"""Deleting unused accounts after two warnings (account_cleanup.py)."""

import asyncio
from datetime import timedelta

from app import account_cleanup, mailer, runtime
from app.db import Session as LoginSession
from app.db import SessionLocal, User, utcnow

DAY = timedelta(days=1)


def _setup(monkeypatch, on="on", months="12", mail_ok=True):
    real = runtime.get
    monkeypatch.setattr(
        runtime,
        "get",
        lambda k: on if k == "account_cleanup" else months if k == "account_cleanup_months" else real(k),
    )
    monkeypatch.setattr(mailer, "configured", lambda: True)
    sent = []

    async def fake_send(to, subject, text):
        if not mail_ok:
            raise mailer.MailError("down")
        sent.append((to, subject, text))

    monkeypatch.setattr(mailer, "send", fake_send)
    monkeypatch.setattr(account_cleanup.accounts, "revoke_links", _no_revoke)
    return sent


async def _no_revoke(db, user):
    return []


def _last_visit(email, when):
    with SessionLocal() as db:
        u = db.query(User).filter_by(email=email).one()
        for s in db.query(LoginSession).filter_by(user_id=u.id):
            s.last_seen_at = when
        u.created_at = when - timedelta(days=30)
        db.commit()
        return u.id


def _exists(uid):
    with SessionLocal() as db:
        return db.get(User, uid) is not None


def test_warn_twice_then_delete(make_user, monkeypatch):
    sent = _setup(monkeypatch)
    make_user("gone@example.com", "Gone")
    start = utcnow()
    last = start - timedelta(days=round(12 * 30.44)) + 25 * DAY  # due in 25 days
    uid = _last_visit("gone@example.com", last)
    asyncio.run(account_cleanup.run(start))
    assert len(sent) == 1 and "will be deleted if it isn't used" in sent[0][1]
    due = (start + 30 * DAY).date()  # the first warning promises at least 30 days
    assert f"{due:%d %B %Y}" in sent[0][2]
    asyncio.run(account_cleanup.run(start + DAY))  # nothing new the next day
    assert len(sent) == 1
    asyncio.run(account_cleanup.run(start + 23 * DAY))  # a week before: the final warning
    assert len(sent) == 2 and sent[1][1].startswith("Final reminder")
    asyncio.run(account_cleanup.run(start + 29 * DAY))  # not yet
    assert _exists(uid)
    asyncio.run(account_cleanup.run(start + 30 * DAY))
    assert not _exists(uid) and sent[-1][1] == "Your CoachQuest account has been deleted"


def test_signing_in_keeps_it(make_user, monkeypatch):
    sent = _setup(monkeypatch)
    make_user("back@example.com")
    start = utcnow()
    uid = _last_visit("back@example.com", start - timedelta(days=380))
    asyncio.run(account_cleanup.run(start))
    assert len(sent) == 1
    _last_visit("back@example.com", start + 2 * DAY)  # they signed in
    for d in (10, 25, 31, 40):
        asyncio.run(account_cleanup.run(start + d * DAY))
    assert _exists(uid) and len(sent) == 1


def test_never_without_warnings_and_never_admins(make_user, monkeypatch):
    _setup(monkeypatch, mail_ok=False)
    make_user("quiet@example.com")
    boss = make_user("boss@example.com")
    keep = make_user("keep@example.com")
    start = utcnow()
    ids = [
        _last_visit(e, start - timedelta(days=800))
        for e in ("quiet@example.com", "boss@example.com", "keep@example.com")
    ]
    with SessionLocal() as db:
        db.get(User, ids[1]).is_admin = True
        db.get(User, ids[2]).keep_account = True
        db.commit()
    for d in range(0, 60, 5):
        asyncio.run(account_cleanup.run(start + d * DAY))
    assert all(_exists(i) for i in ids)  # mail down: no warnings, so nothing deleted
    _setup(monkeypatch, on="off")
    assert asyncio.run(account_cleanup.run(start)) == {"warned": 0, "final": 0, "deleted": 0}
    assert boss and keep


def test_admin_sees_the_date_and_can_keep(make_user, monkeypatch):
    _setup(monkeypatch)
    admin = make_user("admin@example.com")
    with SessionLocal() as db:
        a = db.query(User).filter_by(email="admin@example.com").one()
        a.is_admin = a.is_super_admin = True
        db.commit()
    make_user("old@example.com")
    uid = _last_visit("old@example.com", utcnow() - timedelta(days=360))
    row = next(u for u in admin.get("/api/admin/users").json() if u["id"] == uid)
    assert row["deletion"]["delete_on"] and any("if unused" in f for f in row["flags"])
    admin.request("PATCH", f"/api/admin/users/{uid}", json={"keep_account": True})
    row = next(u for u in admin.get("/api/admin/users").json() if u["id"] == uid)
    assert row["keep_account"] is True and row["deletion"] is None
