"""Database size history, backup status and warnings for super admins (storage_watch.py)."""

import asyncio
import dataclasses
from datetime import UTC, date, datetime, timedelta

from app import mailer, storage_watch
from app.config import settings
from app.db import SessionLocal, StorageReading, User

GB = 1024**3


def _status(tmp_path, monkeypatch, text):
    monkeypatch.setattr(storage_watch, "settings", dataclasses.replace(settings, data_dir=str(tmp_path)))
    if text is not None:
        (tmp_path / "backup-status.txt").write_text(text)


def _reading(db, day, db_bytes, free):
    db.merge(StorageReading(day=day, database_bytes=db_bytes, disk_free=free, disk_total=100 * GB))
    db.commit()


def test_backup_status_and_its_warnings(client, tmp_path, monkeypatch):
    now = datetime(2026, 11, 1, 10, tzinfo=UTC)
    _status(tmp_path, monkeypatch, None)
    with SessionLocal() as db:
        assert storage_watch.backup_status() is None
        assert [w["code"] for w in storage_watch.warnings(db, now)] == ["no_backup"]
        (tmp_path / "backup-status.txt").write_text("at=2026-11-01T01:00:00Z\nstate=ok\nfile=b.db.gz\nsize=1234\n")
        b = storage_watch.backup_status()
        assert b["ok"] and b["size"] == 1234 and b["file"] == "b.db.gz"
        assert storage_watch.warnings(db, now) == []
        assert [w["code"] for w in storage_watch.warnings(db, now + timedelta(days=3))] == ["backup_old"]
        (tmp_path / "backup-status.txt").write_text("at=2026-11-01T01:00:00Z\nstate=failed\nerror=pg_dump failed\n")
        assert "pg_dump failed" in storage_watch.warnings(db, now)[0]["text"]


def test_disk_and_growth_warnings(client, tmp_path, monkeypatch):
    _status(tmp_path, monkeypatch, f"at={datetime.now(UTC):%Y-%m-%dT%H:%M:%SZ}\nstate=ok\n")
    today = date.today()
    with SessionLocal() as db:
        _reading(db, today - timedelta(days=8), 200 * 1024**2, 50 * GB)
        _reading(db, today, 210 * 1024**2, 50 * GB)
        assert storage_watch.warnings(db) == []
        _reading(db, today, 400 * 1024**2, int(1.5 * GB))
        assert [w["code"] for w in storage_watch.warnings(db)] == ["disk", "growth"]
        hist = storage_watch.history(db)
        assert [h["day"] for h in hist] == [(today - timedelta(days=8)).isoformat(), today.isoformat()]


def test_daily_job_emails_super_admins_once(tmp_path, monkeypatch, make_user):
    _status(tmp_path, monkeypatch, None)  # no backup seen: one warning
    make_user("boss@example.com")
    with SessionLocal() as db:
        u = db.query(User).filter_by(email="boss@example.com").one()
        u.is_admin = u.is_super_admin = True
        db.commit()
    sent = []

    async def fake_send(to, subject, text):
        sent.append((to, subject, text))

    monkeypatch.setattr(mailer, "send", fake_send)
    asyncio.run(storage_watch.daily())
    asyncio.run(storage_watch.daily())  # same day: not again
    assert len(sent) == 1 and sent[0][0] == "boss@example.com" and "No backup seen yet" in sent[0][2]
    with SessionLocal() as db:
        assert db.get(StorageReading, date.today()).warned == ["no_backup"]


def test_admin_storage_page(make_user, tmp_path, monkeypatch):
    _status(tmp_path, monkeypatch, None)
    admin = make_user("admin@example.com")
    with SessionLocal() as db:
        u = db.query(User).filter_by(email="admin@example.com").one()
        u.is_admin = u.is_super_admin = True
        db.commit()
    s = admin.get("/api/admin/storage").json()
    assert len(s["history"]) == 1 and s["backup"] is None and s["warnings"][0]["code"] == "no_backup"
    assert admin.get("/api/admin/storage/warnings").json()["warnings"][0]["code"] == "no_backup"
    other = make_user("b@example.com")
    assert other.get("/api/admin/storage/warnings").status_code == 403
