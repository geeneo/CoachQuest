"""Races / events per athlete. The athlete edits; coaches with the plans scope can read."""

import re
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from .. import localtime, pacing, race_stages, segments
from ..activity_types import category
from ..db import Plan, Race, Segment, User, get_db
from ..deps import current_user, require_scope, resolve_athlete_id
from ..queries import activities_since
from ..race_estimate import estimate, format_time, parse_time

router = APIRouter(prefix="/api", tags=["races"])

DISCIPLINES = (
    "Road",
    "Mountain bike",
    "Gravel",
    "Track",
    "Run",
    "Trail run",
    "Ultra",
    "Triathlon",
    "Duathlon",
    "Swim / open water",
    "Multisport",
    "Other",
)


class RaceFields(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=20)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    short_name: str | None = Field(default=None, max_length=20)
    distance_km: float | None = Field(default=None, ge=0, le=10000)
    elevation_m: float | None = Field(default=None, ge=0, le=100000)
    discipline: str | None = None
    target_date: date | None = None
    start_time: time | None = None
    target_ctl: int | None = Field(default=None, ge=0, le=250)
    target_time: str | None = Field(default=None, max_length=10)  # finish time, h:mm or h:mm:ss
    days: int | None = Field(default=None, ge=1, le=60)
    active: bool | None = None
    # One of the athlete's saved routes (Routes page), or null for none.
    segment_id: int | None = None

    @field_validator("code")
    @classmethod
    def _code(cls, v):
        if v is not None and not re.fullmatch(r"[a-z0-9][a-z0-9-]*", v.strip().lower()):
            raise ValueError("Use lowercase letters, numbers and dashes, e.g. k2c or cape-town")
        return v.strip().lower() if v else v

    @field_validator("target_time")
    @classmethod
    def _target_time(cls, v):
        parse_time(v)  # raises ValueError with a hint
        return v

    @field_validator("discipline")
    @classmethod
    def _discipline(cls, v):
        if v is not None and v not in DISCIPLINES:
            raise ValueError(f"Discipline must be one of: {', '.join(DISCIPLINES)}")
        return v


class RaceCreate(RaceFields):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=120)


def race_out(r: Race, today: date | None = None) -> dict:
    today = today or date.today()
    return {
        "id": r.id,
        "code": r.code,
        "name": r.name,
        "short_name": r.short_name,
        "distance_km": r.distance_km,
        "elevation_m": r.elevation_m,
        "discipline": r.discipline,
        "target_date": r.target_date,
        "start_time": r.start_time,
        "target_ctl": r.target_ctl,
        "target_time": format_time(r.target_seconds),
        "ctl_advice": r.ctl_advice,
        "days": r.days,
        "active": r.active,
        "days_to_go": (r.target_date - today).days if r.target_date else None,
        # A multi-day event: each day, and the totals with its longest and hardest day.
        "stages": race_stages.with_dates(r.stages, r.target_date),
        "stage_totals": race_stages.totals(r.stages or []),
        "segment_id": r.segment_id,
    }


def upcoming(db: DbSession, athlete_id: int, today: date | None = None) -> list[Race]:
    """Active races still to come, or under way (a stage race on its third day)."""
    today = today or date.today()
    rows = db.scalars(
        select(Race)
        .where(Race.user_id == athlete_id, Race.active, Race.target_date >= today - timedelta(days=60))
        .order_by(Race.target_date)
    ).all()
    return [r for r in rows if race_stages.last_day(r) >= today]


def _logged(db: DbSession, athlete: User, races: list[Race], out: list[dict]) -> None:
    """After (and during) a stage race: what was logged on each of its days."""
    today = localtime.today(athlete)
    started = [r for r in races if r.stages and r.target_date and r.target_date <= today]
    if not started:
        return
    first = min(r.target_date for r in started)
    tz = localtime.zone(athlete.timezone)
    by_day: dict[str, list] = {}
    since = datetime.combine(first - timedelta(days=1), datetime.min.time())
    for a in activities_since(db, athlete.id, since):
        by_day.setdefault(localtime.local_date(a.start_time, tz).isoformat(), []).append(a)
    for item in out:
        for s in item["stages"]:
            acts = by_day.get(s["date"] or "", [])
            if acts:
                s["logged"] = {
                    "km": round(sum(a.distance_m for a in acts) / 1000, 1),
                    "elevation_m": round(sum(a.elevation_m for a in acts)),
                    "minutes": round(sum(a.duration_s for a in acts) / 60),
                    "types": sorted({category(a) for a in acts}),
                }


def _own(db: DbSession, race_id: int, user: User) -> Race:
    race = db.get(Race, race_id)
    if race is None or race.user_id != user.id:
        raise HTTPException(status_code=404, detail="Race not found")
    return race


def _check_route(db: DbSession, user: User, fields: dict) -> None:
    sid = fields.get("segment_id")
    if sid is not None and sid not in {s.id for s in segments.for_athlete(db, user.id)}:
        raise HTTPException(status_code=422, detail="That route isn't one of your saved routes")


def _tag_race(db: DbSession, race: Race) -> None:
    """The race's route gets the "race" tag on the Routes page (it's a race course)."""
    seg = db.get(Segment, race.segment_id) if race.segment_id else None
    if seg is not None and "race" not in (seg.uses or []):
        seg.uses = segments.clean_uses([*(seg.uses or []), "race"])


