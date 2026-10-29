"""An athlete's favourite Strava routes and segments (see segments.py).

The athlete and coaches with the plans scope; friends only look.
"""

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .. import segments
from ..db import Activity, Connection, Segment, User, get_db
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
    """The athlete's starred segments and routes on Strava that aren't favourites yet, and whether
    private routes are among them (links made before read_all was asked for only show public ones)."""
    athlete_id = _athlete_id(db, user, athlete)
    conn = _strava(db, athlete_id)
    if conn is None:
        raise HTTPException(status_code=409, detail="Strava isn't linked: connect it on Connections first")
    try:
        found = await strava.favourites(db, conn)
    except (httpx.HTTPError, LookupError, KeyError, TypeError, ValueError):
        raise HTTPException(status_code=502, detail="Strava didn't answer; try again in a minute") from None
    have = {(s.kind, s.strava_id) for s in segments.for_athlete(db, athlete_id)}
    return {
        # Strava ids as text: route ids are longer than a browser number keeps exactly.
        "found": [{**f, "strava_id": str(f["strava_id"])} for f in found if (f["kind"], f["strava_id"]) not in have],
        "private_routes": strava.sees_private_routes(conn),
    }


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
            detail="Paste a Strava route, segment or ride link, e.g. https://www.strava.com/routes/… "
            "or https://www.strava.com/activities/…",
        )
    kind, sid = parsed
    if db.scalar(select(Segment).where(Segment.athlete_id == athlete_id, Segment.strava_id == sid)):
        raise HTTPException(status_code=409, detail=f"That {kind} is already a favourite")
    details: dict = _imported_ride(db, athlete_id, sid) if kind == "ride" else {}
    conn = _strava(db, athlete_id)
    if conn is not None and not details:
        fetch = {"route": strava.route, "segment": strava.segment, "ride": strava.activity}[kind]
        try:
            details = await fetch(db, conn, sid)
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


class StravaPick(BaseModel):
    kind: str = Field(pattern="^(route|segment)$")
    strava_id: int  # sent as text by the browser (see from_strava); read as a whole number


class FromStrava(BaseModel):
    items: list[StravaPick] = Field(min_length=1, max_length=200)
    uses: list[str] = Field(default_factory=list, max_length=8)


# What a pick is for when none is ticked: routes are rides, segments are efforts.
DEFAULT_USES = {"route": ["endurance"], "segment": ["hill repeats"]}


@router.post("/from-strava")
async def add_from_strava(
    athlete: str, body: FromStrava, user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    """Save several of the athlete's Strava routes and starred segments at once.

    Details come from Strava's list (one call each for segments and routes), not from the request;
    ones already saved are skipped."""
    athlete_id = _athlete_id(db, user, athlete)
    conn = _strava(db, athlete_id)
    if conn is None:
        raise HTTPException(status_code=409, detail="Strava isn't linked: connect it on Connections first")
    try:
        found = await strava.favourites(db, conn)
    except (httpx.HTTPError, LookupError, KeyError, TypeError, ValueError):
        raise HTTPException(status_code=502, detail="Strava didn't answer; try again in a minute") from None
    wanted = {(p.kind, p.strava_id) for p in body.items}
    have = {s.strava_id for s in segments.for_athlete(db, athlete_id)}
    uses = segments.clean_uses(body.uses)
    added = []
    for f in found:
        if (f["kind"], f["strava_id"]) not in wanted or f["strava_id"] in have:
            continue
        have.add(f["strava_id"])
        details = {k: v for k, v in f.items() if k not in ("kind", "strava_id", "name")}
        s = Segment(
            athlete_id=athlete_id,
            strava_id=f["strava_id"],
            kind=f["kind"],
            name=f["name"] or f"Strava {f['kind']} {f['strava_id']}",
            added_by=user.id,
            uses=uses or DEFAULT_USES[f["kind"]],
            **details,
        )
        db.add(s)
        added.append(s)
    db.commit()
    return {"added": [segments.segment_out(s) for s in added]}


def _imported_ride(db: DbSession, athlete_id: int, strava_id: int) -> dict:
    """A ride the athlete did, from the activities already imported from Strava (no Strava call)."""
    a = db.scalar(
        select(Activity).where(
            Activity.user_id == athlete_id, Activity.source == "strava", Activity.external_id == str(strava_id)
        )
    )
    if a is None:
        return {}
    return {
        "name": (a.name or "")[:120],
        "distance_m": round(a.distance_m or 0) or None,
        "elevation_m": round(a.elevation_m or 0) or None,
        "est_minutes": round(a.duration_s / 60) if a.duration_s else None,
        "sport": "run" if "Run" in (a.sport or "") else "ride",
    }


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
