"""Login, logout, registration, and the verify endpoint nginx calls."""

from datetime import timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from .. import runtime
from ..config import SESSION_COOKIE, settings
from ..db import Session, User, get_db, utcnow
from ..deps import current_user
from ..security import (
    DUMMY_HASH,
    hash_password,
    hash_token,
    new_session_token,
    proxy_secret_ok,
    verify_password,
)

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
        "ftp_watts": user.ftp_watts,
        "lthr_bpm": user.lthr_bpm,
        "max_hr_bpm": user.max_hr_bpm,
        "weight_kg": user.weight_kg,
        "weight_source": user.weight_source,
        "weight_updated_at": user.weight_updated_at,
        "goal": user.goal,
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


@router.post("/register")
def register(body: Registration, request: Request, response: Response, db: DbSession = Depends(get_db)):
    email = body.email.lower()
    is_admin = email in settings.admin_emails
    if runtime.get("registration_mode") != "open" and not is_admin:
        raise HTTPException(status_code=403, detail="Registration is closed")
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with that email already exists")
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        display_name=body.display_name.strip(),
        is_admin=is_admin,
    )
    db.add(user)
    db.commit()
    _start_session(db, user, response, request.headers.get("user-agent"))
    return user_out(user)


@router.post("/login")
def login(body: Credentials, request: Request, response: Response, db: DbSession = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    ok = verify_password(body.password, user.password_hash if user else DUMMY_HASH)
    if not user or not ok or not user.is_active:
        raise HTTPException(status_code=401, detail="Wrong email or password")
    _start_session(db, user, response, request.headers.get("user-agent"))
    return user_out(user)


@router.post("/logout")
def logout(request: Request, response: Response, db: DbSession = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.execute(delete(Session).where(Session.token_hash == hash_token(token)))
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.post("/logout-all")
def logout_all(response: Response, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    db.execute(delete(Session).where(Session.user_id == user.id))
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
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
    return {"ok": True}


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
    if user is None or not user.is_active:
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
