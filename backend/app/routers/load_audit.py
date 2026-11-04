"""Training load audit (load_audit.py): read only, for the athlete and anyone with their fitness and
activities shared."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from .. import load_audit
from ..db import User, get_db
from ..deps import current_user, require_scope, resolve_athlete_id

router = APIRouter(prefix="/api/athletes/{athlete}/load-audit", tags=["load audit"])


def _athlete(db: DbSession, user: User, athlete: str) -> User:
    athlete_id = resolve_athlete_id(athlete, user)
    require_scope(db, user, athlete_id, "fitness")
    require_scope(db, user, athlete_id, "activities")
    return db.get(User, athlete_id)


@router.get("")
def audit(
    athlete: str,
    days: int = Query(default=180, ge=7, le=730),
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    return load_audit.audit(db, _athlete(db, user, athlete), days)


@router.get("/{part}.csv")
def audit_csv(
    athlete: str,
    part: str,
    days: int = Query(default=180, ge=7, le=730),
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """The days (date, TSS, CTL, ATL, TSB) or the activities (source, IDs, status, TSS and method) as CSV."""
    if part not in ("days", "activities"):
        raise HTTPException(status_code=404, detail="Not found")
    a = _athlete(db, user, athlete)
    data = load_audit.audit(db, a, days)
    name = f"coachquest-load-{part}-{data['meta']['to']}.csv"
    return Response(
        load_audit.csv_text(data[part]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


class Other(BaseModel):
    csv: str = Field(min_length=10, max_length=5_000_000)
    days: int = Field(default=180, ge=7, le=730)


@router.post("/compare")
def compare(athlete: str, body: Other, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """Day by day against another platform's export (TrainingPeaks workouts or PMC CSV)."""
    a = _athlete(db, user, athlete)
    try:
        other = load_audit.parse_other(body.csv)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return load_audit.compare(load_audit.audit(db, a, body.days)["days"], other)
