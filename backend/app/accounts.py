"""Password resets and account deletion, shared by the auth and admin routers."""

import logging
import secrets
from datetime import date, timedelta

from sqlalchemy import and_, delete, func, not_, or_, select, update
from sqlalchemy.orm import Session as DbSession

from . import mailer, runtime
from .config import settings
from .db import (
    Base,
    Connection,
    ExternalWorkout,
    PasswordReset,
    ScheduledWorkout,
    Session,
    User,
    utcnow,
)
from .security import decrypt_json, hash_password, hash_token

log = logging.getLogger("coachquest.accounts")

SELF_SERVICE_TTL = timedelta(minutes=30)
ADMIN_LINK_TTL = timedelta(hours=24)


def create_reset_link(db: DbSession, user: User, ttl: timedelta, admin_id: int | None = None) -> str:
    """New single-use link; any older unused links for this user stop working."""
    db.execute(delete(PasswordReset).where(PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None)))
    token = secrets.token_urlsafe(32)
    db.add(PasswordReset(token_hash=hash_token(token), user_id=user.id, created_by=admin_id, expires_at=utcnow() + ttl))
    db.commit()
    return f"{settings.public_base_url}/reset-password?token={token}"


async def email_reset_link(user: User, link: str, ttl: timedelta, by_admin: bool) -> None:
    hours = int(ttl.total_seconds() // 3600)
    valid = f"{hours} hours" if hours >= 2 else f"{int(ttl.total_seconds() // 60)} minutes"
    intro = (
        "An administrator created a password reset link for your CoachQuest account."
        if by_admin
        else "Someone (hopefully you) asked to reset the password for your CoachQuest account."
    )
    await mailer.send(
        user.email,
        "Reset your CoachQuest password",
        f"Hi {user.display_name},\n\n{intro}\n\nChoose a new password here (valid for {valid}, works once):\n"
        f"{link}\n\nIf you didn't ask for this, ignore this email. Your password stays the same.\n",
    )


def use_reset_token(db: DbSession, token: str, new_password: str) -> User | None:
    """Set the new password if the token is valid. Signs the user out everywhere."""
    reset = db.get(PasswordReset, hash_token(token))
    if reset is None or reset.used_at is not None or reset.expires_at < utcnow():
        return None
    user = db.get(User, reset.user_id)
    if user is None or not user.is_active:
        return None
    set_password(db, user, new_password)
    reset.used_at = utcnow()
    db.commit()
    return user


def set_password(db: DbSession, user: User, new_password: str) -> None:
    user.password_hash = hash_password(new_password)
    db.execute(delete(Session).where(Session.user_id == user.id))
    db.commit()


def active_admins(db: DbSession) -> int:
    return len(db.scalars(select(User.id).where(User.is_admin, User.is_active)).all())


def active_super_admins(db: DbSession) -> int:
    return len(db.scalars(select(User.id).where(User.is_super_admin, User.is_active)).all())


def promote_super_admins(db: DbSession) -> None:
    """At start-up: the SUPER_ADMIN_EMAILS accounts are admins and super admins."""
    if not settings.super_admin_emails:
        return
    for user in db.scalars(select(User).where(User.email.in_(settings.super_admin_emails))).all():
        user.is_admin = user.is_super_admin = True
    db.commit()


def super_approval_on() -> bool:
    """Admin → Settings → "Super admin approves new sign-ups"."""
    return runtime.get("signup_approval") == "on"


def disable(db: DbSession, user: User, reason: str | None, by_self: bool = False) -> None:
    """Switch the account off: signed out everywhere; syncs, AI notes, emails and workout sending stop
    (they all skip inactive accounts); coaches see it as disabled. Data, plans and sharing stay."""
    user.is_active = False
    user.disabled_reason = (reason or "").strip()[:200] or None
    user.disabled_at = utcnow()
    user.disabled_by_self = by_self
    db.execute(delete(Session).where(Session.user_id == user.id))
    db.commit()


def enable(db: DbSession, user: User) -> None:
    user.is_active = True
    user.disabled_reason, user.disabled_at, user.disabled_by_self = None, None, False
    db.commit()


# Labels for the delete preview (tables not listed show their table name).
TABLE_LABELS = {
    "activities": "Activities",
    "wellness_days": "Wellness days",
    "plans": "Training plans",
    "scheduled_workouts": "Calendar workouts",
    "workouts": "Workout library",
    "races": "Races",
    "segments": "Favourite routes and segments",
    "comments": "Comments",
    "grants": "Sharing (coaches and friends)",
    "connections": "Linked apps (Strava, Garmin, Intervals.icu)",
    "assessments": "AI coach reviews",
    "coach_chats": "AI coach chats",
    "ai_calls": "AI usage records",
    "athlete_notes": "Notes",
    "coach_instructions": "Coach instructions",
    "sessions": "Sign-in sessions",
    "access_log": "Access log entries",
    "auth_events": "Sign-in log entries",
}


def _plan(table, where, steps: list, depth: int = 0) -> None:
    """What deleting `table` rows matching `where` does, following every foreign key that points at
    them (children first): ("delete", table, where) or ("unsign", table, column, ids)."""
    if depth > 5:
        raise RuntimeError(f"Foreign keys loop through {table.name}")
    for child in Base.metadata.sorted_tables:
        for fk in child.foreign_keys:
            if fk.column.table is not table or child is table:
                continue
            if fk.ondelete == "SET NULL":
                steps.append(("unsign", child, fk.parent, fk.parent.in_(select(fk.column).where(where))))
            else:  # CASCADE (or no rule): the rows belong to what's deleted
                _plan(child, fk.parent.in_(select(fk.column).where(where)), steps, depth + 1)
    steps.append(("delete", table, None, where))


def _steps(user_id: int) -> list:
    users = User.__table__
    steps: list = []
    _plan(users, users.c.id == user_id, steps)
    return steps


def deletion_preview(db: DbSession, user: User) -> dict:
    """Row counts deleting this user removes, and rows they wrote for others that stay, unsigned."""
    deleted: dict[str, int] = {}
    kept: dict[str, int] = {}
    steps = _steps(user.id)
    gone: dict[str, list] = {}
    for action, table, _column, where in steps:
        if action == "delete":
            gone.setdefault(table.name, []).append(where)
    for action, table, _column, where in steps:
        # Users itself, and the sign-in log (kept with the email for security), aren't "for others".
        if table.name in ("users", "auth_events"):
            continue
        if action == "unsign" and table.name in gone:
            where = and_(where, not_(or_(*gone[table.name])))  # their own rows go anyway
        n = db.scalar(select(func.count()).select_from(table).where(where))
        if n:
            label = TABLE_LABELS.get(table.name, table.name.replace("_", " ").capitalize())
            target = deleted if action == "delete" else kept
            target[label] = target.get(label, 0) + n
    return {"deleted": deleted, "kept_unsigned": kept}


def delete_account(db: DbSession, user: User) -> None:
    """Remove the user and everything that belongs to them, following every foreign key to users
    (so tables added later are covered too): rows that belong to them are deleted; rows they wrote
    for others (a coach's plans and comments, posts, settings changed) stay, unsigned.

    Done here rather than left to ON DELETE CASCADE, because SQLite only enforces foreign keys when
    asked to. The sign-in log keeps the email until its retention removes it (security audit).
    Call revoke_links first to tell Strava and Intervals.icu."""
    uid = user.id
    db.expunge(user)
    for action, table, column, where in _steps(uid):
        if action == "unsign":
            db.execute(update(table).where(where).values({column.name: None}))
        else:
            db.execute(delete(table).where(where))
    db.commit()
    log.info("Deleted user %s", uid)


async def revoke_links(db: DbSession, user: User) -> list[str]:
    """Before deleting an account: take CoachQuest's future workouts off their Intervals.icu calendar,
    and revoke CoachQuest's access at Strava and Intervals.icu. Best effort: the local tokens go anyway.
    Returns what was done, for the admin."""
    from .delivery import intervals_icu
    from .providers import strava

    done = []
    today = date.today()
    for conn in db.scalars(select(Connection).where(Connection.user_id == user.id)):
        try:
            token = decrypt_json(conn.token_enc) if conn.token_enc else {}
        except Exception:  # noqa: BLE001 - a token that can't be read can't be revoked
            token = {}
        if conn.provider == "strava":
            await strava.deauthorize(conn)
            done.append("Strava access revoked")
        elif conn.provider == "intervals_icu" and token:
            future = db.scalars(
                select(ExternalWorkout.external_id)
                .join(ScheduledWorkout, ScheduledWorkout.id == ExternalWorkout.scheduled_workout_id)
                .where(
                    ExternalWorkout.athlete_id == user.id,
                    ExternalWorkout.provider == "intervals_icu",
                    ScheduledWorkout.day >= today,
                )
            ).all()
            removed = 0
            for external_id in future:
                try:
                    await intervals_icu.IntervalsIcu().delete(token, external_id)
                    removed += 1
                except Exception as exc:  # noqa: BLE001
                    log.info("Intervals.icu delete %s failed: %s", external_id, exc)
            await intervals_icu.IntervalsIcu().revoke(token)
            done.append(f"Intervals.icu: {removed} upcoming workout(s) removed, access revoked")
    return done
