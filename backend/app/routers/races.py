"""Races / events per athlete. The athlete edits; coaches with the plans scope can read."""

import re
from datetime import date, time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from ..db import Race, User, get_db
from ..deps import current_user, require_scope, resolve_athlete_id

router = APIRouter(prefix="/api", tags=["races"])

DISCIPLINES = (
    "Road",
    "Mountain bike",
    "Gravel",
    "Track",
    "Run",
    "Trail run",
    "Ultra",
    "Triathlon",
    "Duathlon",
    "Swim / open water",
    "Multisport",
    "Other",
)


class RaceFields(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=20)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    short_name: str | None = Field(default=None, max_length=20)
    distance_km: float | None = Field(default=None, ge=0, le=10000)
    elevation_m: float | None = Field(default=None, ge=0, le=100000)
    discipline: str | None = None
    target_date: date | None = None
    start_time: time | None = None
    target_ctl: int | None = Field(default=None, ge=0, le=250)
    days: int | None = Field(default=None, ge=1, le=60)
    active: bool | None = None

    @field_validator("code")
    @classmethod
    def _code(cls, v):
        if v is not None and not re.fullmatch(r"[a-z0-9][a-z0-9-]*", v.strip().lower()):
            raise ValueError("Use lowercase letters, numbers and dashes, e.g. k2c or cape-town")
        return v.strip().lower() if v else v

    @field_validator("discipline")
    @classmethod
    def _discipline(cls, v):
        if v is not None and v not in DISCIPLINES:
            raise ValueError(f"Discipline must be one of: {', '.join(DISCIPLINES)}")
        return v


class RaceCreate(RaceFields):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=120)


def race_out(r: Race, today: date | None = None) -> dict:
    today = today or date.today()
    return {
        "id": r.id,
        "code": r.code,
        "name": r.name,
        "short_name": r.short_name,
        "distance_km": r.distance_km,
        "elevation_m": r.elevation_m,
        "discipline": r.discipline,
        "target_date": r.target_date,
        "start_time": r.start_time,
        "target_ctl": r.target_ctl,
        "days": r.days,
        "active": r.active,
        "days_to_go": (r.target_date - today).days if r.target_date else None,
    }


def upcoming(db: DbSession, athlete_id: int, today: date | None = None) -> list[Race]:
    today = today or date.today()
    rows = db.scalars(
        select(Race)
        .where(Race.user_id == athlete_id, Race.active, Race.target_date >= today)
        .order_by(Race.target_date)
    ).all()
    return list(rows)


def _own(db: DbSession, race_id: int, user: User) -> Race:
    race = db.get(Race, race_id)
    if race is None or race.user_id != user.id:
        raise HTTPException(status_code=404, detail="Race not found")
    return race


def _apply(race: Race, fields: dict) -> None:
    for key, value in fields.items():
        if key == "start_time":
            value = value.strftime("%H:%M") if value else None
        if key == "short_name" and value is None:
            value = ""
        setattr(race, key, value)


@router.get("/races/disciplines")
def disciplines(_: User = Depends(current_user)):
    return list(DISCIPLINES)


@router.get("/athletes/{athlete}/races")
def list_races(athlete: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    athlete_id = resolve_athlete_id(athlete, user)
    require_scope(db, user, athlete_id, "plans")
    rows = db.scalars(
        select(Race).where(Race.user_id == athlete_id).order_by(Race.target_date.is_(None), Race.target_date)
    ).all()
    return [race_out(r) for r in rows]


@router.post("/races")
def create_race(body: RaceCreate, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    race = Race(user_id=user.id, code=body.code, name=body.name)
    _apply(race, body.model_dump(exclude_unset=True))
    db.add(race)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"You already have a race with the code {body.code!r}") from None
    return race_out(race)


@router.patch("/races/{race_id}")
def update_race(race_id: int, body: RaceFields, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    race = _own(db, race_id, user)
    _apply(race, body.model_dump(exclude_unset=True))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Another race already uses that code") from None
    return race_out(race)


@router.delete("/races/{race_id}")
def delete_race(race_id: int, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    race = _own(db, race_id, user)
    db.delete(race)
    db.commit()
    return {"ok": True}
