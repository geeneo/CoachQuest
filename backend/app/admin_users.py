"""Admin → Users: each user's data at a glance.

`overview` builds one row per user from grouped counts (a handful of queries,
not a few per user), so the page stays quick with many users. `detail` adds
the recent history for one user; opening it is written to that user's access
log, like a coach looking at their data.

Storage per user is an estimate: each table's size on disk (SQLite's dbstat,
when the build has it) split by the user's share of its rows.
"""

from datetime import timedelta

from sqlalchemy import case, func, select, text
from sqlalchemy.orm import Session as DbSession

from . import auth_log, backfill, runtime, sync_options
from .coach import monthly_limit
from .db import (
    Activity,
    AiCall,
    Assessment,
    AthleteNote,
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
    UserStravaApp,
    WellnessDay,
    Workout,
    utcnow,
)
from .providers import strava

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
    (AthleteNote, AthleteNote.athlete_id),
    (SyncLog, SyncLog.athlete_id),
    (AuthEvent, AuthEvent.user_id),
)


def _counts(db: DbSession, col, *where) -> dict:
    return dict(db.execute(select(col, func.count()).where(*where).group_by(col)).all())


def strava_apps(db: DbSession) -> dict[int, str | None]:
    """Per user with Strava linked: which app holds the link ("own", "shared", "old").

    Strava caps how many athletes one app may have, so the admin needs to see
    who is using a slot on the shared app.
    """
    own = dict(db.execute(select(UserStravaApp.user_id, UserStravaApp.client_id)).all())
    shared = runtime.get("strava_client_id")
    conns = db.scalars(select(Connection).where(Connection.provider == "strava"))
    return {c.user_id: strava.issuing_app(c, own.get(c.user_id), shared) for c in conns}


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
            # For "Import older data" in the user's details.
            "backfill": backfill.state(c),
            "options": sync_options.options(c),
        }
    for uid, app in strava_apps(db).items():
        conns[uid]["strava"]["app"] = app

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
    coaches = _counts(db, Grant.athlete_id, Grant.status == "active", Grant.role == "coach")
    athletes = _counts(db, Grant.coach_id, Grant.status == "active", Grant.role == "coach")
    wellness = _counts(db, WellnessDay.user_id)
    plans = _counts(db, Plan.athlete_id)
    races = _counts(db, Race.user_id, Race.active.is_(True))
    scheduled = _counts(db, ScheduledWorkout.athlete_id)
    ai: dict[int, dict] = {}
    for uid, athlete_id, n, tokens in db.execute(
        select(AiCall.user_id, AiCall.athlete_id, func.count(), func.sum(_ALL_TOKENS))
        .where(AiCall.at >= month)
        .group_by(AiCall.user_id, AiCall.athlete_id)
    ):
        row = ai.setdefault(uid, {"calls": 0, "tokens": 0, "for_others": 0})
        row["calls"] += n
        row["tokens"] += tokens or 0
        if athlete_id != uid:
            row["for_others"] += n
    storage = _storage(db)

    view_data = runtime.get("admin_view_data") == "on"
    super_approval = runtime.get("signup_approval") == "on"
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
        if u.ai_disabled:
            flags.append("AI off")
        if u.emails_disabled:
            flags.append("emails off")
        limit = monthly_limit(u)
        if limit and ai.get(u.id, {}).get("calls", 0) >= 0.8 * limit:
            flags.append("AI limit nearly used")
            attention += 1
        if failed.get(u.id, 0) >= 5:
            flags.append(f"{failed[u.id]} failed sign-ins")
            attention += 1
        quiet = seen is None or seen < now - QUIET
        if u.is_active and u.approved and quiet:
            flags.append("no sign-in for 30 days")
        if quiet and uc.get("strava", {}).get("app") == "shared":
            # Holds one of the shared Strava app's few athlete slots without using it.
            flags.append("idle on shared Strava app")
            attention += 1
        rows.append(
            {
                "id": u.id,
                "email": u.email,
                "display_name": u.display_name,
                "is_admin": u.is_admin,
                "is_super_admin": u.is_super_admin,
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
                "ai_month": ai.get(u.id, {"calls": 0, "tokens": 0, "for_others": 0}),
                "disabled_reason": u.disabled_reason,
                "disabled_at": u.disabled_at,
                "disabled_by_self": u.disabled_by_self,
                "ai_disabled": u.ai_disabled,
                "emails_disabled": u.emails_disabled,
                "plan_approval_off": u.plan_approval_off,
                "ai_monthly_limit": u.ai_monthly_limit,
                "ai_limit": monthly_limit(u),
                "storage_bytes": storage.get(u.id, 0),
                "flags": flags,
                "attention": attention,
                # Admin → Settings → "Admins can view athletes' data".
                "can_view_data": view_data,
                # Admin → Settings → "Super admin approves new sign-ups".
                "super_approval": super_approval,
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
            {"name": names.get(g.coach_id, "?"), "scopes": g.scopes, "role": g.role}
            for g in grants
            if g.athlete_id == user.id
        ],
        "athletes": [
            {"name": names.get(g.athlete_id, "?"), "scopes": g.scopes, "role": g.role}
            for g in grants
            if g.coach_id == user.id
        ],
        "ai": ai_detail(db, user),
    }


