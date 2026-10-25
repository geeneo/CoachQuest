"""Comments on AI coach notes and calendar workouts (plans have their own URLs in plans.py)."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from .. import comments
from ..db import User, get_db
from ..deps import current_user, require_scope, resolve_athlete_id

router = APIRouter(prefix="/api/athletes/{athlete}/comments", tags=["comments"])


def _athlete_id(db: DbSession, user: User, athlete: str) -> int:
    athlete_id = resolve_athlete_id(athlete, user)
    require_scope(db, user, athlete_id, "plans")
    return athlete_id


def _target(target: str) -> str:
    if target not in comments.TARGETS:
        raise HTTPException(status_code=422, detail=f"target must be one of {', '.join(comments.TARGETS)}")
    return target


@router.get("")
def list_comments(
    athlete: str, target: str, target_id: int, user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    athlete_id = _athlete_id(db, user, athlete)
    comments.resolve(db, _target(target), target_id, athlete_id)
    return comments.for_target(db, target, target_id)


class NewComment(BaseModel):
    target: str
    target_id: int
    body: str = Field(min_length=1, max_length=4000)


@router.post("")
def add_comment(
    athlete: str,
    body: NewComment,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """The athlete and coaches with the plans scope can comment; the others are emailed."""
    athlete_id = _athlete_id(db, user, athlete)
    comments.add(db, background, user, athlete_id, _target(body.target), body.target_id, body.body)
    return comments.for_target(db, body.target, body.target_id)


class EditComment(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


@router.patch("/{comment_id}")
def edit_comment(
    athlete: str,
    comment_id: int,
    body: EditComment,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    athlete_id = _athlete_id(db, user, athlete)
    c = comments.get(db, athlete_id, comment_id)
    comments.edit(db, user, c, body.body)
    return comments.for_target(db, c.target, c.target_id)


@router.delete("/{comment_id}")
def delete_comment(athlete: str, comment_id: int, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    athlete_id = _athlete_id(db, user, athlete)
    c = comments.get(db, athlete_id, comment_id)
    target, target_id = c.target, c.target_id
    db.delete(c)
    db.commit()
    return comments.for_target(db, target, target_id)
