"""Password resets and account deletion, shared by the auth and admin routers."""

import logging
import secrets
from datetime import timedelta

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session as DbSession

from . import mailer, runtime
from .config import settings
from .db import (
    AccessLog,
    Activity,
    AiCall,
    Assessment,
    AthleteNote,
    AuthEvent,
    CoachChat,
    CoachInstruction,
    Comment,
    Connection,
    DeletedActivity,
    ExternalWorkout,
    Grant,
    NoteSuggestion,
    OAuthState,
    PasswordReset,
    PendingMfa,
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
from .security import hash_password, hash_token

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


def delete_account(db: DbSession, user: User) -> None:
    """Remove the user and everything that belongs to them.

    Deleted explicitly rather than through ON DELETE CASCADE, because SQLite
    only enforces foreign keys when asked to.
    """
    uid = user.id
    # Comments about their own training go; comments they wrote for other athletes stay, unsigned.
    db.execute(delete(Comment).where(Comment.athlete_id == uid))
    db.execute(update(Comment).where(Comment.author_id == uid).values(author_id=None))
    # The sign-in log keeps the email until the retention removes it, for the audit trail.
    db.execute(update(AuthEvent).where(AuthEvent.user_id == uid).values(user_id=None))
    db.execute(update(Comment).where(Comment.edited_by == uid).values(edited_by=None))
    # Notes about them go; notes they wrote about other athletes stay, unsigned.
    db.execute(delete(NoteSuggestion).where(NoteSuggestion.athlete_id == uid))
    db.execute(update(NoteSuggestion).where(NoteSuggestion.asked_by == uid).values(asked_by=None))
    db.execute(update(NoteSuggestion).where(NoteSuggestion.decided_by == uid).values(decided_by=None))
    db.execute(delete(AthleteNote).where(AthleteNote.athlete_id == uid))
    db.execute(update(AthleteNote).where(AthleteNote.author_id == uid).values(author_id=None))
    db.execute(update(AthleteNote).where(AthleteNote.updated_by == uid).values(updated_by=None))
    # Instructions for their own training go; ones they wrote for other athletes stay, unsigned.
    db.execute(delete(CoachInstruction).where(CoachInstruction.athlete_id == uid))
    db.execute(update(CoachInstruction).where(CoachInstruction.author_id == uid).values(author_id=None))
    db.execute(update(CoachInstruction).where(CoachInstruction.updated_by == uid).values(updated_by=None))
    for model, column in (
        (Activity, Activity.user_id),
        (DeletedActivity, DeletedActivity.user_id),
        (WellnessDay, WellnessDay.user_id),
        (Connection, Connection.user_id),
        (UserStravaApp, UserStravaApp.user_id),
        (OAuthState, OAuthState.user_id),
        (PendingMfa, PendingMfa.user_id),
        (Session, Session.user_id),
        (PasswordReset, PasswordReset.user_id),
        (Plan, Plan.athlete_id),
        (Race, Race.user_id),
        (Assessment, Assessment.athlete_id),
        (ScheduledWorkout, ScheduledWorkout.athlete_id),
        (Workout, Workout.owner_id),
        (ExternalWorkout, ExternalWorkout.athlete_id),
        (SyncJob, SyncJob.athlete_id),
        (SyncLog, SyncLog.athlete_id),
    ):
        db.execute(delete(model).where(column == uid))
    db.execute(delete(Grant).where(or_(Grant.athlete_id == uid, Grant.coach_id == uid)))
    db.execute(delete(AccessLog).where(or_(AccessLog.athlete_id == uid, AccessLog.viewer_id == uid)))
    db.execute(delete(AiCall).where(or_(AiCall.user_id == uid, AiCall.athlete_id == uid)))
    db.execute(delete(CoachChat).where(or_(CoachChat.athlete_id == uid, CoachChat.viewer_id == uid)))
    # Plans this user wrote for other athletes stay with those athletes.
    db.execute(update(Plan).where(Plan.author_id == uid).values(author_id=None))
    # Workouts this user assigned to others stay on their calendars.
    db.execute(update(ScheduledWorkout).where(ScheduledWorkout.assigned_by == uid).values(assigned_by=None))
    db.delete(user)
    db.commit()
    log.info("Deleted user %s", uid)