def _route_to_plan(db: DbSession, race: Race) -> None:
    """The race's route changed: plan days linked to the race (today and later) ride the new one."""
    today = date.today().isoformat()
    for p in db.scalars(select(Plan).where(Plan.athlete_id == race.user_id, Plan.weeks.is_not(None))):
        weeks, changed = [dict(w, days=[dict(d) for d in w["days"]]) for w in p.weeks or []], False
        for w in weeks:
            for d in w["days"]:
                if d.get("race_id") == race.id and d["date"] >= today and d.get("segment_id") != race.segment_id:
                    d["segment_id"], changed = race.segment_id, True
        if changed:
            p.weeks = weeks


def _apply(race: Race, fields: dict) -> None:
    for key, value in fields.items():
        if key == "start_time":
            value = value.strftime("%H:%M") if value else None
        if key == "short_name" and value is None:
            value = ""
        if key == "target_time":
            key, value = "target_seconds", parse_time(value)
        setattr(race, key, value)


@router.get("/races/disciplines")
def disciplines(_: User = Depends(current_user)):
    return list(DISCIPLINES)


@router.get("/athletes/{athlete}/races")
def list_races(athlete: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    athlete_id = resolve_athlete_id(athlete, user)
    require_scope(db, user, athlete_id, "plans")
    rows = db.scalars(
        select(Race).where(Race.user_id == athlete_id).order_by(Race.target_date.is_(None), Race.target_date)
    ).all()
    # What the target time asks for (power, pace): the athlete's own view, as it uses their weight and FTP.
    out = [race_out(r) for r in rows]
    _logged(db, db.get(User, athlete_id), list(rows), out)
    if athlete_id == user.id:
        return [{**o, "estimate": estimate(r, user)} for o, r in zip(out, rows, strict=True)]
    return out


@router.post("/races")
def create_race(body: RaceCreate, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    race = Race(user_id=user.id, code=body.code, name=body.name)
    fields = body.model_dump(exclude_unset=True)
    _check_route(db, user, fields)
    _apply(race, fields)
    _tag_race(db, race)
    db.add(race)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"You already have a race with the code {body.code!r}") from None
    return race_out(race)


@router.patch("/races/{race_id}")
def update_race(race_id: int, body: RaceFields, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    race = _own(db, race_id, user)
    fields = body.model_dump(exclude_unset=True)
    _check_route(db, user, fields)
    _apply(race, fields)
    if "segment_id" in fields:
        _route_to_plan(db, race)
        _tag_race(db, race)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Another race already uses that code") from None
    return race_out(race)


class Stages(BaseModel):
    stages: list[dict] = Field(default_factory=list, max_length=race_stages.MAX_STAGES)


@router.put("/races/{race_id}/stages")
def set_stages(race_id: int, body: Stages, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """Save a multi-day event's days (all at once); an empty list makes it a one-day race again.
    The race's distance, climbing and number of days become the stages' totals."""
    race = _own(db, race_id, user)
    try:
        stages = race_stages.clean(body.stages)
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    race.stages = stages or None
    tot = race_stages.totals(stages)
    if tot:
        race.days, race.distance_km, race.elevation_m = tot["days"], tot["distance_km"], tot["elevation_m"]
    elif not stages:
        race.days = 1
    db.commit()
    return race_out(race)


@router.delete("/races/{race_id}/ctl-advice")
def dismiss_advice(race_id: int, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    race = _own(db, race_id, user)
    race.ctl_advice = None
    db.commit()
    return race_out(race)


@router.delete("/races/{race_id}")
def delete_race(race_id: int, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    race = _own(db, race_id, user)
    db.delete(race)
    db.commit()
    return {"ok": True}


async def _pacing(db: DbSession, race: Race, user: User, group: str, stops: int) -> tuple[list, dict]:
    from .weather import _line_for_favourite  # Strava's line for a route saved without one

    if not race.target_seconds:
        raise HTTPException(status_code=422, detail="Set a target time for the race first (Races page)")
    seg = db.get(Segment, race.segment_id) if race.segment_id else None
    if seg is None or seg.kind == "segment":
        raise HTTPException(status_code=422, detail="Pick the race's route first (Races page → Route)")
    try:
        points = pacing.route_points(await _line_for_favourite(db, race.user_id, seg))
        heights = await pacing.elevations(points)
        return points, pacing.plan(points, heights, race, user, group, stops)
    except pacing.PacingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


PacingGroup = Query(default="team", pattern="^(alone|team|bunch)$")
PacingStops = Query(default=0, ge=0, le=600)


@router.get("/races/{race_id}/pacing")
async def race_pacing(
    race_id: int,
    group: str = PacingGroup,
    stops: int = PacingStops,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """The pacing plan on the race's route for its target time (pacing.py)."""
    race = _own(db, race_id, user)
    _, p = await _pacing(db, race, user, group, stops)
    return pacing.public(p)


@router.get("/races/{race_id}/pacing.{fmt}")
async def race_pacing_file(
    race_id: int,
    fmt: str,
    group: str = PacingGroup,
    stops: int = PacingStops,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """The pacing course for a Garmin Edge (FIT: the Virtual Partner rides the plan) or as GPX."""
    if fmt not in ("fit", "gpx"):
        raise HTTPException(status_code=404, detail="Not found")
    race = _own(db, race_id, user)
    points, p = await _pacing(db, race, user, group, stops)
    name = race.short_name or race.code.upper()
    filename = f"{race.code}-pacing.{fmt}"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if fmt == "fit":
        return Response(pacing.course_fit(points, p, name), media_type="application/vnd.ant.fit", headers=headers)
    return Response(pacing.course_gpx(points, p, race.name), media_type="application/gpx+xml", headers=headers)
