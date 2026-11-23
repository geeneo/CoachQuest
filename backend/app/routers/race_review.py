"""After a race (race_review.py): the post-race update, earlier years, segments, weather and other riders.

The athlete reads and writes; coaches with the plans and activities scopes, and admins while they may view
athletes' data, read. Segment times are fetched from Strava with each rider's own link, once, whoever looks.
Other riders are those the viewer may see (race_review.visible_riders)."""

import asyncio
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session as DbSession

from .. import localtime, race_analysis, race_debrief, race_results, race_review
from ..coach import CoachError
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


Stage = Query(default=None, ge=1, le=60, description="A stage race's day: that day's review")


def _view(race: Race, stage: int | None):
    """The race, or one stage of it as a one-day race (race_review.stage_view)."""
    try:
        return race_review.view_of(race, stage)
    except ValueError:
        raise HTTPException(status_code=404, detail="No such stage") from None


def result_out(race: Race) -> dict:
    res = dict(race.result or {})
    res.pop("results", None)  # the official results are large: the review has them in short (results)
    res["official_time"] = format_time(res.get("official_s"))
    res["riders"] = [{**r, "time": format_time(r.get("time_s"))} for r in res.get("riders") or []]
    return res


@router.get("/athletes/{athlete}/races/{race_id}/review")
async def review(
    athlete: str,
    race_id: int,
    stage: int | None = Stage,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    race, owner = _race(db, user, athlete, race_id)
    view = _view(race, stage)  # a stage race's day: its own ride, years, segments, weather and riders
    own = owner.id == user.id
    tz = localtime.zone(owner.timezone)
    today = localtime.today(owner)
    cands = race_review.candidates(db, owner, view)
    ride = race_review.pick_ride(view, cands)
    earlier = race_review.editions(db, owner, view, ride)
    rides = ([ride] if ride else []) + earlier
    # The segment times of the athlete's rides, with their Strava link, whoever looks (they may see them):
    # otherwise earlier years stay empty until the athlete opens the review themself. The notes (e.g. "link
    # Strava") are for the athlete.
    fetched = await race_review.fill_details(db, owner.id, rides) if rides else []
    notes = fetched if own else []
    ctl = race_review.ctl_before(db, owner.id, [localtime.local_date(a.start_time, tz) for a in rides])
    stats = [race_review.ride_stats(db, a, tz, ctl.get(localtime.local_date(a.start_time, tz))) for a in rides]
    me = stats[0] if ride else None
    others = race_review.other_riders(db, user, owner, view, ride)
    await race_review.fill_rider_details(db, others)
    columns = [
        {"key": str(s["year"]), "label": str(s["year"]), "kind": "race" if i == 0 and ride else "year"}
        for i, s in enumerate(stats)
    ]
    rider_rows = []
    for o in others:
        d = race_review.detail_of(db, db.get(Activity, o["activity_id"]))
        if d is not None:
            key = f"rider-{o['athlete_id']}"
            columns.append({"key": key, "label": o["name"], "kind": "rider"})
            rider_rows.append((key, d))
    segments = race_review.segment_table(
        [(str(s["year"]), race_review.detail_of(db, a)) for s, a in zip(stats, rides, strict=True)], rider_rows
    )
    result = race.result or {}
    # A stage's standings go by the day's rides: the official time and typed riders are the whole event's.
    standing_result = {} if stage else result
    if view.target_date and view.target_date > today:
        notes.insert(0, "The race is still to come: this fills in on the day.")
    elif ride is None and view.target_date:
        notes.insert(0, "No ride on the race's day yet: once it syncs from Strava or Garmin it shows here.")
    return {
        "race": race_out(race, today),
        "stages": race_review.riding_stages(race),
        "stage": view.stage if stage else None,
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
        "segment_columns": columns,
        "laps": (race_review.detail_of(db, ride) or {}).get("laps", []) if ride else [],
        "others": others,
        "standings": race_review.standings(me, standing_result, others, "You" if own else owner.display_name),
        "results": race_results.summary(result.get("results")),
        "notes": notes,
    }


@router.get("/athletes/{athlete}/races/{race_id}/review/weather")
async def review_weather(
    athlete: str,
    race_id: int,
    stage: int | None = Stage,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """The weather each ride of the race had (this year and earlier ones), by activity id. Slow (a weather
    request per ride), so the page asks for it after the rest."""
    race, owner = _race(db, user, athlete, race_id)
    view = _view(race, stage)
    today = localtime.today(owner)
    ride = race_review.pick_ride(view, race_review.candidates(db, owner, view))
    rides = ([ride] if ride else []) + race_review.editions(db, owner, view, ride)
    found = await asyncio.gather(*(race_review.weather_for(db, a, today) for a in rides))
    out = {}
    for a, w in zip(rides, found, strict=True):
        if w and not w.get("error"):
            # What the wind cost (or gave) each year, for the moving time ridden (race_analysis.py).
            w["wind"] = race_analysis.wind_effect(a.distance_m, a.duration_s, w.pop("head_kmh", []), race, owner)
        out[str(a.id)] = w
    return out


@router.get("/athletes/{athlete}/races/{race_id}/review/pacing")
async def review_pacing(
    athlete: str,
    race_id: int,
    stage: int | None = Stage,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """The pacing plan for the race's target time against the race as ridden (race_analysis.py): the
    checkpoints' planned and actual times and the climbs' target and actual power. Asked for after the
    rest of the page (it fetches the route, and the race's track from Strava once)."""
    race, owner = _race(db, user, athlete, race_id)
    if stage:
        _view(race, stage)
        return {"available": False, "why": "A pacing plan is for a one-day race's target time, not a stage."}
    return await _plan_vs_race(db, race, owner)


async def _plan_vs_race(db: DbSession, race: Race, owner: User) -> dict:
    from .races import _pacing

    ride = race_review.pick_ride(race, race_review.candidates(db, owner, race))
    if ride is None:
        return {"available": False, "why": "No ride on the race's day yet."}
    if not race.target_seconds or not race.segment_id:
        return {"available": False, "why": "Set the race's target time and route (Races page) to compare a plan."}
    copy = race_review.strava_copy(db, ride)
    note = await race_analysis.fill_track(db, owner.id, copy)
    track = (copy.detail or {}).get("track") if copy is not None else None
    if not track:
        return {"available": False, "why": note or "The race's power and timing come from Strava: link it."}
    stopped = max(0, (ride.elapsed_s or ride.duration_s or 0) - (ride.duration_s or 0))
    try:
        _, plan = await _pacing(db, race, owner, None, min(600, round(stopped / 60)))
    except HTTPException as exc:
        return {"available": False, "why": exc.detail}
    return {"available": True, **race_analysis.plan_vs_race(plan, track)}


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
def save_result(
    race_id: int,
    body: PostRace,
    stage: int | None = Stage,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """The post-race update: only the fields sent change; an empty value clears one. With `stage`, only the
    ride picked for that day of a stage race (the rest is the whole event's)."""
    race = db.get(Race, race_id)
    if race is None or race.user_id != user.id:
        raise HTTPException(status_code=404, detail="Race not found")
    res = dict(race.result or {})
    fields = body.model_dump(exclude_unset=True)
    if stage:
        view = _view(race, stage)
        aid = fields.get("activity_id")
        if set(fields) - {"activity_id"}:
            raise HTTPException(status_code=422, detail="For a stage, only its ride can be picked")
        if aid is not None and aid not in {a.id for a in race_review.candidates(db, user, view)}:
            raise HTTPException(status_code=422, detail="Pick one of your sessions on that day")
        rides = dict(res.get("stage_rides") or {})
        if aid is None:
            rides.pop(str(stage), None)
        else:
            rides[str(stage)] = aid
        res["stage_rides"] = rides
        race.result = {k: v for k, v in res.items() if v not in (None, "", [], {})}
        db.commit()
        return result_out(race)
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


@router.get("/admin/race-reviews")
def admin_race_reviews(
    days: int = Query(default=365, ge=7, le=3650),
    only_updates: bool = True,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """Admin: every athlete's post-race updates (Admin → Race reviews). Only while admins may view athletes'
    data (admin_view_data), like every other look at an athlete's data."""
    if not user.is_admin:
        raise HTTPException(status_code=404, detail="Not found")
    if not race_review.admin_sees_all(user):
        raise HTTPException(
            status_code=403, detail='Turn on "admins can view athletes\' data" (Admin → Settings) to see them'
        )
    today = date.today()
    return race_review.all_reviews(db, user, today - timedelta(days=days), today, only_updates)


@router.post("/races/{race_id}/debrief")
async def write_debrief(
    race_id: int, stage: int | None = Stage, user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    """The AI coach's debrief of the athlete's own race, or of one day of a stage race (race_debrief.py),
    kept with the race."""
    race = db.get(Race, race_id)
    if race is None or race.user_id != user.id:
        raise HTTPException(status_code=404, detail="Race not found")
    view = _view(race, stage)
    data = await review("me", race_id, stage, user, db)
    weather = await review_weather("me", race_id, stage, user, db)
    plan = {"available": False} if stage else await _plan_vs_race(db, race, user)
    try:
        f = race_debrief.facts(view, data, weather, plan)
        return await race_debrief.write(db, race, user, user, f, stage)
    except CoachError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


class ResultsPaste(BaseModel):
    text: str = Field(min_length=1, max_length=4_000_000)


class ResultsMe(BaseModel):
    index: int | None = Field(default=None, ge=0, le=race_results.MAX_ROWS)


def _own_race(db: DbSession, user: User, race_id: int) -> Race:
    race = db.get(Race, race_id)
    if race is None or race.user_id != user.id:
        raise HTTPException(status_code=404, detail="Race not found")
    return race


def _place_me(race: Race, stored: dict) -> None:
    """The athlete's place from the results into their post-race update, where it's still empty."""
    s = race_results.summary(stored) or {}
    if s.get("me") is None:
        return
    res = dict(race.result or {})
    fill = {
        "official_s": s.get("time_s"),
        "position": s.get("position"),
        "field_size": s.get("field"),
        "category": s.get("category"),
        "category_position": s.get("category_position"),
        "category_size": s.get("category_size"),
    }
    for k, v in fill.items():
        if v and not res.get(k):
            res[k] = v
    race.result = res


@router.put("/races/{race_id}/results")
def import_results(
    race_id: int, body: ResultsPaste, user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    """The official results, pasted (race_results.py): kept with the race, the athlete found and placed."""
    race = _own_race(db, user, race_id)
    try:
        rows = race_results.parse(body.text)
    except race_results.ResultsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    res = race.result or {}
    ride = race_review.pick_ride(race, race_review.candidates(db, user, race))
    me = race_results.find_me(rows, user.display_name, res.get("official_s"), ride.elapsed_s if ride else None)
    stored = {"rows": rows, "me": me, "imported_at": date.today().isoformat()}
    race.result = {**res, "results": stored}
    _place_me(race, stored)
    db.commit()
    return race_results.summary(stored)


@router.put("/races/{race_id}/results/me")
def results_me(race_id: int, body: ResultsMe, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """The athlete points at their own line in the results (when the name didn't find it)."""
    race = _own_race(db, user, race_id)
    stored = dict((race.result or {}).get("results") or {})
    if not stored.get("rows"):
        raise HTTPException(status_code=409, detail="Import the results first")
    if body.index is not None and body.index >= len(stored["rows"]):
        raise HTTPException(status_code=422, detail="No such line in the results")
    stored["me"] = body.index
    race.result = {**(race.result or {}), "results": stored}
    _place_me(race, stored)
    db.commit()
    return race_results.summary(stored)


@router.get("/races/{race_id}/results/search")
def results_search(
    race_id: int,
    q: str = Query(min_length=2, max_length=80),
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """Lines of the results whose name has `q`: to find one's own when it wasn't found."""
    race = _own_race(db, user, race_id)
    rows = ((race.result or {}).get("results") or {}).get("rows") or []
    words = race_results._norm(q).split()
    hits = [
        {"index": i, "name": r["name"], "category": r.get("category"), "time": format_time(r["time_s"])}
        for i, r in enumerate(rows)
        if all(w in race_results._norm(r["name"]) for w in words)
    ]
    return hits[:20]


@router.delete("/races/{race_id}/results")
def remove_results(race_id: int, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    race = _own_race(db, user, race_id)
    res = dict(race.result or {})
    res.pop("results", None)
    race.result = res
    db.commit()
    return {"ok": True}
