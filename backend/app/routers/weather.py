"""The weather page: the athlete's routes (rides grouped, and favourites) and the forecast along them."""

from datetime import UTC, date, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from .. import geo, localtime, plan_tracker, ride_routes, weather
from ..db import Activity, Connection, Plan, Segment, User, get_db
from ..deps import current_user, require_scope, resolve_athlete_id
from ..providers import strava

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


def _usual_start(db: DbSession, athlete: User) -> str:
    """When the athlete usually starts riding (their last 20 outdoor rides), rounded to the half hour."""
    tz = localtime.zone(athlete.timezone)
    rides = db.scalars(
        select(Activity.start_time)
        .where(Activity.user_id == athlete.id, Activity.polyline.is_not(None))
        .order_by(Activity.start_time.desc())
        .limit(20)
    ).all()
    if not rides:
        return "07:00"
    minutes = sorted((t.replace(tzinfo=UTC).astimezone(tz).hour * 60 + t.minute) for t in rides)[len(rides) // 2]
    minutes = round(minutes / 30) * 30
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


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
        "usual_start": _usual_start(db, a),
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
    except (LookupError, httpx.HTTPError, KeyError, TypeError, ValueError):
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
    start = start or _usual_start(db, a)
    minutes = r.get("avg_minutes") or round(r["distance_km"] / 25 * 60)
    try:
        fc = await weather.route_forecast(r["polyline"], minutes, start, localtime.today(a))
    except weather.WeatherError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    for d in fc["days"]:
        if d["ride"]:
            d["ride"]["direction"] = weather.direction_advice(d["ride"])
    return {"route": {k: v for k, v in r.items() if k != "polyline"}, "start": start, **fc}


def _home_point(db: DbSession, athlete_id: int) -> geo.Point | None:
    """Where the athlete usually starts: their latest outdoor ride's start."""
    latest = db.scalar(
        select(Activity.polyline)
        .where(Activity.user_id == athlete_id, Activity.polyline.is_not(None))
        .order_by(Activity.start_time.desc())
        .limit(1)
    )
    points = geo.decode(latest) if latest else []
    return points[0] if points else None


@router.get("/home")
async def home(athlete: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """The forecast where the athlete usually starts (their latest outdoor ride's start), day by day."""
    a = _athlete(db, user, athlete)
    point = _home_point(db, a.id)
    if point is None:
        raise HTTPException(status_code=409, detail="No outdoor ride with a map line yet")
    try:
        hourly = (await weather.forecast([point]))[0]
    except weather.WeatherError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    today = localtime.today(a)
    days = [weather._daily(hourly, today + timedelta(days=n)) for n in range(weather.DAYS)]
    return {"days": [d for d in days if d]}


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
    start = _usual_start(db, a)
    home_at = _home_point(db, a.id)
    try:
        for d in days:
            w = await _plan_day(db, a, d, start, today, home_at)
            if w:
                out[d["date"]] = w
    except weather.WeatherError as exc:
        return {"days": out, "start": start, "error": str(exc)}
    return {"days": out, "start": start}
