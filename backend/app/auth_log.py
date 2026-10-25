"""Sign-in log: who signed in (or tried to), when, from where, and other account events.

Kept as long as Admin > Settings > "Keep sign-in log for" says (90 days by
default; 0 = keep), then deleted by a nightly job, which also trims the coach
access log. Only what an audit needs: no passwords, and the IP address and
browser only for that long. Sign-ins blocked by nginx's rate limit never reach
the API, so they aren't in here.
"""

from datetime import timedelta

from fastapi import Request
from sqlalchemy import delete
from sqlalchemy.orm import Session as DbSession

from . import runtime
from .db import AccessLog, AuthEvent, SessionLocal, User, utcnow
from .security import proxy_secret_ok

EVENTS = {
    "login_ok": "Signed in",
    "login_failed": "Wrong email or password",
    "login_pending": "Tried to sign in while waiting for approval",
    "login_disabled": "Tried to sign in to a disabled account",
    "registered": "Created an account",
    "logout": "Signed out",
    "logout_all": "Signed out everywhere",
    "password_changed": "Changed their password",
    "reset_requested": "Asked for a password reset link",
    "password_reset": "Reset their password with a link",
    "admin_password_set": "Password set by an admin",
    "admin_reset_link": "Reset link created by an admin",
    "admin_approved": "Approved by an admin",
    "admin_rejected": "Sign-up rejected by an admin",
    "admin_disabled": "Disabled by an admin",
    "admin_enabled": "Enabled by an admin",
    "admin_deleted": "Deleted by an admin",
}
FAILURES = {"login_failed", "login_pending", "login_disabled"}


def client_ip(request: Request) -> str | None:
    """The browser's address as nginx saw it (X-Real-IP), trusted only on requests that came through nginx."""
    if proxy_secret_ok(request.headers.get("x-proxy-secret")) and request.headers.get("x-real-ip"):
        return request.headers["x-real-ip"][:45]
    return request.client.host[:45] if request.client else None


def record(
    db: DbSession,
    request: Request | None,
    event: str,
    user: User | None = None,
    email: str | None = None,
    detail: str = "",
) -> None:
    db.add(
        AuthEvent(
            user_id=user.id if user else None,
            email=(email or (user.email if user else "") or "")[:255].lower(),
            event=event,
            ip=client_ip(request) if request else None,
            user_agent=(request.headers.get("user-agent") or "")[:255] if request else "",
            detail=detail[:255],
        )
    )
    db.commit()


def admin_action(
    db: DbSession, request: Request, event: str, admin: User, target: User | None, email: str = ""
) -> None:
    record(db, request, event, target, email or (target.email if target else ""), f"by {admin.email}")


def out(e: AuthEvent) -> dict:
    return {
        "id": e.id,
        "at": e.at,
        "event": e.event,
        "label": EVENTS.get(e.event, e.event),
        "failed": e.event in FAILURES,
        "user_id": e.user_id,
        "email": e.email,
        "ip": e.ip,
        "user_agent": e.user_agent,
        "detail": e.detail,
    }


def _days(key: str) -> int | None:
    raw = runtime.get(key)
    try:
        return int(raw) if raw not in ("", None) else None
    except ValueError:
        return None


def purge(db: DbSession) -> dict:
    """Delete sign-in log entries (and coach access log entries) older than the retention."""
    removed = {}
    days = _days("auth_log_days")
    if days:
        removed["sign_ins"] = db.execute(
            delete(AuthEvent).where(AuthEvent.at < utcnow() - timedelta(days=days))
        ).rowcount
    access_days = _days("access_log_days") or days
    if access_days:
        removed["access"] = db.execute(
            delete(AccessLog).where(AccessLog.at < utcnow() - timedelta(days=access_days))
        ).rowcount
    db.commit()
    return removed


def purge_job() -> None:
    with SessionLocal() as db:
        purge(db)
