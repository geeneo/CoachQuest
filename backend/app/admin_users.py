"""Admin → Users: each user's data at a glance.

`overview` builds one row per user from grouped counts (a handful of queries,
not a few per user), so the page stays quick with many users. `detail` adds
the recent history for one user; opening it is written to that user's access
log, like a coach looking at their data.

Storage per user is an estimate: each table's size on disk (SQLite's dbstat,
when the build has it) split by the user's share of its rows.
"""

from datetime import timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session as DbSession

from . import auth_log
from .db import (
    Activity,
    AiCall,
    Assessment,
    AuthEvent,
    CoachChat,
    Comment,
    Connection,
    Grant,
    Plan,
    Race,
    ScheduledWorkout,
    Session,
    SyncJob,
    SyncLog,
    User,
    WellnessDay,
    Workout,
    utcnow,
)

PROVIDERS = ("strava", "garmin", "intervals_icu")
STALE_SYNC = timedelta(days=2)  # a connected source with no sync for this long is flagged
QUIET = timedelta(days=30)  # no sign-in for this long
# Tables that hold a user's data, with the column naming the user (for the storage estimate).
OWNED = (
    (Activity, Activity.user_id),
    (WellnessDay, WellnessDay.user_id),
    (Plan, Plan.athlete_id),
    (Assessment, Assessment.athlete_id),
    (CoachChat, CoachChat.athlete_id),
    (ScheduledWorkout, ScheduledWorkout.athlete_id),
    (Workout, Workout.owner_id),
    (Comment, Comment.athlete_id),
    (SyncLog, SyncLog.athlete_id),
    (AuthEvent, AuthEvent.user_id),
)


def _counts(db: DbSession, col, *where) -> dict:
    return dict(db.execute(select(col, func.count()).where(*where).group_by(col)).all())


def _table_bytes(db: DbSession) -> dict[str, int]:
    """Bytes on disk per table (its indexes not counted), or {} when dbstat isn't there."""
    try:
        rows = db.execute(text("SELECT name, SUM(pgsize) FROM dbstat GROUP BY name")).all()
    except Exception:  # not SQLite, or SQLite built without dbstat
        db.rollback()
        return {}
    return {name: int(size or 0) for name, size in rows}


def _storage(db: DbSession) -> dict[int, int]:
    sizes = _table_bytes(db)
    out: dict[int, float] = {}
    for model, col in OWNED:
        per_user = _counts(db, col)
        total = sum(per_user.values())
        if not total:
            continue
        # Without dbstat, a rough 200 bytes a row.
        per_row = sizes.get(model.__tablename__, total * 200) / total
        for uid, n in per_user.items():
            if uid is not None:
                out[uid] = out.get(uid, 0) + n * per_row
    return {uid: round(v) for uid, v in out.items()}


