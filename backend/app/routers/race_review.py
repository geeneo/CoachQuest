"""After a race (race_review.py): the post-race update, earlier years, segments, weather and other riders.

The athlete reads and writes; coaches with the plans and activities scopes read. Only the athlete's own
look fetches anything from Strava (segment times, with their link) or lists other riders (who shared with
them, not with the coach)."""

import asyncio
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session as DbSession

from .. import localtime, race_review
from ..db import Activity, Race, User, get_db
from ..deps import current_user, require_scope, resolve_athlete_id
from ..race_estimate import format_time, parse_time
from .races import race_out

router = APIRouter(prefix="/api", tags=["race review"])


def _race(db: DbSession, viewer: User, athlete: str, race_id: int) -> tuple[Race, User]:
    athlete_id = resolve_athlete_id(athlete, viewer)
    require_scope(db, viewer, athlete_id, "plans")
    if athlete_id != viewer.id:
        require_scope(db, viewer, athlete_id, "activities")
    race = db.get(Race, race_id)
    if race is None or race.user_id != athlete_id:
        raise HTTPException(status_code=404, detail="Race not found")
    return race, db.get(User, athlete_id)


def result_out(race: Race) -> dict:
    res = dict(race.result or {})
    res["official_time"] = format_time(res.get("official_s"))
    res["riders"] = [{**r, "time": format_time(r.get("time_s"))} for r in res.get("riders") or []]
    return res


@router.get("/athletes/{athlete}/races/{race_id}/review")
async def review(athlete: str, race_id: int, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    race, owner = _race(db, user, athlete, race_id)
    own = owner.id == user.id
    tz = localtime.zone(owner.timezone)
    today = localtime.today(owner)
    cands = race_review.candidates(db, owner, race)
    ride = race_review.pick_ride(race, cands)
    earlier = race_review.editions(db, owner, race, ride)
    rides = ([ride] if ride else []) + earlier
    notes = await race_review.fill_details(db, owner.id, rides) if own and rides else []
    ctl = race_review.ctl_before(db, owner.id, [localtime.local_date(a.start_time, tz) for a in rides])
    stats = [race_review.ride_stats(db, a, tz, ctl.get(localtime.local_date(a.start_time, tz))) for a in rides]
    me = stats[0] if ride else None
    segments = race_review.segment_table(
        [(str(s["year"]), race_review.detail_of(db, a)) for s, a in zip(stats, rides, strict=True)]
    )
    others = race_review.other_riders(db, owner, race, ride) if own else []
    result = race.result or {}
    if race.target_date and race.target_date > today:
        notes.insert(0, "The race is still to come: this fills in on the day.")
    elif ride is None and race.target_date:
        notes.insert(0, "No ride on the race's day yet: once it syncs from Strava or Garmin it shows here.")
    return {
        "race": race_out(race, today),
        "own": own,
        "athlete": {"id": owner.id, "name": owner.display_name},
        "result": result_out(race),
        "ride": me,
        "candidates": [
            {
                "activity_id": a.id,
                "name": a.name,
                "date": localtime.local_date(a.start_time, tz).isoformat(),
                "distance_km": round(a.distance_m / 1000, 1),
                "minutes": round((a.duration_s or 0) / 60),
            }
            for a in cands
        ],
        "earlier": stats[1:],
        "segments": segments,
        "laps": (race_review.detail_of(db, ride) or {}).get("laps", []) if ride else [],
        "others": others,
        "standings": race_review.standings(me, result, others),
        "notes": notes,
    }


@router.get("/athletes/{athlete}/races/{race_id}/review/weather")
async def review_weather(
    athlete: str, race_id: int, user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    """The weather each ride of the race had (this year and earlier ones), by activity id. Slow (a weather
    request per ride), so the page asks for it after the rest."""
    race, owner = _race(db, user, athlete, race_id)
    today = localtime.today(owner)
    ride = race_review.pick_ride(race, race_review.candidates(db, owner, race))
    rides = ([ride] if ride else []) + race_review.editions(db, owner, race, ride)
    found = await asyncio.gather(*(race_review.weather_for(db, a, today) for a in rides))
    return {str(a.id): w for a, w in zip(rides, found, strict=True)}


class TypedRider(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    time: str = Field(min_length=1, max_length=10)
    category: str | None = Field(default=None, max_length=40)
    note: str | None = Field(default=None, max_length=200)

    @field_validator("time")
    @classmethod
    def _time(cls, v):
        parse_time(v)
        return v


class PostRace(BaseModel):
    activity_id: int | None = None
    official_time: str | None = Field(default=None, max_length=10)
    position: int | None = Field(default=None, ge=1, le=100000)
    field_size: int | None = Field(default=None, ge=1, le=100000)
    category: str | None = Field(default=None, max_length=40)
    category_position: int | None = Field(default=None, ge=1, le=100000)
    category_size: int | None = Field(default=None, ge=1, le=100000)
    feeling: int | None = Field(default=None, ge=1, le=5)
    went_well: str | None = Field(default=None, max_length=2000)
    went_badly: str | None = Field(default=None, max_length=2000)
    nutrition: str | None = Field(default=None, max_length=2000)
    problems: str | None = Field(default=None, max_length=2000)
    next_time: str | None = Field(default=None, max_length=2000)
    riders: list[TypedRider] | None = Field(default=None, max_length=50)

    @field_validator("official_time")
    @classmethod
    def _official(cls, v):
        parse_time(v)
        return v


@router.put("/races/{race_id}/result")
def save_result(race_id: int, body: PostRace, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """The post-race update: only the fields sent change; an empty value clears one."""
    race = db.get(Race, race_id)
    if race is None or race.user_id != user.id:
        raise HTTPException(status_code=404, detail="Race not found")
    res = dict(race.result or {})
    fields = body.model_dump(exclude_unset=True)
    if "activity_id" in fields:
        aid = fields.pop("activity_id")
        if aid is not None and aid not in {a.id for a in race_review.candidates(db, user, race)}:
            raise HTTPException(status_code=422, detail="Pick one of your sessions on the race's day")
        old = db.get(Activity, res.get("activity_id")) if res.get("activity_id") else None
        if old is not None and old.race_id == race.id:
            old.race_id = None
        new = db.get(Activity, aid) if aid else None
        if new is not None:
            new.race_id = race.id
        res["activity_id"] = aid
    if "official_time" in fields:
        res["official_s"] = parse_time(fields.pop("official_time"))
    if "riders" in fields:
        res["riders"] = [
            {
                "name": r["name"].strip(),
                "time_s": parse_time(r["time"]),
                "category": r.get("category"),
                "note": r.get("note"),
            }
            for r in fields.pop("riders") or []
        ]
    for k, v in fields.items():
        res[k] = v.strip() if isinstance(v, str) else v
    res = {k: v for k, v in res.items() if v not in (None, "", [])}
    res["updated_at"] = date.today().isoformat()
    race.result = res
    db.commit()
    return result_out(race)
