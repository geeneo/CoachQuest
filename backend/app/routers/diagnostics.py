"""Data health (diagnostics.py): the athlete, their coaches (activities shared) and admins."""

import json

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session as DbSession

from .. import diagnostics
from ..config import settings
from ..db import User, get_db
from ..deps import current_user, require_scope, resolve_athlete_id

router = APIRouter(prefix="/api/athletes/{athlete}/diagnostics", tags=["diagnostics"])


def _athlete(db: DbSession, user: User, athlete: str) -> User:
    athlete_id = resolve_athlete_id(athlete, user)
    require_scope(db, user, athlete_id, "activities")
    return db.get(User, athlete_id)


@router.get("")
def check(athlete: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    return diagnostics.check(db, _athlete(db, user, athlete))


@router.get("/report.json")
def report(athlete: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """Everything above, and the training load summary, as one file to send to support."""
    a = _athlete(db, user, athlete)
    body = json.dumps(diagnostics.report(db, a, settings.build_commit), indent=2, default=str)
    name = f"coachquest-diagnostics-{a.id}.json"
    return Response(
        body, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{name}"'}
    )