# Rough $ per million tokens (input, output) for the cost estimate on the admin page; cache reads cost
# 0.1x the input price and cache writes 1.25x. Unknown models show no estimate. Check anthropic.com/pricing.
PRICES = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}
_ALL_TOKENS = AiCall.input_tokens + AiCall.output_tokens + AiCall.cache_read_tokens + AiCall.cache_write_tokens


def _cost(model: str, inp: int, out: int, read: int, write: int) -> float | None:
    price = PRICES.get(model)
    if price is None:
        return None
    return (inp * price[0] + out * price[1] + read * price[0] * 0.1 + write * price[0] * 1.25) / 1_000_000


def ai_detail(db: DbSession, user: User) -> dict:
    """This month's AI calls the user asked for, by kind and by athlete, with tokens and a rough cost."""
    month = utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows = db.execute(
        select(
            AiCall.kind,
            AiCall.athlete_id,
            AiCall.model,
            func.count(),
            func.sum(AiCall.input_tokens),
            func.sum(AiCall.output_tokens),
            func.sum(AiCall.cache_read_tokens),
            func.sum(AiCall.cache_write_tokens),
            func.sum(case((AiCall.status.not_in(("ok", "end_turn", "tool_use")), 1), else_=0)),
        )
        .where(AiCall.user_id == user.id, AiCall.at >= month)
        .group_by(AiCall.kind, AiCall.athlete_id, AiCall.model)
    ).all()
    names = {u.id: u.display_name for u in db.scalars(select(User).where(User.id.in_({r[1] for r in rows})))}
    by_kind: dict[str, dict] = {}
    by_athlete: dict[str, dict] = {}
    total_cost, priced = 0.0, True
    for kind, athlete_id, model, n, inp, out, read, write, failed in rows:
        inp, out, read, write = inp or 0, out or 0, read or 0, write or 0
        cost = _cost(model, inp, out, read, write)
        priced = priced and cost is not None
        total_cost += cost or 0
        who = "themselves" if athlete_id == user.id else names.get(athlete_id, "a deleted athlete")
        for key, bucket in ((kind or "other", by_kind), (who, by_athlete)):
            b = bucket.setdefault(key, {"calls": 0, "failed": 0, "input": 0, "output": 0, "cache_read": 0})
            b["calls"] += n
            b["failed"] += failed or 0
            b["input"] += inp + write
            b["output"] += out
            b["cache_read"] += read
    return {
        "recent": recent_calls(db, user, names),
        "by_kind": by_kind,
        "by_athlete": by_athlete,
        "cost_usd": round(total_cost, 2) if rows else 0,
        "cost_complete": priced,
        "limit": monthly_limit(user),
        "own_limit": user.ai_monthly_limit,
        "disabled": user.ai_disabled,
    }


def _guess_kind(db: DbSession, user: User, call: AiCall) -> str | None:
    """For calls logged before calls had a type: what the user made at that moment (a plan, a note, a chat)."""
    if call.status in ("end_turn", "tool_use", "pause_turn", "stop_sequence"):
        return "chat"  # only the chat logs Claude's stop reason; plans and notes log "ok"
    near = (call.at - timedelta(minutes=5), call.at + timedelta(minutes=5))
    if db.scalar(select(Plan.id).where(Plan.author_id == user.id, Plan.created_at.between(*near))):
        return "plan"
    note = db.scalar(
        select(Assessment.kind).where(Assessment.author_id == user.id, Assessment.created_at.between(*near))
    )
    if note:
        return "readiness" if note == "daily" else "weekly"
    if db.scalar(select(CoachChat.id).where(CoachChat.viewer_id == user.id, CoachChat.updated_at.between(*near))):
        return "chat"
    return None


def recent_calls(db: DbSession, user: User, names: dict[int, str], limit: int = 20) -> list[dict]:
    """The user's latest AI calls: when, what for (guessed for old ones), whose data, result and tokens."""
    rows = db.scalars(select(AiCall).where(AiCall.user_id == user.id).order_by(AiCall.at.desc()).limit(limit)).all()
    missing = {r.athlete_id for r in rows} - set(names) - {user.id}
    if missing:
        names = {**names, **{u.id: u.display_name for u in db.scalars(select(User).where(User.id.in_(missing)))}}
    out = []
    for r in rows:
        guessed = None if r.kind else _guess_kind(db, user, r)
        out.append(
            {
                "at": r.at,
                "kind": r.kind or guessed,
                "guessed": guessed is not None,
                "whose": "themselves" if r.athlete_id == user.id else names.get(r.athlete_id, "a deleted athlete"),
                "status": r.status,
                "tokens": r.input_tokens + r.output_tokens + r.cache_read_tokens + r.cache_write_tokens,
                "model": r.model,
            }
        )
    return out
