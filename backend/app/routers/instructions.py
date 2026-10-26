"""Standing coach instructions for the AI coach (see instructions.py)."""

from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from .. import instructions, localtime
from ..db import User, get_db
from ..deps import current_user, require_scope, resolve_athlete_id

router = APIRouter(prefix="/api/athletes/{athlete}/instructions", tags=["instructions"])


def _athlete(db: DbSession, user: User, athlete: str) -> User:
    athlete_id = resolve_athlete_id(athlete, user)
    require_scope(db, user, athlete_id, "plans")
    return db.get(User, athlete_id)


def _list(db: DbSession, athlete: User) -> list[dict]:
    return instructions.listing(db, athlete.id, localtime.today(athlete))


@router.get("")
def list_instructions(athlete: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    return _list(db, _athlete(db, user, athlete))


class NewInstruction(BaseModel):
    body: str = Field(min_length=3, max_length=500)
    until: date | None = None


@router.post("")
def add_instruction(
    athlete: str,
    body: NewInstruction,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """The athlete and coaches with the plans scope can add them; the others are emailed."""
    a = _athlete(db, user, athlete)
    instructions.add(db, background, user, a.id, body.body, body.until)
    return _list(db, a)


class EditInstruction(BaseModel):
    body: str | None = Field(default=None, min_length=3, max_length=500)
    until: date | None = None
    active: bool | None = None


@router.patch("/{instruction_id}")
def edit_instruction(
    athlete: str,
    instruction_id: int,
    body: EditInstruction,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    a = _athlete(db, user, athlete)
    i = instructions.get(db, a.id, instruction_id)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("body") is None:
        changes.pop("body", None)
    if changes.get("active") is None:
        changes.pop("active", None)
    instructions.change(db, background, user, i, changes)
    return _list(db, a)


@router.delete("/{instruction_id}")
def delete_instruction(
    athlete: str, instruction_id: int, user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    a = _athlete(db, user, athlete)
    db.delete(instructions.get(db, a.id, instruction_id))
    db.commit()
    return _list(db, a)
