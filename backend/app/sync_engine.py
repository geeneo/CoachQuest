"""Sends scheduled workouts to the athlete's platforms in the background.

Changes are queued as jobs (one open job per workout and platform; a newer
change replaces the queued one) and worked off by `run_due`, which the
scheduler calls every minute and requests kick off right away.

- Idempotent: our key on the platform is "cq-<scheduled id>", so a repeat
  updates instead of duplicating, and a workout whose content hasn't changed
  since it was last sent isn't sent again.
- Transient errors back off exponentially (1, 2, 4 ... 60 minutes) and give
  up after MAX_ATTEMPTS; a Retry starts over.
- Rate limits wait as long as the platform asks, without using up attempts.
- Lost or narrowed authorisation blocks the job and marks the connection;
  nothing is retried until the athlete reconnects. Rejected workouts wait
  for a change or a Retry.
- Every attempt goes in the sync log.
"""

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import localtime
from .db import Connection, ExternalWorkout, ScheduledWorkout, SessionLocal, SyncJob, SyncLog, User, utcnow
from .delivery import adapter
from .delivery.base import AuthFailed, DeliveryError, Forbidden, RateLimited
from .security import decrypt_json

log = logging.getLogger("coachquest.sync")

MAX_ATTEMPTS = 6
OPEN = ("queued", "running", "failed", "blocked")
_lock = asyncio.Lock()


def external_id(scheduled_workout_id: int) -> str:
    return f"cq-{scheduled_workout_id}"


def backoff(attempts: int) -> timedelta:
    """Wait before try number attempts+1: 1, 2, 4, 8, 16, 32 minutes, at most an hour."""
    return timedelta(minutes=min(60, 2 ** max(0, attempts - 1)))


def payload(sw: ScheduledWorkout) -> dict:
    return {
        "name": sw.name,
        "description": sw.description,
        "instructions": sw.instructions,
        "sport": sw.sport,
        "steps": sw.steps,
    }


