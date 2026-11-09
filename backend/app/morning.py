"""The morning readiness note at the time each athlete chooses, once last night's sleep is in.

Each athlete picks a time on the AI coach tab ("Send my morning note at", their own time zone; default
06:30) and how long to wait for their sleep data. Every few minutes, for each athlete with the daily note on:

1. Before their time: nothing.
2. At their time (and every SYNC_EVERY while waiting): sync their Garmin now, not at the twice-daily batch,
   as last night's sleep and HRV only reach Garmin Connect once the watch has synced.
3. Last night's sleep or HRV is in (today's wellness row): write the note and email it.
4. Still not in after their wait: write it anyway on training load alone (the note says so).
5. After that, until UPDATE_UNTIL: when the note went out without last night's data and the data arrives,
   write it again; a short email follows only when the verdict changed.
"""

import logging
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import assessments, localtime, mailer
from .coach import CoachError
from .db import Assessment, Connection, SessionLocal, User, WellnessDay

log = logging.getLogger("coachquest.morning")

DEFAULT_TIME = "06:30"
DEFAULT_WAIT_MIN = 90
MAX_WAIT_MIN = 240
SYNC_EVERY = timedelta(minutes=30)  # on-demand Garmin syncs while waiting for the sleep data
UPDATE_UNTIL = time(12, 0)  # local: after this, a note written without last night's data stays as it is
_last_sync: dict[int, datetime] = {}  # athlete id -> last on-demand Garmin sync (UTC)


def settings_of(user: User) -> tuple[time, int]:
    """(local send time, minutes to wait for the sleep data)."""
    s = user.ai_settings or {}
    try:
        at = time.fromisoformat(s.get("daily_time") or DEFAULT_TIME)
    except ValueError:
        at = time.fromisoformat(DEFAULT_TIME)
    wait = s.get("sleep_wait_min")
    wait = DEFAULT_WAIT_MIN if wait is None else max(0, min(int(wait), MAX_WAIT_MIN))
    return at, wait


def slept(db: DbSession, user_id: int, today: date) -> bool:
    """Last night's sleep or HRV is in: Garmin files the night that ended this morning under today."""
    row = db.scalar(select(WellnessDay).where(WellnessDay.user_id == user_id, WellnessDay.day == today))
    return row is not None and (row.sleep_s is not None or row.hrv_ms is not None)


def todays_note(db: DbSession, user_id: int, today: date) -> Assessment | None:
    """The newest scheduled readiness note for today (author None: written by the scheduler)."""
    return db.scalar(
        select(Assessment)
        .where(
            Assessment.athlete_id == user_id,
            Assessment.kind == "daily",
            Assessment.period_start == today,
            Assessment.author_id.is_(None),
        )
        .order_by(Assessment.created_at.desc())
    )


def without_last_night(a: Assessment, today: date) -> bool:
    return ((a.facts or {}).get("numbers") or {}).get("last_night") != today.isoformat()


def step(db: DbSession, user: User, now: datetime) -> str:
    """What to do for one athlete now: wait, sync, send, update, or nothing ("done")."""
    local = now.astimezone(localtime.zone(user.timezone))
    today, at, (send_at, wait) = local.date(), local.time(), settings_of(user)
    if at < send_at:
        return "wait"
    note = todays_note(db, user.id, today)
    has_sleep = slept(db, user.id, today)
    if note is not None:
        if has_sleep and without_last_night(note, today) and at < UPDATE_UNTIL:
            return "update"
        if not has_sleep and without_last_night(note, today) and at < UPDATE_UNTIL:
            return "sync"
        return "done"
    if has_sleep:
        return "send"
    deadline = datetime.combine(today, send_at) + timedelta(minutes=wait)
    return "send" if local.replace(tzinfo=None) >= deadline else "sync"


async def _sync_garmin(db: DbSession, user: User, now: datetime) -> None:
    last = _last_sync.get(user.id)
    if last is not None and now - last < SYNC_EVERY:
        return
    conn = db.scalar(select(Connection).where(Connection.user_id == user.id, Connection.provider == "garmin"))
    if conn is None:
        return
    _last_sync[user.id] = now
    from .providers import garmin  # the Garmin client is heavy; only loaded when needed

    try:
        await garmin.sync(db, conn)
    except Exception as exc:  # a failed sync shouldn't stop the others' notes
        log.warning("Morning Garmin sync for user %s failed: %s", user.id, exc)


async def _email(user: User, subject: str, content_md: str) -> None:
    if not (user.ai_settings or {}).get("email") or user.emails_disabled or not mailer.configured():
        return
    try:
        await mailer.send(user.email, subject, *assessments.email_bodies(user, subject, content_md))
    except mailer.MailError as exc:
        log.warning("Emailing the morning note to user %s failed: %s", user.id, exc)


async def handle(db: DbSession, user: User, now: datetime) -> str:
    action = step(db, user, now)
    if action == "sync":
        await _sync_garmin(db, user, now)
        action = step(db, user, now)  # the sync may have brought the sleep in
        if action == "sync":
            return "waiting"
    if action not in ("send", "update"):
        return action
    today = now.astimezone(localtime.zone(user.timezone)).date()
    before = todays_note(db, user.id, today)
    try:
        a = await assessments.create(db, user, user, "daily", scheduled=True, today=today)
    except CoachError as exc:
        log.warning("Morning note for user %s skipped: %s", user.id, exc)
        return "skipped"
    if action == "send":
        await _email(user, f"Today: {a.verdict.upper()}", a.content_md)
    elif before is not None and a.verdict != before.verdict:
        subject = f"Update: today is {a.verdict.upper()}, not {before.verdict.upper()}"
        await _email(user, subject, "Last night's sleep data came in after your note.\n\n" + a.content_md)
    return action


async def run(now: datetime | None = None) -> None:
    """Scheduler job, every few minutes."""
    now = now or datetime.now(UTC)
    db = SessionLocal()
    try:
        users = [
            u
            for u in db.scalars(select(User).where(User.is_active)).all()
            if (u.ai_settings or {}).get("daily") and not u.ai_disabled
        ]
        for user in users:
            if step(db, user, now) in ("wait", "done"):
                continue
            if not assessments.has_recent_data(db, user):
                continue
            await handle(db, user, now)
    finally:
        db.close()
