"""Login, logout, registration, and the verify endpoint nginx calls."""

import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from .. import accounts, auth_log, datefmt, mailer, profile_sync, runtime
from ..config import SESSION_COOKIE, settings
from ..db import AuthEvent, Session, User, get_db, utcnow
from ..deps import current_user
from ..security import (
    DUMMY_HASH,
    hash_password,
    hash_token,
    new_session_token,
    proxy_secret_ok,
    verify_password,
)

log = logging.getLogger("coachquest.auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])
internal = APIRouter(prefix="/internal/auth", include_in_schema=False)


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class Registration(Credentials):
    password: str = Field(min_length=12, max_length=256)
    display_name: str = Field(min_length=1, max_length=100)


def user_out(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "is_admin": user.is_admin,
        "is_super_admin": user.is_super_admin,
        "ftp_watts": user.ftp_watts,
        "lthr_bpm": user.lthr_bpm,
        "max_hr_bpm": user.max_hr_bpm,
        "weight_kg": user.weight_kg,
        "weight_source": user.weight_source,
        "weight_updated_at": user.weight_updated_at,
        "profile_sources": user.profile_sources or {},
        "goal": user.goal,
        "week_start": user.week_start or 0,
        "notify_sharing": user.notify_sharing,
        "notify_comments": user.notify_comments,
        "timezone": user.timezone,
        "emails_disabled": user.emails_disabled,
        "date_format": datefmt.date_format(user),
        "time_format": datefmt.time_format(user),
        "birth_date": user.birth_date,
        "age": profile_sync.age(user.birth_date),
    }


def _start_session(db: DbSession, user: User, response: Response, user_agent: str | None) -> None:
    token = new_session_token()
    db.add(
        Session(
            token_hash=hash_token(token),
            user_id=user.id,
            expires_at=utcnow() + timedelta(hours=settings.session_ttl_hours),
            user_agent=(user_agent or "")[:255],
        )
    )
    db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


PENDING_MESSAGE = (
    "Thanks for signing up. An administrator needs to approve your account; you'll get an email when it's ready."
)


ALPHA_NOTICE = "CoachQuest is an alpha version: things can change or break. Access is subject to approval."


def alpha_notice_on() -> bool:
    """Admin → Settings → "Alpha notice for new users" (super admins only)."""
    return runtime.get("alpha_notice") == "on"


async def _send_alpha_notice(user: User) -> None:
    """Welcome email for a new sign-up while the alpha notice is on."""
    status = (
        "Your account is waiting for approval. You'll get another email when it's ready."
        if not user.approved
        else "Your account is active, but it can be paused or removed while CoachQuest is in alpha."
    )
    try:
        await mailer.send(
            user.email,
            "Welcome to CoachQuest (alpha version)",
            f"Hi {user.display_name},\n\n"
            "Thanks for signing up to CoachQuest.\n\n"
            "Please note:\n"
            "- CoachQuest is an alpha version. Features can change and things may break.\n"
            "- Your access is subject to approval.\n\n"
            f"{status}\n\n{settings.public_base_url}\n",
        )
    except mailer.MailError as exc:
        log.warning("Could not send the alpha notice to new user %s: %s", user.id, exc)


@router.get("/notice")
def sign_up_notice():
    """Public: what the sign-up page shows above the form."""
    return {"message": ALPHA_NOTICE if alpha_notice_on() else None}


async def _tell_admins_about(db: DbSession, user: User) -> None:
    """Email the admins who can approve: only super admins while "Super admin approves new sign-ups" is on."""
    who = User.is_super_admin if accounts.super_approval_on() else User.is_admin
    admins = db.scalars(select(User).where(who, User.is_active, User.emails_disabled.is_(False))).all()
    for admin in admins:
        try:
            await mailer.send(
                admin.email,
                f"CoachQuest: {user.display_name} is waiting for approval",
                f"{user.display_name} ({user.email}) signed up and is waiting for approval.\n\n"
                f"Approve or reject them under Admin → Users: {settings.public_base_url}/admin\n",
            )
        except mailer.MailError as exc:
            log.warning("Could not email admin %s about sign-up %s: %s", admin.id, user.id, exc)


@router.post("/register")
async def register(body: Registration, request: Request, response: Response, db: DbSession = Depends(get_db)):
    email = body.email.lower()
    is_super = email in settings.super_admin_emails
    is_admin = is_super or email in settings.admin_emails
    mode = runtime.get("registration_mode")
    if mode == "closed" and not is_admin:
        raise HTTPException(status_code=403, detail="Registration is closed")
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with that email already exists")
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        display_name=body.display_name.strip(),
        is_admin=is_admin,
        is_super_admin=is_super,
        approved=is_admin or (mode != "approval" and not accounts.super_approval_on()),
    )
    db.add(user)
    db.commit()
    auth_log.record(db, request, "registered", user, detail="" if user.approved else "waiting for approval")
    if alpha_notice_on():
        await _send_alpha_notice(user)
    if not user.approved:
        await _tell_admins_about(db, user)
        return {"pending": True, "message": PENDING_MESSAGE}
    _start_session(db, user, response, request.headers.get("user-agent"))
    return user_out(user)


