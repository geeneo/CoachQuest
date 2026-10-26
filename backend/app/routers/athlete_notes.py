"""Athlete notes for the AI coach (see athlete_notes.py)."""

from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from .. import athlete_notes, localtime
from ..db import User, get_db
from ..deps import current_user, require_scope, resolve_athlete_id

router = APIRouter(prefix="/api/athletes/{athlete}/notes", tags=["athlete notes"])


def _athlete(db: DbSession, user: User, athlete: str) -> User:
    athlete_id = resolve_athlete_id(athlete, user)
    require_scope(db, user, athlete_id, "plans")
    return db.get(User, athlete_id)


def _list(db: DbSession, a: User) -> dict:
    return {
        "notes": athlete_notes.listing(db, a.id, localtime.today(a)),
        "categories": athlete_notes.CATEGORIES,
    }


@router.get("")
def list_notes(athlete: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    return _list(db, _athlete(db, user, athlete))


class NewNote(BaseModel):
    category: str
    body: str = Field(min_length=3, max_length=300)
    review_by: date | None = None


@router.post("")
def add_note(athlete: str, body: NewNote, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """The athlete and coaches with the plans scope can add notes."""
    a = _athlete(db, user, athlete)
    athlete_notes.add(db, user, a.id, body.category, body.body, body.review_by, localtime.today(a))
    return _list(db, a)


class EditNote(BaseModel):
    category: str | None = None
    body: str | None = Field(default=None, min_length=3, max_length=300)
    review_by: date | None = None


@router.patch("/{note_id}")
def edit_note(
    athlete: str, note_id: int, body: EditNote, user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    a = _athlete(db, user, athlete)
    n = athlete_notes.get(db, a.id, note_id)
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None or k == "review_by"}
    athlete_notes.change(db, user, n, changes, localtime.today(a))
    return _list(db, a)


@router.post("/{note_id}/confirm")
def confirm_note(athlete: str, note_id: int, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """Still true: the note goes back into AI requests."""
    a = _athlete(db, user, athlete)
    athlete_notes.confirm(db, user, athlete_notes.get(db, a.id, note_id), localtime.today(a))
    return _list(db, a)


@router.delete("/{note_id}")
def delete_note(athlete: str, note_id: int, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    a = _athlete(db, user, athlete)
    db.delete(athlete_notes.get(db, a.id, note_id))
    db.commit()
    return _list(db, a)