def overview(db: DbSession) -> list[dict]:
    now = utcnow()
    month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    users = db.scalars(select(User).order_by(User.approved, User.created_at)).all()

    acts: dict[int, dict] = {}
    for uid, source, n, first, last in db.execute(
        select(Activity.user_id, Activity.source, func.count(), func.min(Activity.start_time))
        .add_columns(func.max(Activity.start_time))
        .group_by(Activity.user_id, Activity.source)
    ):
        a = acts.setdefault(uid, {"total": 0, "by_source": {}, "first": None, "last": None})
        a["total"] += n
        a["by_source"][source] = n
        a["first"] = min(filter(None, (a["first"], first)), default=None)
        a["last"] = max(filter(None, (a["last"], last)), default=None)

    conns: dict[int, dict] = {}
    for c in db.scalars(select(Connection).where(Connection.provider.in_(PROVIDERS))):
        conns.setdefault(c.user_id, {})[c.provider] = {
            "status": c.status,
            "last_sync_at": c.last_sync_at,
            "last_error": c.last_error,
        }

    jobs: dict[int, dict] = {}
    for uid, status, n in db.execute(
        select(SyncJob.athlete_id, SyncJob.status, func.count())
        .where(SyncJob.status.in_(("queued", "failed", "blocked")))
        .group_by(SyncJob.athlete_id, SyncJob.status)
    ):
        jobs.setdefault(uid, {})[status] = n

    last_login = dict(
        db.execute(
            select(AuthEvent.user_id, func.max(AuthEvent.at))
            .where(AuthEvent.event == "login_ok")
            .group_by(AuthEvent.user_id)
        ).all()
    )
    last_seen = dict(
        db.execute(select(Session.user_id, func.max(Session.last_seen_at)).group_by(Session.user_id)).all()
    )
    failed = _counts(db, AuthEvent.user_id, AuthEvent.event == "login_failed", AuthEvent.at >= now - timedelta(days=7))
    coaches = _counts(db, Grant.athlete_id, Grant.status == "active")
    athletes = _counts(db, Grant.coach_id, Grant.status == "active")
    wellness = _counts(db, WellnessDay.user_id)
    plans = _counts(db, Plan.athlete_id)
    races = _counts(db, Race.user_id, Race.active.is_(True))
    scheduled = _counts(db, ScheduledWorkout.athlete_id)
    ai = {
        uid: {"calls": n, "tokens": tokens}
        for uid, n, tokens in db.execute(
            select(AiCall.user_id, func.count(), func.sum(AiCall.input_tokens + AiCall.output_tokens))
            .where(AiCall.at >= month)
            .group_by(AiCall.user_id)
        )
    }
    storage = _storage(db)

    rows = []
    for u in users:
        uc = conns.get(u.id, {})
        uj = jobs.get(u.id, {})
        seen = max(filter(None, (last_login.get(u.id), last_seen.get(u.id))), default=None)
        flags, attention = [], 0
        if not u.approved:
            flags.append("waiting for approval")
            attention += 5
        if not u.is_active:
            flags.append("disabled")
        for provider, c in uc.items():
            name = {"intervals_icu": "Intervals.icu"}.get(provider, provider.capitalize())
            if c["status"] == "error":
                flags.append(f"{name} sync error")
                attention += 3
            elif provider != "intervals_icu" and (not c["last_sync_at"] or c["last_sync_at"] < now - STALE_SYNC):
                flags.append(f"{name} not synced lately")
                attention += 1
        if uj.get("failed") or uj.get("blocked"):
            flags.append("workout delivery failed")
            attention += 2
        if failed.get(u.id, 0) >= 5:
            flags.append(f"{failed[u.id]} failed sign-ins")
            attention += 1
        if u.is_active and u.approved and (seen is None or seen < now - QUIET):
            flags.append("no sign-in for 30 days")
        rows.append(
            {
                "id": u.id,
                "email": u.email,
                "display_name": u.display_name,
                "is_admin": u.is_admin,
                "is_active": u.is_active,
                "approved": u.approved,
                "created_at": u.created_at,
                "last_seen_at": seen,
                "failed_sign_ins_7d": failed.get(u.id, 0),
                "activities": acts.get(u.id, {"total": 0, "by_source": {}, "first": None, "last": None}),
                "wellness_days": wellness.get(u.id, 0),
                "connections": uc,
                "delivery": {k: uj.get(k, 0) for k in ("queued", "failed", "blocked")},
                "coaches": coaches.get(u.id, 0),
                "athletes": athletes.get(u.id, 0),
                "plans": plans.get(u.id, 0),
                "races": races.get(u.id, 0),
                "scheduled_workouts": scheduled.get(u.id, 0),
                "ai_month": ai.get(u.id, {"calls": 0, "tokens": 0}),
                "storage_bytes": storage.get(u.id, 0),
                "flags": flags,
                "attention": attention,
            }
        )
    return rows


def detail(db: DbSession, user: User) -> dict:
    """Recent history for one user: sports, sign-ins, deliveries, sharing."""
    sports = db.execute(
        select(Activity.sport, func.count()).where(Activity.user_id == user.id).group_by(Activity.sport)
    ).all()
    signins = db.scalars(
        select(AuthEvent).where(AuthEvent.user_id == user.id).order_by(AuthEvent.at.desc()).limit(8)
    ).all()
    deliveries = db.scalars(
        select(SyncLog)
        .where(SyncLog.athlete_id == user.id, SyncLog.outcome != "unchanged")
        .order_by(SyncLog.at.desc())
        .limit(8)
    ).all()
    grants = db.scalars(
        select(Grant).where(((Grant.athlete_id == user.id) | (Grant.coach_id == user.id)), Grant.status == "active")
    ).all()
    ids = {g.athlete_id for g in grants} | {g.coach_id for g in grants}
    names = {u.id: u.display_name for u in db.scalars(select(User).where(User.id.in_(ids)))}
    return {
        "sports": sorted(({"sport": s, "count": n} for s, n in sports), key=lambda r: -r["count"]),
        "sign_ins": [auth_log.out(e) for e in signins],
        "deliveries": [
            {
                "provider": r.provider,
                "workout": r.workout_name,
                "action": r.action,
                "outcome": r.outcome,
                "message": r.message,
                "at": r.at,
            }
            for r in deliveries
        ],
        "coaches": [
            {"name": names.get(g.coach_id, "?"), "scopes": g.scopes} for g in grants if g.athlete_id == user.id
        ],
        "athletes": [
            {"name": names.get(g.athlete_id, "?"), "scopes": g.scopes} for g in grants if g.coach_id == user.id
        ],
    }
