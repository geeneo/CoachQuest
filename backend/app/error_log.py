"""Error tracking without an outside service: what the app logs at WARNING (its own loggers) or ERROR
(anyone, unhandled request errors included) is kept, grouped by kind, for Admin → Errors.

A kind is the logger, the message before its values are filled in (so "Garmin sync failed for user 3" and
"... for user 9" are one kind) and the exception type. Each kind keeps a count, when it was first and last
seen, and the latest message and traceback. An admin marks a kind fixed; it opens again when it happens
after that. Once a day super admins get one email listing the kinds that are new or back since the last
email, and the connections that stopped syncing (Garmin, Strava, Intervals.icu).
"""

import hashlib
import logging
import threading
import traceback
from datetime import timedelta

from sqlalchemy import select

from . import mailer
from .db import Connection, ErrorGroup, SessionLocal, User, utcnow

log = logging.getLogger("coachquest.error_log")
OWN = "coachquest"  # our loggers: their warnings count too
QUIET = ("sqlalchemy", "httpx", "httpcore", "apscheduler", "coachquest.error_log")
_local = threading.local()


def fingerprint(record: logging.LogRecord) -> str:
    exc = record.exc_info[0].__name__ if record.exc_info and record.exc_info[0] else ""
    raw = f"{record.name}|{record.levelname}|{record.msg}|{exc}"
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


def store(record: logging.LogRecord) -> None:
    """Count a logged problem in its group (a new group the first time)."""
    try:
        message = record.getMessage()
    except Exception:  # a broken format string: keep the template
        message = str(record.msg)
    trace = "".join(traceback.format_exception(*record.exc_info))[-6000:] if record.exc_info else ""
    fp = fingerprint(record)
    with SessionLocal() as db:
        g = db.scalar(select(ErrorGroup).where(ErrorGroup.fingerprint == fp))
        if g is None:
            g = ErrorGroup(fingerprint=fp, level=record.levelname, logger=record.name[:100], count=0)
            db.add(g)
        now = utcnow()
        g.count += 1
        g.message = message[:1000]
        g.traceback = trace or g.traceback or ""
        g.last_seen = now
        db.commit()


class Handler(logging.Handler):
    """Logging handler: WARNING and up from our loggers, ERROR and up from everyone else."""

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(_local, "busy", False):
            return  # a problem while storing a problem: don't loop
        own = record.name.startswith(OWN)
        if record.levelno < (logging.WARNING if own else logging.ERROR):
            return
        if record.name.startswith(QUIET):
            return
        _local.busy = True
        try:
            store(record)
        except Exception:  # the database is down, say: the log line itself is still written
            pass
        finally:
            _local.busy = False


def install() -> None:
    root = logging.getLogger()
    if not any(isinstance(h, Handler) for h in root.handlers):
        root.addHandler(Handler(level=logging.WARNING))


def is_open(g: ErrorGroup) -> bool:
    return g.resolved_at is None or g.last_seen > g.resolved_at


def group_out(g: ErrorGroup) -> dict:
    return {
        "id": g.id,
        "level": g.level,
        "logger": g.logger,
        "message": g.message,
        "traceback": g.traceback,
        "count": g.count,
        "first_seen": g.first_seen,
        "last_seen": g.last_seen,
        "resolved_at": g.resolved_at,
        "open": is_open(g),
    }


def failed_connections(db) -> list[dict]:
    """Connections whose last sync failed, or that haven't synced for two days."""
    stale = utcnow() - timedelta(days=2)
    out = []
    rows = db.execute(select(Connection, User).join(User, User.id == Connection.user_id).where(User.is_active)).all()
    for c, u in rows:
        if c.provider not in ("strava", "garmin", "intervals_icu"):
            continue
        if c.status == "error" or (c.last_sync_at is not None and c.last_sync_at < stale):
            why = (c.last_error or "error")[:200] if c.status == "error" else f"no sync since {c.last_sync_at:%d %b}"
            out.append({"user": u.display_name, "provider": c.provider, "why": why})
    return out


async def daily() -> None:
    """Scheduler job: one email to super admins with what's new or back since the last email."""
    with SessionLocal() as db:
        groups = db.scalars(select(ErrorGroup)).all()
        fresh = [g for g in groups if is_open(g) and (g.emailed_at is None or g.last_seen > g.emailed_at)]
        conns = failed_connections(db)
        if not fresh and not conns:
            return
        lines = ["CoachQuest logged problems since the last email (Admin → Errors):", ""]
        for g in sorted(fresh, key=lambda g: -g.count)[:20]:
            lines.append(f"- {g.level} ×{g.count}, last {g.last_seen:%d %b %H:%M} UTC: {g.message[:200]}")
        if conns:
            lines += ["", "Connections that aren't syncing:"]
            lines += [f"- {c['user']}: {c['provider']} ({c['why']})" for c in conns[:30]]
        body = "\n".join(lines)
        if mailer.configured():
            for a in db.scalars(select(User).where(User.is_super_admin, User.is_active)):
                try:
                    await mailer.send(a.email, "CoachQuest: problems to look at", body)
                except mailer.MailError as exc:
                    log.info("Problems email to %s not sent: %s", a.id, exc)  # info: not a new problem
        now = utcnow()
        for g in fresh:
            g.emailed_at = now
        db.commit()
