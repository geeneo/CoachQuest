"""Request identity and access control.

Authentication happens in nginx: every protected request first goes through
`auth_request` to /internal/auth/verify. On success nginx forwards the user id
in X-Auth-User-Id together with X-Proxy-Secret. This module trusts that header
only when the secret matches, so a request that reaches the API without going
through nginx carries no identity.

Authorization (who may see which athlete's data) is decided here, per request,
from the grants table.
"""

from contextvars import ContextVar

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import runtime
from .db import AccessLog, Grant, User, get_db
from .security import proxy_secret_ok

# "profile" = FTP, threshold/max HR and goal; "weight" is separate because it is more personal.
SCOPES = ("activities", "fitness", "wellness", "profile", "weight", "plans")


def current_user(
    request: Request,
    db: DbSession = Depends(get_db),
    x_proxy_secret: str | None = Header(default=None),
    x_auth_user_id: str | None = Header(default=None),
) -> User:
    if not proxy_secret_ok(x_proxy_secret) or not x_auth_user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        user_id = int(x_auth_user_id)
    except ValueError:
        raise HTTPException(status_code=401, detail="Not authenticated") from None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    return user


COACH, FRIEND = "coach", "friend"


def active_grant(db: DbSession, athlete_id: int, coach_id: int) -> Grant | None:
    return db.scalar(
        select(Grant).where(
            Grant.athlete_id == athlete_id,
            Grant.coach_id == coach_id,
            Grant.status == "active",
        )
    )


# Set per request by the middleware in main.py: True for GET / HEAD.
READ_REQUEST: ContextVar[bool] = ContextVar("read_request", default=False)


def allowed_scopes(db: DbSession, viewer: User, athlete_id: int) -> set[str]:
    """Scopes `viewer` holds on `athlete_id`. An athlete holds every scope on themself.

    With the admin_view_data setting on, admins can look at any athlete's data,
    read only: on a GET they hold every
    scope, on anything that changes data only what a grant gives them. Their
    looks are written to the athlete's access log like a coach's.
    """
    if viewer.id == athlete_id:
        return set(SCOPES)
    if (
        viewer.is_admin
        and READ_REQUEST.get()
        and runtime.get("admin_view_data") == "on"
        and db.get(User, athlete_id) is not None
    ):
        return set(SCOPES)
    grant = active_grant(db, athlete_id, viewer.id)
    athlete = db.get(User, athlete_id) if grant else None
    if athlete is None or not athlete.is_active:
        return set()  # a paused or disabled athlete's data isn't shown to coaches
    if grant.role == FRIEND and not READ_REQUEST.get():
        return set()  # friends only look
    return set(grant.scopes) & set(SCOPES)


def is_friend(db: DbSession, viewer: User, athlete_id: int) -> bool:
    """Does `viewer` see this athlete's data as a friend (view only), not as their coach?"""
    grant = active_grant(db, athlete_id, viewer.id) if viewer.id != athlete_id else None
    return grant is not None and grant.role == FRIEND


def require_scope(db: DbSession, viewer: User, athlete_id: int, scope: str) -> None:
    """Raise 404 (not 403) so a coach can't probe which user ids exist."""
    if scope not in allowed_scopes(db, viewer, athlete_id):
        if not READ_REQUEST.get() and is_friend(db, viewer, athlete_id):
            raise HTTPException(status_code=403, detail="View only: you can look at this, not change it")
        raise HTTPException(status_code=404, detail="Athlete not found or not shared with you")
    if viewer.id != athlete_id:
        db.add(AccessLog(athlete_id=athlete_id, viewer_id=viewer.id, resource=scope))
        db.commit()


def resolve_athlete_id(athlete: str, viewer: User) -> int:
    if athlete == "me":
        return viewer.id
    try:
        return int(athlete)
    except ValueError:
        raise HTTPException(status_code=404, detail="Athlete not found") from None
