"""Admin page: settings, users, version and usage stats."""

import logging
import shutil
from datetime import date, timedelta
from pathlib import Path

import anthropic
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session as DbSession

from .. import accounts, admin_users, auth_log, backfill, mailer, platform_catalog, runtime
from ..config import settings
from ..db import (
    AccessLog,
    Activity,
    AiCall,
    AuthEvent,
    Connection,
    Grant,
    Plan,
    PlatformWorkout,
    Session,
    User,
    WellnessDay,
    get_db,
    utcnow,
)
from ..delivery import intervals_icu
from ..deps import admin_user
from . import connections

log = logging.getLogger("coachquest.admin")

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/version")
def version(_: User = Depends(admin_user)):
    return {"commit": settings.build_commit, "built": settings.build_time}


@router.get("/stats")
def stats(_: User = Depends(admin_user), db: DbSession = Depends(get_db)):
    return {
        "users": db.scalar(select(func.count(User.id))),
        "connections": dict(db.execute(select(Connection.provider, func.count()).group_by(Connection.provider)).all()),
        "strava_shared": sum(app == "shared" for app in admin_users.strava_apps(db).values()),
        "connection_errors": db.scalar(select(func.count()).where(Connection.status == "error")),
        "ai_calls": dict(db.execute(select(AiCall.status, func.count()).group_by(AiCall.status)).all()),
        "ai_tokens": {
            "input": db.scalar(select(func.coalesce(func.sum(AiCall.input_tokens), 0))),
            "output": db.scalar(select(func.coalesce(func.sum(AiCall.output_tokens), 0))),
        },
    }


@router.get("/ai-usage")
def ai_usage(_: User = Depends(admin_user), db: DbSession = Depends(get_db)):
    """AI calls and tokens per user this month, against the monthly limit."""
    start = utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows = db.execute(
        select(
            User.id,
            User.display_name,
            func.count(AiCall.id),
            func.coalesce(func.sum(AiCall.input_tokens), 0),
            func.coalesce(func.sum(AiCall.output_tokens), 0),
        )
        .join(AiCall, AiCall.user_id == User.id)
        .where(AiCall.at >= start)
        .group_by(User.id)
        .order_by(func.count(AiCall.id).desc())
    ).all()
    return {
        "limit": int(runtime.get("ai_monthly_limit") or 0),
        "users": [{"id": r[0], "name": r[1], "calls": r[2], "input_tokens": r[3], "output_tokens": r[4]} for r in rows],
    }


# ---- settings ----


@router.get("/settings")
def list_settings(_: User = Depends(admin_user)):
    return {
        "settings": runtime.describe(),
        "env_only": {
            "PUBLIC_BASE_URL": settings.public_base_url,
            "strava_callback_domain": settings.public_base_url.split("://")[-1].split("/")[0],
        },
    }


class SettingsUpdate(BaseModel):
    # key -> new value; "" removes the web value and falls back to .env
    values: dict[str, str]