def content_hash(sw: ScheduledWorkout) -> str:
    raw = json.dumps({**payload(sw), "day": sw.day.isoformat()}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def auto_providers(db: DbSession, athlete: User) -> list[str]:
    """Platforms this athlete has switched automatic delivery on for, that can take workouts."""
    auto = (athlete.platform_prefs or {}).get("auto") or {}
    out = []
    for provider, on in auto.items():
        a = adapter(provider)
        if on and a and a.available() and "upsert" in a.operations:
            conn = _connection(db, athlete.id, provider)
            if conn is not None:
                out.append(provider)
    return out


def _connection(db: DbSession, athlete_id: int, provider: str) -> Connection | None:
    return db.scalar(select(Connection).where(Connection.user_id == athlete_id, Connection.provider == provider))


def _mapping(db: DbSession, sw_id: int, provider: str) -> ExternalWorkout | None:
    return db.scalar(
        select(ExternalWorkout).where(
            ExternalWorkout.scheduled_workout_id == sw_id, ExternalWorkout.provider == provider
        )
    )


def _open_job(db: DbSession, sw_id: int, provider: str) -> SyncJob | None:
    return db.scalar(
        select(SyncJob).where(
            SyncJob.scheduled_workout_id == sw_id, SyncJob.provider == provider, SyncJob.status.in_(OPEN)
        )
    )


def _queue(db: DbSession, athlete_id: int, provider: str, sw_id: int, name: str, action: str, reason: str) -> None:
    job = _open_job(db, sw_id, provider)
    if job is None:
        job = SyncJob(athlete_id=athlete_id, provider=provider, scheduled_workout_id=sw_id)
        db.add(job)
    job.workout_name = name[:120]
    job.action = action
    job.reason = reason
    job.status = "queued"
    job.attempts = 0
    job.last_error = None
    job.next_attempt_at = utcnow()
    job.updated_at = utcnow()


def _wanted_action(sw: ScheduledWorkout | None, today) -> str:
    """Send planned workouts from today on; take cancelled or skipped ones off the platform."""
    if sw is None or sw.status in ("cancelled", "skipped"):
        return "delete"
    return "upsert" if sw.day >= today else "none"


def workout_changed(db: DbSession, sw: ScheduledWorkout, reason: str) -> int:
    """Queue whatever the platforms need after a workout was created or changed. Returns jobs queued."""
    athlete = db.get(User, sw.athlete_id)
    action = _wanted_action(sw, localtime.today(athlete))
    queued = 0
    providers = set(auto_providers(db, athlete))
    # A workout already on a platform is kept in step there even if auto-send was later switched off.
    providers |= {
        m.provider for m in db.scalars(select(ExternalWorkout).where(ExternalWorkout.scheduled_workout_id == sw.id))
    }
    for provider in providers:
        if action == "delete" and _mapping(db, sw.id, provider) is None and _open_job(db, sw.id, provider) is None:
            continue
        if action == "none":
            continue
        _queue(db, sw.athlete_id, provider, sw.id, sw.name, action, reason)
        queued += 1
    db.commit()
    return queued


def workout_removed(db: DbSession, athlete_id: int, sw_id: int, name: str) -> int:
    """The workout was deleted from the calendar: remove it wherever it was sent."""
    queued = 0
    providers = {
        m.provider for m in db.scalars(select(ExternalWorkout).where(ExternalWorkout.scheduled_workout_id == sw_id))
    }
    providers |= {
        j.provider
        for j in db.scalars(select(SyncJob).where(SyncJob.scheduled_workout_id == sw_id, SyncJob.status.in_(OPEN)))
    }
    for provider in providers:
        _queue(db, athlete_id, provider, sw_id, name, "delete", "removed")
        queued += 1
    db.commit()
    return queued


def send_upcoming(db: DbSession, athlete: User, provider: str, reason: str) -> int:
    """After connecting or switching auto-send on: queue every planned workout from today on."""
    today = localtime.today(athlete)
    rows = db.scalars(
        select(ScheduledWorkout).where(
            ScheduledWorkout.athlete_id == athlete.id,
            ScheduledWorkout.day >= today,
            ScheduledWorkout.status == "planned",
        )
    ).all()
    for sw in rows:
        _queue(db, athlete.id, provider, sw.id, sw.name, "upsert", reason)
    # Jobs blocked by the old, broken authorisation can go again.
    for job in db.scalars(
        select(SyncJob).where(
            SyncJob.athlete_id == athlete.id, SyncJob.provider == provider, SyncJob.status == "blocked"
        )
    ):
        job.status, job.attempts, job.next_attempt_at, job.reason = "queued", 0, utcnow(), reason
    db.commit()
    return len(rows)


async def resend_now(db: DbSession, athlete: User, provider: str) -> dict[str, int | list[str]]:
    """ "Sync now": send every planned workout from today on again, unchanged ones too, right away.

    A platform only tells its own partners (e.g. Intervals.icu → MyWhoosh) about workouts that changed,
    so a re-send is what nudges them. Returns counts by outcome, and the error messages."""
    today = localtime.today(athlete)
    upcoming = db.scalars(
        select(ScheduledWorkout.id).where(ScheduledWorkout.athlete_id == athlete.id, ScheduledWorkout.day >= today)
    ).all()
    for m in db.scalars(
        select(ExternalWorkout).where(
            ExternalWorkout.athlete_id == athlete.id,
            ExternalWorkout.provider == provider,
            ExternalWorkout.scheduled_workout_id.in_(upcoming),
        )
    ):
        m.content_hash = ""  # counts as changed, so it goes again
    send_upcoming(db, athlete, provider, "sync_now")
    out: dict[str, int | list[str]] = {"sent": 0, "deleted": 0, "failed": 0, "errors": []}
    async with _lock:
        jobs = db.scalars(
            select(SyncJob).where(
                SyncJob.athlete_id == athlete.id, SyncJob.provider == provider, SyncJob.status == "queued"
            )
        ).all()
        for job in jobs:
            outcome = await process(db, job)
            if outcome in ("sent", "deleted"):
                out[outcome] += 1
            elif outcome not in ("unchanged", "skipped"):
                out["failed"] += 1
                if job.last_error and job.last_error not in out["errors"]:
                    out["errors"].append(job.last_error)
    return out


def forget_sent(db: DbSession, athlete_id: int, provider: str) -> None:
    """Forget what was sent, e.g. when the athlete links a different account: everything goes again."""
    for m in db.scalars(
        select(ExternalWorkout).where(ExternalWorkout.athlete_id == athlete_id, ExternalWorkout.provider == provider)
    ):
        db.delete(m)


def disconnected(db: DbSession, athlete_id: int, provider: str) -> None:
    """Forget what was sent and close open jobs. Workouts already on the platform stay there."""
    for m in db.scalars(
        select(ExternalWorkout).where(ExternalWorkout.athlete_id == athlete_id, ExternalWorkout.provider == provider)
    ):
        db.delete(m)
    for job in db.scalars(
        select(SyncJob).where(SyncJob.athlete_id == athlete_id, SyncJob.provider == provider, SyncJob.status.in_(OPEN))
    ):
        job.status, job.last_error = "failed", "Disconnected"
    db.add(SyncLog(athlete_id=athlete_id, provider=provider, action="disconnect", outcome="disconnected"))
    db.commit()


def retry(db: DbSession, job: SyncJob) -> None:
    job.status, job.attempts, job.next_attempt_at, job.last_error = "queued", 0, utcnow(), None
    job.reason = "retry"
    db.commit()


def _log(db: DbSession, job: SyncJob, outcome: str, message: str = "") -> None:
    db.add(
        SyncLog(
            job_id=job.id,
            athlete_id=job.athlete_id,
            provider=job.provider,
            scheduled_workout_id=job.scheduled_workout_id,
            workout_name=job.workout_name,
            action=job.action,
            outcome=outcome,
            message=message[:500],
        )
    )


def _finish(db: DbSession, job: SyncJob, status: str, outcome: str, message: str = "") -> None:
    job.status = status
    job.updated_at = utcnow()
    job.last_error = None if status == "done" else (message or None)
    _log(db, job, outcome, message)
    db.commit()


async def process(db: DbSession, job: SyncJob, now: datetime | None = None) -> str:
    """Try one job. Returns the outcome written to the log."""
    now = now or utcnow()
    a = adapter(job.provider)
    if a is None or not a.available():
        _finish(db, job, "failed", "unavailable", f"Sending to {job.provider} isn't available on this server")
        return "unavailable"
    conn = _connection(db, job.athlete_id, job.provider)
    if conn is None:
        _finish(db, job, "blocked", "blocked", f"{a.name} isn't connected")
        return "blocked"
    if conn.status == "error":
        _finish(db, job, "blocked", "blocked", conn.last_error or f"Reconnect {a.name}")
        return "blocked"

    sw = db.get(ScheduledWorkout, job.scheduled_workout_id)
    if job.action == "upsert" and (sw is None or sw.status in ("cancelled", "skipped")):
        job.action = "delete"
    mapping = _mapping(db, job.scheduled_workout_id, job.provider)
    if job.action == "upsert" and mapping and mapping.content_hash == content_hash(sw):
        _finish(db, job, "done", "unchanged", "Already up to date")
        return "unchanged"
    if job.action == "delete" and mapping is None:
        _finish(db, job, "done", "skipped", "Was never sent")
        return "skipped"

    job.status, job.attempts, job.updated_at = "running", job.attempts + 1, now
    db.commit()
    token = decrypt_json(conn.token_enc)
    ext = external_id(job.scheduled_workout_id)
    try:
        if job.action == "upsert":
            result = await a.upsert(token, ext, payload(sw), sw.day)
            if mapping is None:
                mapping = ExternalWorkout(
                    scheduled_workout_id=sw.id, athlete_id=sw.athlete_id, provider=job.provider, external_id=ext
                )
                db.add(mapping)
            mapping.remote_id = result.remote_id or mapping.remote_id
            mapping.content_hash = content_hash(sw)
            mapping.synced_at = now
            conn.last_sync_at = now
            _finish(db, job, "done", "sent")
            return "sent"
        await a.delete(token, ext)
        db.delete(mapping)
        conn.last_sync_at = now
        _finish(db, job, "done", "deleted")
        return "deleted"
    except RateLimited as exc:
        job.attempts -= 1  # waiting our turn isn't a failure
        job.next_attempt_at = now + timedelta(seconds=exc.retry_after)
        _finish(db, job, "queued", "rate_limited", f"{exc.message}; next try in {exc.retry_after} s")
        return "rate_limited"
    except DeliveryError as exc:
        if exc.permanent:
            if isinstance(exc, AuthFailed | Forbidden):
                conn.status, conn.last_error = "error", exc.message
                _finish(db, job, "blocked", "blocked", exc.message)
                return "blocked"
            _finish(db, job, "failed", "failed", exc.message)
            return "failed"
        return _transient(db, job, exc.message, now)
    except Exception as exc:  # noqa: BLE001 - an adapter bug must not stop the queue
        log.exception("Sync job %s crashed", job.id)
        return _transient(db, job, f"Unexpected error: {type(exc).__name__}", now)


def _transient(db: DbSession, job: SyncJob, message: str, now: datetime) -> str:
    if job.attempts >= MAX_ATTEMPTS:
        _finish(db, job, "failed", "failed", f"Gave up after {job.attempts} tries: {message}")
        return "failed"
    wait = backoff(job.attempts)
    job.next_attempt_at = now + wait
    _finish(db, job, "queued", "retrying", f"{message}; next try in {int(wait.total_seconds() // 60)} min")
    return "retrying"


async def run_due(limit: int = 25) -> int:
    """Work off jobs that are due. Safe to call often: runs one batch at a time."""
    if _lock.locked():
        return 0
    async with _lock:
        db = SessionLocal()
        try:
            jobs = db.scalars(
                select(SyncJob)
                .join(User, User.id == SyncJob.athlete_id)
                # Jobs of a paused or disabled account wait until it's turned back on.
                .where(SyncJob.status == "queued", SyncJob.next_attempt_at <= utcnow(), User.is_active)
                .order_by(SyncJob.next_attempt_at)
                .limit(limit)
            ).all()
            for job in jobs:
                await process(db, job)
            return len(jobs)
        finally:
            db.close()


def reset_stuck() -> None:
    """At start-up: a job left "running" by a restart goes back in the queue."""
    with SessionLocal() as db:
        for job in db.scalars(select(SyncJob).where(SyncJob.status == "running")):
            job.status, job.next_attempt_at = "queued", utcnow()
        db.commit()


def status_for(db: DbSession, sw_ids: list[int]) -> dict[int, list[dict]]:
    """Per workout: where it is on each platform (sent, queued, retrying, failed, blocked)."""
    if not sw_ids:
        return {}
    out: dict[int, dict[str, dict]] = {}
    for m in db.scalars(select(ExternalWorkout).where(ExternalWorkout.scheduled_workout_id.in_(sw_ids))):
        out.setdefault(m.scheduled_workout_id, {})[m.provider] = {
            "provider": m.provider,
            "state": "sent",
            "at": m.synced_at,
        }
    for j in db.scalars(select(SyncJob).where(SyncJob.scheduled_workout_id.in_(sw_ids), SyncJob.status.in_(OPEN))):
        state = j.status
        if state == "queued" and j.attempts:
            state = "retrying"
        out.setdefault(j.scheduled_workout_id, {})[j.provider] = {
            "provider": j.provider,
            "state": state,
            "action": j.action,
            "at": j.updated_at,
            "message": j.last_error,
            "job_id": j.id,
        }
    return {k: list(v.values()) for k, v in out.items()}
