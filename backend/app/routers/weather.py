"""The weather page: the athlete's routes (rides grouped, and favourites) and the forecast along them."""

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from .. import geo, localtime, plan_tracker, ride_info, ride_routes, weather
from ..db import Activity, Connection, Plan, Segment, User, get_db
from ..deps import current_user, require_scope, resolve_athlete_id
from ..providers import strava

log = logging.getLogger("coachquest.weather")
router = APIRouter(prefix="/api/athletes/{athlete}/weather", tags=["weather"])
SUMMARY = (
    "key",
    "source",
    "name",
    "category",
    "distance_km",
    "elevation_m",
    "avg_minutes",
    "count",
    "this_year",
    "first",
    "last",
)
_groups: dict[tuple, list[dict]] = {}  # (athlete, rides with a line, newest id) -> routes


def _athlete(db: DbSession, user: User, athlete: str) -> User:
    athlete_id = resolve_athlete_id(athlete, user)
    require_scope(db, user, athlete_id, "activities")
    return db.get(User, athlete_id)


def _routes(db: DbSession, athlete_id: int) -> list[dict]:
    """Grouping hundreds of rides takes a moment, so it's kept until a ride with a line comes or goes."""
    marker = db.execute(
        select(func.count(Activity.id), func.max(Activity.id)).where(
            Activity.user_id == athlete_id, Activity.polyline.is_not(None)
        )
    ).one()
    key = (athlete_id, *marker)
    if key not in _groups:
        for old in [k for k in _groups if k[0] == athlete_id]:
            del _groups[old]
        _groups[key] = ride_routes.ride_groups(db, athlete_id)
    return ride_routes.favourites(db, athlete_id) + _groups[key]