@router.put("/settings")
def update_settings(body: SettingsUpdate, admin: User = Depends(admin_user), db: DbSession = Depends(get_db)):
    try:
        for key, value in body.values.items():
            if value.strip():
                runtime.validate(key, value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if runtime.SUPER_ONLY & body.values.keys() and not admin.is_super_admin:
        names = ", ".join(runtime.EDITABLE[k].label for k in sorted(runtime.SUPER_ONLY & body.values.keys()))
        raise HTTPException(status_code=403, detail=f"Only a super admin can change: {names}")
    for key, value in body.values.items():
        runtime.save(db, key, value.strip(), admin.id)
    return {"settings": runtime.describe()}


@router.post("/settings/test-anthropic")
async def test_anthropic(_: User = Depends(admin_user)):
    """Checks the key and model with a free models lookup, no tokens spent."""
    key, model = runtime.get("anthropic_api_key"), runtime.get("anthropic_model")
    if not key:
        return {"ok": False, "message": "No API key set."}
    try:
        info = await anthropic.AsyncAnthropic(api_key=key, max_retries=0).models.retrieve(model)
    except anthropic.AuthenticationError:
        return {"ok": False, "message": "Anthropic rejected the API key."}
    except anthropic.NotFoundError:
        return {"ok": False, "message": f"The key works, but model {model!r} was not found."}
    except anthropic.APIStatusError as exc:
        return {"ok": False, "message": f"Anthropic returned an error ({exc.status_code})."}
    except anthropic.APIConnectionError:
        return {"ok": False, "message": "Could not reach api.anthropic.com from the server."}
    return {"ok": True, "message": f"Key works. Model: {info.display_name or info.id}."}


class TestEmail(BaseModel):
    to: EmailStr | None = None


@router.post("/settings/test-intervals")
async def test_intervals(_: User = Depends(admin_user)):
    """Checks the Intervals.icu Client ID and secret without anyone signing in."""
    return await intervals_icu.check_app()


@router.post("/settings/test-email")
async def test_email(body: TestEmail, admin: User = Depends(admin_user)):
    to = body.to or admin.email
    try:
        await mailer.send(
            to,
            "CoachQuest test email",
            f"This is a test from CoachQuest ({settings.public_base_url}).\n\nIf you can read this, email works.",
        )
    except mailer.MailError as exc:
        return {"ok": False, "message": str(exc)}
    return {"ok": True, "message": f"Sent to {to}. Check the inbox (and spam folder)."}


# ---- users ----


@router.get("/users")
def list_users(_: User = Depends(admin_user), db: DbSession = Depends(get_db)):
    """Every user with their data at a glance (people waiting for approval first)."""
    return admin_users.overview(db)


@router.get("/users/{user_id}/detail")
def user_detail(user_id: int, admin: User = Depends(admin_user), db: DbSession = Depends(get_db)):
    """One user's recent history. Logged in their access log, like a coach looking."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id != admin.id:
        db.add(AccessLog(athlete_id=user.id, viewer_id=admin.id, resource="admin overview"))
        db.commit()
    return admin_users.detail(db, user)


@router.post("/users/{user_id}/sync/{provider}")
async def user_sync_now(
    user_id: int,
    provider: str,
    force: bool = False,
    _: User = Depends(admin_user),
    db: DbSession = Depends(get_db),
):
    """Run a user's Strava / Garmin / Intervals.icu import now.

    Same 5-minute limit as theirs, unless `force` is set ("Sync anyway" on the page).
    """
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return await connections.sync_for(provider, user, db, force)


def _user_conn(db: DbSession, user_id: int, provider: str):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return connections._conn(db, user, provider)


class BackfillIn(BaseModel):
    since: date


@router.post("/users/{user_id}/backfill/{provider}")
def user_backfill(
    user_id: int,
    provider: str,
    body: BackfillIn,
    background: BackgroundTasks,
    _: User = Depends(admin_user),
    db: DbSession = Depends(get_db),
):
    """Import a user's older Strava / Garmin data, as they can on their Connections page."""
    return connections.begin_backfill(db, _user_conn(db, user_id, provider), body.since, background)


@router.post("/users/{user_id}/refresh/{provider}")
def user_refresh(
    user_id: int,
    provider: str,
    background: BackgroundTasks,
    _: User = Depends(admin_user),
    db: DbSession = Depends(get_db),
):
    return connections.begin_refresh(db, _user_conn(db, user_id, provider), background)


@router.delete("/users/{user_id}/backfill/{provider}")
def user_cancel_backfill(user_id: int, provider: str, _: User = Depends(admin_user), db: DbSession = Depends(get_db)):
    conn = _user_conn(db, user_id, provider)
    backfill.cancel(db, conn)
    return connections.conn_out(conn)


class UserUpdate(BaseModel):
    is_admin: bool | None = None
    is_super_admin: bool | None = None
    is_active: bool | None = None
    ai_disabled: bool | None = None
    emails_disabled: bool | None = None
    plan_approval_off: bool | None = None
    disabled_reason: str | None = Field(default=None, max_length=200)
    # A number overrides the site's monthly limit for this user (0 = no limit); null goes back to the site's.
    ai_monthly_limit: int | None = Field(default=None, ge=0, le=100000)


class SetPassword(BaseModel):
    new_password: str = Field(min_length=12, max_length=256)


def _other_user(db: DbSession, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def _manageable(db: DbSession, user_id: int, admin: User) -> User:
    """A user whose account `admin` may change: a super admin's only another super admin may."""
    user = _other_user(db, user_id)
    if user.is_super_admin and not admin.is_super_admin:
        raise HTTPException(status_code=403, detail="Only a super admin can change a super admin's account")
    return user


def _may_approve(admin: User) -> None:
    if accounts.super_approval_on() and not admin.is_super_admin:
        raise HTTPException(status_code=403, detail="Only a super admin can approve or reject sign-ups")


@router.post("/users/{user_id}/password")
def admin_set_password(
    user_id: int,
    body: SetPassword,
    request: Request,
    admin: User = Depends(admin_user),
    db: DbSession = Depends(get_db),
):
    """Set a user's password. They are signed out everywhere."""
    user = _manageable(db, user_id, admin)
    accounts.set_password(db, user, body.new_password)
    auth_log.admin_action(db, request, "admin_password_set", admin, user)
    log.info("Admin %s set the password of user %s", admin.id, user.id)
    return {"ok": True}


@router.post("/users/{user_id}/reset-link")
async def admin_reset_link(
    user_id: int, request: Request, admin: User = Depends(admin_user), db: DbSession = Depends(get_db)
):
    """A 24-hour reset link: emailed when email works, and always shown to the admin to pass on."""
    user = _manageable(db, user_id, admin)
    link = accounts.create_reset_link(db, user, accounts.ADMIN_LINK_TTL, admin_id=admin.id)
    auth_log.admin_action(db, request, "admin_reset_link", admin, user)
    log.info("Admin %s created a reset link for user %s", admin.id, user.id)
    try:
        await accounts.email_reset_link(user, link, accounts.ADMIN_LINK_TTL, by_admin=True)
        emailed = f"Emailed to {user.email}."
    except mailer.MailError as exc:
        emailed = f"Not emailed: {exc}"
    return {"link": link, "emailed": emailed}


@router.post("/users/{user_id}/approve")
async def approve_user(
    user_id: int, request: Request, admin: User = Depends(admin_user), db: DbSession = Depends(get_db)
):
    _may_approve(admin)
    user = _other_user(db, user_id)
    if user.approved:
        return {"ok": True, "emailed": None}
    user.approved = True
    db.commit()
    auth_log.admin_action(db, request, "admin_approved", admin, user)
    log.info("Admin %s approved user %s", admin.id, user.id)
    try:
        await mailer.send(
            user.email,
            "Your CoachQuest account is ready",
            f"Hi {user.display_name},\n\nYour CoachQuest account has been approved. Sign in here:\n"
            f"{settings.public_base_url}/login\n",
        )
        emailed = f"Emailed {user.email}."
    except mailer.MailError as exc:
        emailed = f"Not emailed: {exc}"
    return {"ok": True, "emailed": emailed}


@router.post("/users/{user_id}/reject")
def reject_user(user_id: int, request: Request, admin: User = Depends(admin_user), db: DbSession = Depends(get_db)):
    """Remove a sign-up that is still waiting for approval."""
    _may_approve(admin)
    user = _other_user(db, user_id)
    if user.approved:
        raise HTTPException(status_code=400, detail="Only accounts waiting for approval can be rejected; use Delete")
    email = user.email
    accounts.delete_account(db, user)
    auth_log.admin_action(db, request, "admin_rejected", admin, None, email)
    log.info("Admin %s rejected sign-up %s", admin.id, user_id)
    return {"ok": True}


class DeleteUser(BaseModel):
    confirm_email: str


@router.delete("/users/{user_id}")
def admin_delete_user(
    user_id: int, body: DeleteUser, request: Request, admin: User = Depends(admin_user), db: DbSession = Depends(get_db)
):
    user = _manageable(db, user_id, admin)
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="You can't delete your own account")
    if body.confirm_email.strip().lower() != user.email:
        raise HTTPException(status_code=400, detail="Type the user's email exactly to confirm")
    email = user.email
    accounts.delete_account(db, user)
    auth_log.admin_action(db, request, "admin_deleted", admin, None, email)
    log.info("Admin %s deleted user %s", admin.id, user_id)
    return {"ok": True}


@router.get("/storage")
def storage(_: User = Depends(admin_user), db: DbSession = Depends(get_db)):
    tables = {}
    for name, model in (
        ("Users", User),
        ("Activities", Activity),
        ("Wellness days", WellnessDay),
        ("Training plans", Plan),
        ("Connections", Connection),
        ("Sharing grants", Grant),
        ("Access log entries", AccessLog),
        ("AI calls", AiCall),
        ("Sign-in sessions", Session),
    ):
        tables[name] = db.scalar(select(func.count()).select_from(model))
    files = {}
    url = make_url(settings.db_url)
    if url.get_backend_name() == "sqlite" and url.database:
        for suffix in ("", "-wal", "-shm"):
            path = Path(url.database + suffix)
            if path.exists():
                files[path.name] = path.stat().st_size
    disk = shutil.disk_usage(settings.data_dir if Path(settings.data_dir).exists() else ".")
    return {
        "database_bytes": sum(files.values()),
        "files": files,
        "tables": tables,
        "disk": {"total": disk.total, "used": disk.used, "free": disk.free, "path": settings.data_dir},
    }


@router.patch("/users/{user_id}")
def update_user(
    user_id: int, body: UserUpdate, request: Request, admin: User = Depends(admin_user), db: DbSession = Depends(get_db)
):
    user = _manageable(db, user_id, admin)
    if user.id == admin.id and (body.is_admin is False or body.is_active is False or body.is_super_admin is False):
        raise HTTPException(status_code=400, detail="You can't remove your own admin rights or disable yourself")
    stays_super = user.is_super_admin if body.is_super_admin is None else body.is_super_admin
    if body.is_admin is False and stays_super:
        raise HTTPException(status_code=400, detail="Remove their super admin rights first")
    if body.is_super_admin is not None and body.is_super_admin != user.is_super_admin:
        if not admin.is_super_admin:
            raise HTTPException(status_code=403, detail="Only a super admin can make someone super admin")
        if body.is_super_admin and not user.approved:
            raise HTTPException(status_code=400, detail="Approve the account first")
        user.is_super_admin = body.is_super_admin
        if body.is_super_admin:
            user.is_admin = True
        auth_log.admin_action(db, request, "admin_super_on" if body.is_super_admin else "admin_super_off", admin, user)
    if body.is_admin is not None:
        user.is_admin = body.is_admin
    if body.is_active is False and user.is_active and user.is_admin and accounts.active_admins(db) <= 1:
        raise HTTPException(status_code=400, detail="That's the last admin: make someone else admin first")
    if body.is_active is not None and body.is_active != user.is_active:
        if body.is_active:
            accounts.enable(db, user)
        else:
            accounts.disable(db, user, body.disabled_reason)
        auth_log.admin_action(db, request, "admin_enabled" if body.is_active else "admin_disabled", admin, user)
    if body.emails_disabled is not None and body.emails_disabled != user.emails_disabled:
        user.emails_disabled = body.emails_disabled
        event = "admin_emails_off" if body.emails_disabled else "admin_emails_on"
        auth_log.admin_action(db, request, event, admin, user)
    if body.plan_approval_off is not None:
        user.plan_approval_off = body.plan_approval_off
    if body.ai_disabled is not None and body.ai_disabled != user.ai_disabled:
        user.ai_disabled = body.ai_disabled
        auth_log.admin_action(db, request, "admin_ai_off" if body.ai_disabled else "admin_ai_on", admin, user)
    if "ai_monthly_limit" in body.model_fields_set and body.ai_monthly_limit != user.ai_monthly_limit:
        user.ai_monthly_limit = body.ai_monthly_limit
        auth_log.admin_action(db, request, "admin_ai_limit", admin, user)
    db.commit()
    return {"ok": True}


@router.get("/sign-ins")
def sign_ins(
    q: str = "",
    event: str = "",
    failed: bool = False,
    days: int = Query(default=30, ge=1, le=3650),
    limit: int = Query(default=200, ge=1, le=1000),
    _: User = Depends(admin_user),
    db: DbSession = Depends(get_db),
):
    """The sign-in log, newest first. q matches the email or IP address."""
    query = select(AuthEvent).where(AuthEvent.at >= utcnow() - timedelta(days=days))
    if q.strip():
        like = f"%{q.strip().lower()}%"
        query = query.where(or_(AuthEvent.email.like(like), AuthEvent.ip.like(like)))
    if event:
        query = query.where(AuthEvent.event == event)
    if failed:
        query = query.where(AuthEvent.event.in_(auth_log.FAILURES))
    rows = db.scalars(query.order_by(AuthEvent.at.desc(), AuthEvent.id.desc()).limit(limit)).all()
    return {
        "events": [auth_log.out(e) for e in rows],
        "kinds": auth_log.EVENTS,
        "keep_days": runtime.get("auth_log_days"),
    }


# ---- Zwift / MyWhoosh workout catalog (platform_catalog.py) ----


@router.get("/platform-workouts")
def list_platform_workouts(_: User = Depends(admin_user), db: DbSession = Depends(get_db)):
    rows = db.scalars(select(PlatformWorkout).order_by(PlatformWorkout.platform, PlatformWorkout.name)).all()
    return {
        "enabled": platform_catalog.enabled(),
        "platforms": platform_catalog.PLATFORMS,
        "workouts": [platform_catalog.catalog_out(w) for w in rows],
    }


class ZwoFile(BaseModel):
    name: str = Field(max_length=255)
    content: str = Field(max_length=platform_catalog.MAX_FILE_BYTES)


class CatalogUpload(BaseModel):
    platform: str
    files: list[ZwoFile] = Field(min_length=1, max_length=200)


@router.post("/platform-workouts")
def upload_platform_workouts(body: CatalogUpload, admin: User = Depends(admin_user), db: DbSession = Depends(get_db)):
    """Add .zwo files to the catalog. A workout with the same name on that platform is replaced."""
    if body.platform not in platform_catalog.PLATFORMS:
        raise HTTPException(status_code=422, detail="Platform must be zwift or mywhoosh")
    counts, errors = {"added": 0, "updated": 0}, []
    for f in body.files:
        try:
            parsed = platform_catalog.parse_zwo(f.content)
        except platform_catalog.ZwoError as exc:
            errors.append({"file": f.name, "error": str(exc)})
            continue
        counts[platform_catalog.add(db, body.platform, parsed, admin.id)] += 1
        db.flush()  # a second file with the same name in this upload replaces the first
    db.commit()
    log.info("Admin %s uploaded platform workouts: %s, %d errors", admin.id, counts, len(errors))
    return {**counts, "errors": errors}


@router.delete("/platform-workouts/{workout_id}")
def delete_platform_workout(workout_id: int, admin: User = Depends(admin_user), db: DbSession = Depends(get_db)):
    """Remove from the catalog. Plan days already swapped to it keep their copy of the steps."""
    w = db.get(PlatformWorkout, workout_id)
    if w is None:
        raise HTTPException(status_code=404, detail="Workout not found")
    db.delete(w)
    db.commit()
    return {"ok": True}
