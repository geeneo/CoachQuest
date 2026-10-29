"""An athlete's health conditions (health.py): they edit them; a coach with the plans scope reads them."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session as DbSession

from .. import health
from ..db import User, get_db, utcnow
from ..deps import current_user, require_scope, resolve_athlete_id

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/athletes/{athlete}/health")
def get_health(athlete: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    athlete_id = resolve_athlete_id(athlete, user)
    if not health.can_see(db, user, athlete_id):
        raise HTTPException(status_code=404, detail="Athlete not found or not shared with you")
    require_scope(db, user, athlete_id, "plans")  # logs a coach's look in the athlete's access log
    return health.out(db.get(User, athlete_id))


class HealthIn(BaseModel):
    conditions: list[dict] = Field(default_factory=list, max_length=40)
    accept_disclaimer: bool = False

    @field_validator("conditions")
    @classmethod
    def _conditions(cls, v):
        return health.clean(v)


@router.put("/me/health")
def set_health(body: HealthIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """Only the athlete sets their conditions, after accepting the medical disclaimer once."""
    if body.accept_disclaimer and user.health_disclaimer_at is None:
        user.health_disclaimer_at = utcnow()
    if body.conditions and user.health_disclaimer_at is None:
        raise HTTPException(status_code=422, detail="Read and accept the medical disclaimer first")
    user.health_conditions = body.conditions
    db.commit()
    return health.out(user)
