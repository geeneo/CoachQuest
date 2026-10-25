"""Training preferences: what an athlete likes to do on each weekday, and their activity note tags.

Both feed the AI coach. The athlete edits; coaches with the plans scope can read.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import update
from sqlalchemy.orm import Session as DbSession

from ..db import Activity, User, get_db
from ..deps import current_user, require_scope, resolve_athlete_id

router = APIRouter(prefix="/api", tags=["preferences"])

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
SESSION_TYPES = (
    "Rest",
    "Road",
    "Gravel",
    "MTB",
    "E-MTB",
    "Hill repeats",
    "Zwift / indoor",
    "Treadmill run",
    "Outdoor run",
    "Trail run",
    "Swim",
    "Strength",
    "Yoga / mobility",
    "Race",
)
DEFAULT_NOTE_TAGS = [
    "illness",
    "mechanical",
    "travel",
    "weather",
    "adventure",
    "group",
    "solo",
    "wind",
    "work",
    "other",
]


def preferences_out(user: User) -> dict:
    return {
        "weekday_prefs": {d: (user.weekday_prefs or {}).get(d, []) for d in WEEKDAYS},
        "note_tags": user.note_tags if user.note_tags is not None else list(DEFAULT_NOTE_TAGS),
        "session_types": list(SESSION_TYPES),
    }


def _tag(value: str) -> str:
    tag = value.strip().lower()
    if not 1 <= len(tag) <= 30:
        raise ValueError("Tags are 1 to 30 characters")
    return tag


class PreferencesIn(BaseModel):
    weekday_prefs: dict[str, list[str]] | None = None
    note_tags: list[str] | None = Field(default=None, max_length=40)

    @field_validator("weekday_prefs")
    @classmethod
    def _prefs(cls, v):
        if v is None:
            return v
        bad_days = set(v) - set(WEEKDAYS)
        bad_types = {t for types in v.values() for t in types} - set(SESSION_TYPES)
        if bad_days or bad_types:
            raise ValueError(f"Unknown {'days' if bad_days else 'session types'}: {sorted(bad_days or bad_types)}")
        return {d: [t for t in SESSION_TYPES if t in v.get(d, [])] for d in WEEKDAYS}

    @field_validator("note_tags")
    @classmethod
    def _tags(cls, v):
        if v is None:
            return v
        tags = [_tag(t) for t in v]
        return list(dict.fromkeys(tags))  # unique, order kept


class TagRename(BaseModel):
    old: str
    new: str


@router.get("/athletes/{athlete}/preferences")
def get_preferences(athlete: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    athlete_id = resolve_athlete_id(athlete, user)
    require_scope(db, user, athlete_id, "plans")
    return preferences_out(db.get(User, athlete_id))


@router.put("/me/preferences")
def set_preferences(body: PreferencesIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    if body.weekday_prefs is not None:
        user.weekday_prefs = body.weekday_prefs
    if body.note_tags is not None:
        user.note_tags = body.note_tags
    db.commit()
    return preferences_out(user)


@router.post("/me/note-tags/rename")
def rename_tag(body: TagRename, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """Rename a tag everywhere: in the list and on activities already tagged with it."""
    try:
        old, new = _tag(body.old), _tag(body.new)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    tags = preferences_out(user)["note_tags"]
    if old not in tags:
        raise HTTPException(status_code=404, detail="No such tag")
    if new in tags and new != old:
        raise HTTPException(status_code=409, detail=f"You already have a tag called {new!r}")
    user.note_tags = [new if t == old else t for t in tags]
    db.execute(update(Activity).where(Activity.user_id == user.id, Activity.note_tag == old).values(note_tag=new))
    db.commit()
    return preferences_out(user)
