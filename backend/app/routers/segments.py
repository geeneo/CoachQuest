"""An athlete's saved Strava segments (see segments.py). The athlete and coaches with the plans scope."""

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .. import segments
from ..db import Connection, Segment, User, get_db
from ..deps import current_user, require_scope, resolve_athlete_id
from ..providers import strava

router = APIRouter(prefix="/api/athletes/{athlete}/segments", tags=["segments"])


def _athlete_id(db: DbSession, user: User, athlete: str) -> int:
    athlete_id = resolve_athlete_id(athlete, user)
    require_scope(db, user, athlete_id, "plans")
    return athlete_id


@router.get("")
def list_segments(athlete: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    return [segments.segment_out(s) for s in segments.for_athlete(db, _athlete_id(db, user, athlete))]


class NewSegment(BaseModel):
    link: str = Field(min_length=3, max_length=300)
    name: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=300)


@router.post("")
async def add_segment(
    athlete: str, body: NewSegment, user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    """Save a segment from its Strava link; details come from Strava when the athlete's Strava is linked."""
    athlete_id = _athlete_id(db, user, athlete)
    sid = segments.strava_id(body.link)
    if sid is None:
        raise HTTPException(
            status_code=422, detail="Paste the segment's Strava link, e.g. https://www.strava.com/segments/1234567"
        )
    if db.scalar(select(Segment).where(Segment.athlete_id == athlete_id, Segment.strava_id == sid)):
        raise HTTPException(status_code=409, detail="That segment is already saved")
    details: dict = {}
    conn = db.scalar(
        select(Connection).where(
            Connection.user_id == athlete_id, Connection.provider == "strava", Connection.status == "active"
        )
    )
    if conn is not None:
        try:
            details = await strava.segment(db, conn, sid)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except (httpx.HTTPError, KeyError, ValueError):
            details = {}  # Strava unreachable: save it with the name given
    name = body.name.strip() or details.get("name") or f"Strava segment {sid}"
    s = Segment(
        athlete_id=athlete_id,
        strava_id=sid,
        added_by=user.id,
        notes=body.notes.strip(),
        **{**details, "name": name},
    )
    db.add(s)
    db.commit()
    return segments.segment_out(s)


class SegmentEdit(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=300)


def _own(db: DbSession, athlete_id: int, segment_id: int) -> Segment:
    s = db.get(Segment, segment_id)
    if s is None or s.athlete_id != athlete_id:
        raise HTTPException(status_code=404, detail="Segment not found")
    return s


@router.patch("/{segment_id}")
def edit_segment(
    athlete: str,
    segment_id: int,
    body: SegmentEdit,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    s = _own(db, _athlete_id(db, user, athlete), segment_id)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(s, k, v.strip())
    db.commit()
    return segments.segment_out(s)


@router.delete("/{segment_id}")
def delete_segment(athlete: str, segment_id: int, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """Plan days that named it keep their text; the link just stops showing."""
    db.delete(_own(db, _athlete_id(db, user, athlete), segment_id))
    db.commit()
    return {"ok": True}
