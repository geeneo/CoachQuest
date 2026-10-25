"""Import older data in the background, one small step at a time.

Progress lives in Connection.backfill, so a run survives restarts:

    {"status": "running" | "waiting" | "done" | "cancelled" | "error",
     "target": "2024-01-01",           # import back to this day
     "cursor": "2025-04-28T06:12:00",  # everything newer than this is done
     "stored": 312, "resume_at": "...", "message": "...", "started_at": "..."}

Strava pauses when its rate-limit headers get close to the limit and resumes
from the scheduler. Garmin goes back two weeks per step with a short pause in
between.
"""

import asyncio
import logging
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from . import sync_options
from .db import Activity, Connection, SessionLocal, WellnessDay, utcnow
from .providers import garmin, strava

log = logging.getLogger("coachquest.backfill")

EARLIEST = date(2009, 1, 1)  # Strava's launch; nothing older to fetch
GARMIN_PAUSE_S = 3
_running: set[int] = set()


def state(conn: Connection) -> dict | None:
    return dict(conn.backfill) if conn.backfill else None


def _save(db: DbSession, conn: Connection, **changes) -> None:
    conn.backfill = {**(conn.backfill or {}), **changes}
    db.commit()


def _oldest_imported(db: DbSession, conn: Connection) -> datetime:
    """Where to start going back from: the oldest data already imported from this provider."""
    oldest = db.scalar(
        select(func.min(Activity.start_time)).where(Activity.user_id == conn.user_id, Activity.source == conn.provider)
    )
    if conn.provider == "garmin":
        day = db.scalar(select(func.min(WellnessDay.day)).where(WellnessDay.user_id == conn.user_id))
        if day:
            as_dt = datetime.combine(day, datetime.min.time())
            oldest = min(oldest, as_dt) if oldest else as_dt
    return oldest or utcnow()


def start(db: DbSession, conn: Connection, target: date) -> dict:
    if target < EARLIEST or target >= date.today():
        raise ValueError(f"Pick a date between {EARLIEST:%Y-%m-%d} and yesterday.")
    if not any(sync_options.options(conn).get(k) for k in ("activities", "wellness")):
        raise ValueError("Turn on at least one data type for this connection first.")
    cursor = _oldest_imported(db, conn)
    if cursor.date() <= target:
        raise ValueError(f"Data from {target:%Y-%m-%d} onwards is already imported.")
    conn.backfill = {
        "status": "running",
        "target": target.isoformat(),
        "cursor": cursor.isoformat(),
        "stored": 0,
        "resume_at": None,
        "message": None,
        "started_at": utcnow().isoformat(),
    }
    db.commit()
    return state(conn)


def cancel(db: DbSession, conn: Connection) -> None:
    if conn.backfill and conn.backfill.get("status") in ("running", "waiting"):
        _save(db, conn, status="cancelled", resume_at=None)


async def run(conn_id: int) -> None:
    """Work until done, paused or cancelled. Safe to call again; only one run per connection."""
    if conn_id in _running:
        return
    _running.add(conn_id)
    db = SessionLocal()
    try:
        while True:
            conn = db.get(Connection, conn_id)
            db.refresh(conn)
            bf = conn.backfill if conn else None
            # "waiting" runs continue only after resume_due() marks them running again.
            if not bf or bf.get("status") != "running":
                return
            target = date.fromisoformat(bf["target"])
            cursor = datetime.fromisoformat(bf["cursor"])
            if cursor.date() <= target:
                _save(db, conn, status="done", resume_at=None, message=None)
                return
            try:
                if conn.provider == "strava":
                    new_cursor, stored, pause = await strava.backfill_step(
                        db, conn, datetime.combine(target, datetime.min.time()), cursor
                    )
                else:
                    new_day, stored = await garmin.backfill_step(db, conn, target, cursor.date())
                    new_cursor, pause = datetime.combine(new_day, datetime.min.time()), None
            except Exception as exc:
                log.warning("Backfill of connection %s failed: %r", conn_id, exc)
                _save(db, conn, status="error", message=f"{type(exc).__name__}: {exc}"[:300])
                return
            _save(db, conn, cursor=new_cursor.isoformat(), stored=bf.get("stored", 0) + stored)
            if new_cursor.date() <= target or (conn.provider == "strava" and stored == 0 and not pause):
                _save(db, conn, status="done", cursor=datetime.combine(target, datetime.min.time()).isoformat())
                return
            if pause:
                _save(
                    db,
                    conn,
                    status="waiting",
                    resume_at=pause.isoformat(),
                    message="Paused to stay inside Strava's rate limit; resumes automatically.",
                )
                return
            if conn.provider == "garmin":
                await asyncio.sleep(GARMIN_PAUSE_S)
    finally:
        _running.discard(conn_id)
        db.close()


async def resume_due() -> None:
    """Scheduler job: continue runs that were paused or interrupted by a restart."""
    db = SessionLocal()
    try:
        conns = [c for c in db.scalars(select(Connection)).all() if c.backfill]
        due = [
            c.id
            for c in conns
            if c.backfill.get("status") == "running"
            or (
                c.backfill.get("status") == "waiting"
                and (not c.backfill.get("resume_at") or datetime.fromisoformat(c.backfill["resume_at"]) <= utcnow())
            )
        ]
        for c in conns:
            if c.id in due and c.backfill.get("status") == "waiting":
                _save(db, c, status="running", resume_at=None, message=None)
    finally:
        db.close()
    for conn_id in due:
        await run(conn_id)
