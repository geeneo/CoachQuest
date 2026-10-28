"""An athlete's favourite Strava routes and segments (see segments.py).

The athlete and coaches with the plans scope; friends only look.
"""

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


def _strava(db: DbSession, athlete_id: int) -> Connection | None:
    return db.scalar(
        select(Connection).where(
            Connection.user_id == athlete_id, Connection.provider == "strava", Connection.status == "active"
        )
    )


@router.get("")
def list_segments(athlete: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    athlete_id = _athlete_id(db, user, athlete)
    return {
        "favourites": [segments.segment_out(s) for s in segments.for_athlete(db, athlete_id)],
        "uses": list(segments.USES),
        "strava_linked": _strava(db, athlete_id) is not None,
    }


@router.get("/strava")
async def from_strava(athlete: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """The athlete's starred segments and routes on Strava that aren't favourites yet."""
    athlete_id = _athlete_id(db, user, athlete)
    conn = _strava(db, athlete_id)
    if conn is None:
        raise HTTPException(status_code=409, detail="Strava isn't linked: connect it on Connections first")
    try:
        found = await strava.favourites(db, conn)
    except (httpx.HTTPError, LookupError, KeyError, TypeError, ValueError):
        raise HTTPException(status_code=502, detail="Strava didn't answer; try again in a minute") from None
    have = {(s.kind, s.strava_id) for s in segments.for_athlete(db, athlete_id)}
    return [f for f in found if (f["kind"], f["strava_id"]) not in have]


class NewFavourite(BaseModel):
    link: str = Field(min_length=3, max_length=300)
    name: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=300)
    uses: list[str] = Field(default_factory=list, max_length=8)


@router.post("")
async def add_segment(
    athlete: str, body: NewFavourite, user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    """Save a route or segment from its Strava link; details come from Strava when the athlete's Strava is linked."""
    athlete_id = _athlete_id(db, user, athlete)
    parsed = segments.parse_link(body.link)
    if parsed is None:
        raise HTTPException(
            status_code=422,
            detail="Paste a Strava route or segment link, e.g. https://www.strava.com/segments/1234567",
        )
    kind, sid = parsed
    if db.scalar(select(Segment).where(Segment.athlete_id == athlete_id, Segment.strava_id == sid)):
        raise HTTPException(status_code=409, detail=f"That {kind} is already a favourite")
    details: dict = {}
    conn = _strava(db, athlete_id)
    if conn is not None:
        try:
            details = await (strava.route if kind == "route" else strava.segment)(db, conn, sid)
        except LookupError:
            raise HTTPException(status_code=404, detail=f"Strava doesn't know that {kind} (or it's private)") from None
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            details = {}  # Strava unreachable or answered oddly: save it with the name given
    # Your name if given, else Strava's, else a placeholder.
    name = body.name.strip() or details.get("name") or f"Strava {kind} {sid}"
    details = {k: v for k, v in details.items() if k not in ("kind", "strava_id", "name")}
    s = Segment(
        athlete_id=athlete_id,
        strava_id=sid,
        kind=kind,
        name=name,
        added_by=user.id,
        notes=body.notes.strip(),
        uses=segments.clean_uses(body.uses),
        **details,
    )
    db.add(s)
    db.commit()
    return segments.segment_out(s)


class FavouriteEdit(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=300)
    uses: list[str] | None = Field(default=None, max_length=8)


def _own(db: DbSession, athlete_id: int, segment_id: int) -> Segment:
    s = db.get(Segment, segment_id)
    if s is None or s.athlete_id != athlete_id:
        raise HTTPException(status_code=404, detail="Favourite not found")
    return s


@router.patch("/{segment_id}")
def edit_segment(
    athlete: str,
    segment_id: int,
    body: FavouriteEdit,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    s = _own(db, _athlete_id(db, user, athlete), segment_id)
    changes = body.model_dump(exclude_none=True)
    if "uses" in changes:
        s.uses = segments.clean_uses(changes.pop("uses"))
    for k, v in changes.items():
        setattr(s, k, v.strip())
    db.commit()
    return segments.segment_out(s)


@router.delete("/{segment_id}")
def delete_segment(athlete: str, segment_id: int, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """Plan days that named it keep their text; the link just stops showing."""
    db.delete(_own(db, _athlete_id(db, user, athlete), segment_id))
    db.commit()
    return {"ok": True}