@router.get("/routes")
def routes(athlete: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    a = _athlete(db, user, athlete)
    rs = _routes(db, a.id)
    with_line = [r for r in rs if r["polyline"] or r["source"] == "favourite"]
    return {
        "routes": [{k: r.get(k) for k in SUMMARY} | {"has_line": bool(r["polyline"])} for r in with_line],
        "rides_without_line": db.scalar(
            select(func.count(Activity.id)).where(
                Activity.user_id == a.id, Activity.polyline.is_(None), Activity.source == "strava"
            )
        ),
        "usual_start": ride_routes.usual_start(db, a),
        "home": _home_out(db, a),
    }


async def _line_for_favourite(db: DbSession, athlete_id: int, seg: Segment) -> str | None:
    """A favourite saved before lines were kept: fetch its line from Strava once."""
    if seg.polyline:
        return seg.polyline
    conn = db.scalar(
        select(Connection).where(
            Connection.user_id == athlete_id, Connection.provider == "strava", Connection.status == "active"
        )
    )
    if conn is None:
        return None
    fetch = strava.activity if seg.kind == "ride" else strava.route
    try:
        details = await fetch(db, conn, seg.strava_id)
    except Exception as exc:  # not found, rate limited, a token or network problem: no line this time
        log.info("No line for favourite %s from Strava: %r", seg.id, exc)
        return None
    seg.polyline = details.get("polyline")
    db.commit()
    return seg.polyline


@router.get("/routes/{key}")
async def route(
    athlete: str,
    key: str,
    start: str = Query(default="", pattern=r"^([01]\d|2[0-3]):[0-5]\d$|^$"),
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """One route: its numbers, its line, and riding it at `start` on each of the next 16 days."""
    a = _athlete(db, user, athlete)
    r = next((x for x in _routes(db, a.id) if x["key"] == key), None)
    if r is None:
        raise HTTPException(status_code=404, detail="Route not found")
    if r["source"] == "favourite" and not r["polyline"]:
        r = {**r, "polyline": await _line_for_favourite(db, a.id, db.get(Segment, r["segment_id"]))}
    if not r["polyline"]:
        raise HTTPException(status_code=409, detail="No map line for this route (connect Strava, or add it again)")
    start = start or ride_routes.usual_start(db, a)
    minutes = r.get("avg_minutes") or round(r["distance_km"] / 25 * 60)
    try:
        fc = await weather.route_forecast(r["polyline"], minutes, start, localtime.today(a))
    except weather.WeatherError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    for d in fc["days"]:
        if d["ride"]:
            d["ride"]["direction"] = weather.direction_advice(d["ride"])
    return {"route": {k: v for k, v in r.items() if k != "polyline"}, "start": start, **fc}


def _home_out(db: DbSession, a: User) -> dict:
    if a.home_lat is not None and a.home_lng is not None:
        return {"set": True, "name": a.home_name or "Home", "lat": a.home_lat, "lng": a.home_lng}
    return {
        "set": False,
        "name": "Where your latest outdoor ride started",
        "available": bool(ride_routes.latest_start(db, a.id)),
    }


class HomeIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    name: str = Field(default="", max_length=120)


@router.put("/home-location")
def set_home(
    athlete: str, body: HomeIn | None = None, user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    """Set the home location (or, with no body, go back to where the latest ride started)."""
    a = _athlete(db, user, athlete)
    if a.id != user.id:
        raise HTTPException(status_code=403, detail="Only the athlete can set their home location")
    a.home_lat, a.home_lng = (round(body.lat, 4), round(body.lng, 4)) if body else (None, None)
    a.home_name = body.name.strip() if body else ""
    db.commit()
    return _home_out(db, a)


@router.get("/places")
async def places(
    athlete: str,
    q: str = Query(min_length=2, max_length=80),
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    _athlete(db, user, athlete)
    try:
        return {"places": await weather.places(q)}
    except weather.WeatherError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/home")
async def home(athlete: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """The forecast at the athlete's home location (or their latest outdoor ride's start), day by day."""
    a = _athlete(db, user, athlete)
    point = ride_routes.home_point(db, a)
    if point is None:
        raise HTTPException(status_code=409, detail="Set your home location, or ride outdoors with Strava first")
    try:
        hourly = (await weather.forecast([point]))[0]
    except weather.WeatherError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    today = localtime.today(a)
    days = [weather._daily(hourly, today + timedelta(days=n)) for n in range(weather.DAYS)]
    return {"days": [d for d in days if d], "home": _home_out(db, a)}


async def _plan_day(db: DbSession, a: User, d: dict, start: str, today: date, home_at) -> dict | None:
    """One outdoor plan day: along its route at riding time, else the whole day where the ride starts."""
    day = date.fromisoformat(d["date"])
    seg = db.get(Segment, d["segment_id"]) if d.get("segment_id") else None
    if seg is not None and seg.athlete_id != a.id:
        seg = None
    if seg is not None and seg.kind != "segment" and await _line_for_favourite(db, a.id, seg):
        minutes = d.get("duration_min") or seg.est_minutes or round((seg.distance_m or 0) / 1000 / 25 * 60)
        fc = await weather.route_forecast(seg.polyline, minutes, start, today)
        hit = next((x for x in fc["days"] if x["date"] == d["date"]), None)
        if hit and hit["ride"]:
            return weather.plan_summary(hit["ride"], seg.name, f"fav-{seg.id}")
    points = geo.decode(seg.polyline) if seg is not None and seg.polyline else []
    point = points[0] if points else home_at
    if point is None:
        return None
    whole = weather._daily((await weather.forecast([point]))[0], day)
    return weather.plan_summary(whole, seg.name if seg else None) if whole else None


@router.get("/plan/{plan_id}")
async def plan_days(athlete: str, plan_id: int, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """The weather for each outdoor day of a plan within the forecast (16 days), by date."""
    a = _athlete(db, user, athlete)
    plan = db.get(Plan, plan_id)
    if plan is None or plan.athlete_id != a.id:
        raise HTTPException(status_code=404, detail="Plan not found")
    today = localtime.today(a)
    last = today + timedelta(days=weather.DAYS - 1)
    days = [
        d
        for week in plan.weeks or []
        for d in week["days"]
        if today.isoformat() <= d["date"] <= last.isoformat()
        and d.get("type") != "Rest"
        and plan_tracker.takes_route(d.get("type"))
    ]
    out: dict[str, dict] = {}
    if not days:
        return {"days": out, "start": None}
    start = ride_routes.usual_start(db, a)
    home_at = ride_routes.home_point(db, a)
    try:
        for d in days:
            w = await _plan_day(db, a, d, start, today, home_at)
            if w:
                out[d["date"]] = w
    except weather.WeatherError as exc:
        return {"days": out, "start": start, "error": str(exc)}
    return {"days": out, "start": start}


@router.get("/rides")
async def ride_details(
    athlete: str,
    start: date,
    end: date,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """The Calendar's planned outdoor rides from `start` to `end`: their numbers, food and drink, pacing,
    kit, and the weather on them when they're within the forecast (ride_info.py)."""
    from .workouts import _plan_days  # the Calendar's own view of the plan days

    a = _athlete(db, user, athlete)
    if end < start or (end - start).days > 45:
        raise HTTPException(status_code=422, detail="Pick a range of up to 45 days")
    today = localtime.today(a)
    ride_start = ride_routes.usual_start(db, a)
    speed = ride_info.recent_speed(db, a.id)
    home_at = ride_routes.home_point(db, a)
    groups: list = []  # the ridden routes, grouped once when a day needs them
    forecast_ok = True
    out = {}
    for day, d in sorted(_plan_days(db, a.id, start, end).items()):
        if d["type"] == "Rest" or not plan_tracker.takes_route(d["type"]):
            continue
        try:
            item, forecast_ok = await _ride_day(db, a, day, d, ride_start, speed, home_at, today, forecast_ok, groups)
        except Exception:  # one odd day mustn't hide the others
            log.exception("Ride details for athlete %s on %s failed", a.id, day)
            continue
        out[day] = item
    return {"days": out, "forecast_ok": forecast_ok}


async def _ride_day(
    db: DbSession,
    a: User,
    day: str,
    d: dict,
    ride_start: str,
    speed: float | None,
    home_at: geo.Point | None,
    today: date,
    forecast_ok: bool,
    groups: list,
) -> tuple[dict, bool]:
    """One planned outdoor ride for ride_details, and whether the forecast still answers. `groups` holds
    the ridden routes once a day needed them (grouping takes a moment)."""
    seg = db.get(Segment, d["segment"]["id"]) if d.get("segment") else None
    history = None
    if seg is not None and seg.kind != "segment" and await _line_for_favourite(db, a.id, seg):
        if not groups:
            groups.append([g for g in _routes(db, a.id) if g["source"] == "rides"])
        history = ride_info.route_history(groups[0], seg)
    nums = ride_info.numbers(d, seg, history, speed, ride_start)
    minutes = nums["ride_minutes"] or d["duration_min"] or 0
    w = None
    if forecast_ok and today <= date.fromisoformat(day) <= today + timedelta(days=weather.DAYS - 1):
        session = {"date": day, "segment_id": seg.id if seg else None, "duration_min": minutes}
        try:
            w = await _plan_day(db, a, session, ride_start, today, home_at)
        except weather.WeatherError:
            forecast_ok = False  # don't wait on it again for every day
    return {
        "numbers": nums,
        "fuel": ride_info.fuel(minutes, w.get("temp_max") if w else None) if minutes else None,
        "pacing": ride_info.pacing(d.get("intensity"), a.ftp_watts),
        "kit": ride_info.kit(w),
        "weather": w,
    }, forecast_ok
