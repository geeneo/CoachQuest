"""Athletes share selected data with coaches."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session as DbSession

from ..db import AccessLog, Grant, User, get_db, utcnow
from ..deps import SCOPES, current_user

router = APIRouter(prefix="/api/grants", tags=["sharing"])


def _clean_scopes(scopes: list[str]) -> list[str]:
    bad = set(scopes) - set(SCOPES)
    if bad:
        raise ValueError(f"Unknown scopes: {', '.join(sorted(bad))}")
    if not scopes:
        raise ValueError("Pick at least one scope")
    return [s for s in SCOPES if s in scopes]


class GrantUpdate(BaseModel):
    scopes: list[str]

    @field_validator("scopes")
    @classmethod
    def _check_scopes(cls, v: list[str]) -> list[str]:
        return _clean_scopes(v)


class GrantCreate(GrantUpdate):
    coach_email: EmailStr


def grant_out(g: Grant, db: DbSession) -> dict:
    athlete, coach = db.get(User, g.athlete_id), db.get(User, g.coach_id)
    return {
        "id": g.id,
        "status": g.status,
        "scopes": g.scopes,
        "athlete": {"id": athlete.id, "display_name": athlete.display_name, "email": athlete.email},
        "coach": {"id": coach.id, "display_name": coach.display_name, "email": coach.email},
        "created_at": g.created_at,
        "updated_at": g.updated_at,
    }


@router.get("")
def list_grants(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    rows = db.scalars(
        select(Grant)
        .where(or_(Grant.athlete_id == user.id, Grant.coach_id == user.id), Grant.status != "revoked")
        .order_by(Grant.created_at.desc())
    ).all()
    return {
        "given": [grant_out(g, db) for g in rows if g.athlete_id == user.id],
        "received": [grant_out(g, db) for g in rows if g.coach_id == user.id],
        "scopes": list(SCOPES),
    }


@router.post("")
def create_grant(body: GrantCreate, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    coach = db.scalar(select(User).where(User.email == body.coach_email.lower(), User.is_active))
    if coach is None:
        raise HTTPException(
            status_code=404, detail="No CoachQuest account with that email. Ask your coach to register first."
        )
    if coach.id == user.id:
        raise HTTPException(status_code=400, detail="You can't share with yourself")
    existing = db.scalar(
        select(Grant).where(Grant.athlete_id == user.id, Grant.coach_id == coach.id, Grant.status != "revoked")
    )
    if existing:
        existing.scopes = body.scopes
        existing.updated_at = utcnow()
        db.commit()
        return grant_out(existing, db)
    grant = Grant(athlete_id=user.id, coach_id=coach.id, scopes=body.scopes, status="pending")
    db.add(grant)
    db.commit()
    return grant_out(grant, db)


def _own(db: DbSession, grant_id: int, user: User) -> Grant:
    g = db.get(Grant, grant_id)
    if g is None or user.id not in (g.athlete_id, g.coach_id) or g.status == "revoked":
        raise HTTPException(status_code=404, detail="Grant not found")
    return g


@router.patch("/{grant_id}")
def update_scopes(
    grant_id: int, body: GrantUpdate, user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    g = _own(db, grant_id, user)
    if g.athlete_id != user.id:
        raise HTTPException(status_code=403, detail="Only the athlete can change what is shared")
    g.scopes = body.scopes
    g.updated_at = utcnow()
    db.commit()
    return grant_out(g, db)


@router.post("/{grant_id}/accept")
def accept(grant_id: int, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    g = _own(db, grant_id, user)
    if g.coach_id != user.id or g.status != "pending":
        raise HTTPException(status_code=400, detail="Only the invited coach can accept a pending invitation")
    g.status = "active"
    g.updated_at = utcnow()
    db.commit()
    return grant_out(g, db)


@router.delete("/{grant_id}")
def revoke(grant_id: int, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """Either side can end the relationship at any time. Takes effect on the next request."""
    g = _own(db, grant_id, user)
    g.status = "revoked"
    g.updated_at = utcnow()
    db.commit()
    return {"ok": True}


@router.get("/access-log")
def access_log(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    rows = db.scalars(
        select(AccessLog).where(AccessLog.athlete_id == user.id).order_by(AccessLog.at.desc()).limit(200)
    ).all()
    names = {u.id: u.display_name for u in db.scalars(select(User).where(User.id.in_({r.viewer_id for r in rows})))}
    return [{"viewer": names.get(r.viewer_id, "?"), "resource": r.resource, "at": r.at} for r in rows]