@router.post("/login")
def login(body: Credentials, request: Request, response: Response, db: DbSession = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    ok = verify_password(body.password, user.password_hash if user else DUMMY_HASH)
    if not user or not ok:
        auth_log.record(db, request, "login_failed", user, email=body.email)
        raise HTTPException(status_code=401, detail="Wrong email or password")
    if not user.is_active:
        auth_log.record(db, request, "login_disabled", user)
        # Only after the right password, so this doesn't tell strangers which emails have accounts.
        raise HTTPException(
            status_code=403,
            detail="This account is paused. Ask your CoachQuest administrator to turn it back on.",
        )
    if not user.approved:
        auth_log.record(db, request, "login_pending", user)
        raise HTTPException(status_code=403, detail="Your account is waiting for an administrator to approve it.")
    _start_session(db, user, response, request.headers.get("user-agent"))
    auth_log.record(db, request, "login_ok", user)
    return user_out(user)


@router.post("/logout")
def logout(request: Request, response: Response, db: DbSession = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        s = db.scalar(select(Session).where(Session.token_hash == hash_token(token)))
        if s is not None:
            auth_log.record(db, request, "logout", db.get(User, s.user_id))
        db.execute(delete(Session).where(Session.token_hash == hash_token(token)))
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.post("/logout-all")
def logout_all(
    request: Request, response: Response, user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    db.execute(delete(Session).where(Session.user_id == user.id))
    db.commit()
    auth_log.record(db, request, "logout_all", user)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


class PauseAccount(BaseModel):
    confirm_email: EmailStr


@router.post("/pause")
def pause_account(
    body: PauseAccount,
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """Pause your own account: signed out everywhere, nothing runs for it; an admin turns it back on."""
    if body.confirm_email.lower() != user.email:
        raise HTTPException(status_code=422, detail="Type your own email address to confirm")
    if user.is_admin and accounts.active_admins(db) <= 1:
        raise HTTPException(status_code=400, detail="You're the only admin: make someone else admin first")
    if user.is_super_admin and accounts.active_super_admins(db) <= 1:
        raise HTTPException(status_code=400, detail="You're the only super admin: make someone else super admin first")
    accounts.disable(db, user, "Paused by themselves", by_self=True)
    auth_log.record(db, request, "paused_self", user)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


class ForgotPassword(BaseModel):
    email: EmailStr


FORGOT_REPLY = {
    "ok": True,
    "message": "If that email has a CoachQuest account, a reset link is on its way. "
    "It works once and expires in 30 minutes. Check your spam folder too.",
}


@router.post("/forgot")
async def forgot_password(body: ForgotPassword, request: Request, db: DbSession = Depends(get_db)):
    """Always gives the same answer, so it can't be used to find out who has an account."""
    user = db.scalar(select(User).where(User.email == body.email.lower(), User.is_active))
    auth_log.record(db, request, "reset_requested", user, email=body.email, detail="" if user else "no such account")
    if user is not None:
        link = accounts.create_reset_link(db, user, accounts.SELF_SERVICE_TTL)
        try:
            await accounts.email_reset_link(user, link, accounts.SELF_SERVICE_TTL, by_admin=False)
        except mailer.MailError as exc:
            log.warning("Password reset email for user %s not sent: %s", user.id, exc)
    return FORGOT_REPLY


class ResetPassword(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    new_password: str = Field(min_length=12, max_length=256)


@router.post("/reset")
def reset_password(body: ResetPassword, request: Request, db: DbSession = Depends(get_db)):
    user = accounts.use_reset_token(db, body.token, body.new_password)
    if user is None:
        raise HTTPException(
            status_code=400, detail="This reset link is invalid, already used or expired. Ask for a new one."
        )
    auth_log.record(db, request, "password_reset", user)
    return {"ok": True}


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


@router.post("/password")
def change_password(
    body: PasswordChange, request: Request, user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    """Change your own password. Other devices are signed out; this one stays signed in."""
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is wrong")
    if body.new_password == body.current_password:
        raise HTTPException(status_code=400, detail="Choose a password different from the current one")
    user.password_hash = hash_password(body.new_password)
    this = hash_token(request.cookies.get(SESSION_COOKIE, ""))
    db.execute(delete(Session).where(Session.user_id == user.id, Session.token_hash != this))
    db.commit()
    auth_log.record(db, request, "password_changed", user)
    return {"ok": True}


@router.get("/sign-ins")
def my_sign_ins(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """Your own recent sign-ins and account events, to spot one that wasn't you."""
    rows = db.scalars(
        select(AuthEvent)
        .where(AuthEvent.user_id == user.id)
        .order_by(AuthEvent.at.desc(), AuthEvent.id.desc())
        .limit(30)
    ).all()
    return [auth_log.out(e) for e in rows]


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_out(user)


@internal.get("/verify")
def verify(
    request: Request,
    db: DbSession = Depends(get_db),
    x_proxy_secret: str | None = Header(default=None),
):
    """nginx `auth_request` target. 200 + identity headers, or 401."""
    if not proxy_secret_ok(x_proxy_secret):
        raise HTTPException(status_code=401)
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401)
    session = db.scalar(select(Session).where(Session.token_hash == hash_token(token)))
    now = utcnow()
    if session is None or session.expires_at < now:
        raise HTTPException(status_code=401)
    user = db.get(User, session.user_id)
    if user is None or not user.is_active or not user.approved:
        raise HTTPException(status_code=401)
    # Write at most once a minute so every request doesn't hit the disk.
    if (now - session.last_seen_at).total_seconds() > 60:
        session.last_seen_at = now
        db.commit()
    return Response(
        status_code=200,
        headers={
            "X-Auth-User-Id": str(user.id),
            "X-Auth-Is-Admin": "1" if user.is_admin else "0",
        },
    )
