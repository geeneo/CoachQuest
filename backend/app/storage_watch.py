"""Watching the database and the disk (Admin → Storage).

Once a day (and when Admin → Storage is opened and today has no reading yet) CoachQuest records the
database size and the free disk. Super admins are warned, on the admin pages and by email at most once
a day per warning, when:

- free disk drops below `storage_warn_free_gb` (Admin → Settings, default 2 GB);
- the database grows fast: more than half again in a week, and by more than 100 MB;
- the last backup is more than two days old, or the last one failed. backup.sh (menu.sh option 7, and
  the nightly job from option 10) writes DATA_DIR/backup-status.txt; without that file CoachQuest
  only says no backup has been seen.
"""

import logging
import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy import text as sql
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm.attributes import flag_modified

from . import mailer, runtime
from .config import settings
from .db import SessionLocal, StorageReading, User

log = logging.getLogger("coachquest.storage")

HISTORY_DAYS = 90
GROWTH_SHARE = 0.5  # half again in a week ...
GROWTH_BYTES = 100 * 1024**2  # ... and at least this much
BACKUP_MAX_AGE = timedelta(days=2)
GB = 1024**3


def database_files(db: DbSession) -> dict[str, int]:
    """The database's files and their sizes (SQLite), or the Postgres database's size."""
    files = {}
    url = make_url(settings.db_url)
    if url.get_backend_name() == "sqlite" and url.database:
        for suffix in ("", "-wal", "-shm"):
            path = Path(url.database + suffix)
            if path.exists():
                files[path.name] = path.stat().st_size
    elif url.get_backend_name() == "postgresql":
        name = db.scalar(sql("SELECT current_database()"))
        files[f"Postgres database {name}"] = db.scalar(sql("SELECT pg_database_size(current_database())"))
    return files


def disk() -> dict:
    d = shutil.disk_usage(settings.data_dir if Path(settings.data_dir).exists() else ".")
    return {"total": d.total, "used": d.used, "free": d.free, "path": settings.data_dir}


def record(db: DbSession, today: date | None = None) -> StorageReading:
    """Today's reading (taken now if there's none yet, else updated)."""
    today = today or date.today()
    d = disk()
    r = db.get(StorageReading, today) or StorageReading(day=today)
    r.database_bytes = sum(database_files(db).values())
    r.disk_free, r.disk_total = d["free"], d["total"]
    db.add(r)
    db.commit()
    return r


def history(db: DbSession, today: date | None = None) -> list[dict]:
    today = today or date.today()
    rows = db.scalars(
        select(StorageReading)
        .where(StorageReading.day > today - timedelta(days=HISTORY_DAYS))
        .order_by(StorageReading.day)
    ).all()
    return [
        {
            "day": r.day.isoformat(),
            "database_bytes": r.database_bytes,
            "disk_free": r.disk_free,
            "disk_total": r.disk_total,
        }
        for r in rows
    ]


def backup_status() -> dict | None:
    """What backup.sh wrote last: {at, ok, file, size, error}, or None when it never ran (here)."""
    path = Path(settings.data_dir) / "backup-status.txt"
    try:
        fields = dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)
    except OSError:
        return None
    try:
        at = datetime.fromisoformat(fields.get("at", "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    return {
        "at": at,
        "ok": fields.get("state") == "ok",
        "file": fields.get("file", ""),
        "size": int(fields["size"]) if fields.get("size", "").isdigit() else None,
        "error": fields.get("error", ""),
    }


def warnings(db: DbSession, now: datetime | None = None) -> list[dict]:
    """What a super admin should know about: [{code, text}]."""
    now = now or datetime.now(UTC)
    out = []
    last = db.scalar(select(StorageReading).order_by(StorageReading.day.desc()).limit(1))
    limit_gb = float(runtime.get("storage_warn_free_gb") or 2)
    if last is not None and last.disk_free < limit_gb * GB:
        out.append(
            {
                "code": "disk",
                "text": f"Only {last.disk_free / GB:.1f} GB free on the server's disk (warning below {limit_gb:g} GB). "
                "Free up space or add disk before the database or backups fill it.",
            }
        )
    if last is not None:
        week = db.scalar(
            select(StorageReading)
            .where(StorageReading.day <= last.day - timedelta(days=7))
            .order_by(StorageReading.day.desc())
            .limit(1)
        )
        if week is not None and week.database_bytes:
            grew = last.database_bytes - week.database_bytes
            if grew > GROWTH_BYTES and grew > GROWTH_SHARE * week.database_bytes:
                out.append(
                    {
                        "code": "growth",
                        "text": f"The database grew from {week.database_bytes / 1024**2:,.0f} MB to "
                        f"{last.database_bytes / 1024**2:,.0f} MB in a week. Check Admin → Storage for the table "
                        "that grows.",
                    }
                )
    b = backup_status()
    if b is None:
        out.append(
            {
                "code": "no_backup",
                "text": "No backup seen yet. Switch on the nightly backup on the server (bash menu.sh → option 10), "
                "or make one now (option 7).",
            }
        )
    elif not b["ok"]:
        out.append({"code": "backup_failed", "text": f"The last backup failed ({b['at']:%d %b %H:%M}): {b['error']}"})
    elif now - b["at"] > BACKUP_MAX_AGE:
        days = (now - b["at"]).days
        out.append(
            {
                "code": "backup_old",
                "text": f"The last backup is {days} days old. Check the nightly backup on the server "
                "(bash menu.sh → option 10).",
            }
        )
    return out


async def daily() -> None:
    """The scheduled job: today's reading, then email super admins new warnings (once a day each)."""
    with SessionLocal() as db:
        reading = record(db)
        found = warnings(db)
        new = [w for w in found if w["code"] not in (reading.warned or [])]
        if not new:
            return
        admins = db.scalars(select(User).where(User.is_super_admin, User.is_active)).all()
        body = "CoachQuest needs a look (Admin → Storage):\n\n" + "\n\n".join(f"- {w['text']}" for w in new)
        for a in admins:
            try:
                await mailer.send(a.email, "CoachQuest: storage or backup needs attention", body)
            except mailer.MailError as exc:
                log.warning("Storage warning to %s not sent: %s", a.id, exc)
        reading.warned = sorted({*(reading.warned or []), *(w["code"] for w in new)})
        flag_modified(reading, "warned")
        db.commit()
