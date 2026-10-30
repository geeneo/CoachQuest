"""The routes an athlete rides: their outdoor Strava rides grouped by the line they followed, plus their
favourite routes (Routes page), for the weather page (weather.py).

Two rides are the same route when they start near each other, are about as long, and follow the same
line (either way round). Each route gets its numbers from all its rides: how often and when it was
ridden, average and fastest time, speed, heart rate and power.
"""

from datetime import date
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import geo, segments
from .activity_types import category, is_outdoor, is_ride
from .db import Activity, Segment

SHAPE_POINTS = 40  # each ride compared by 40 evenly spaced points
START_M = 1500  # starts within 1.5 km
LENGTH_SHARE = 0.08  # lengths within 8%
GAP_M = 450  # lines on average within 450 m of each other
MIN_KM = 3


@lru_cache(maxsize=4096)
def _shape(encoded: str) -> tuple:
    return tuple(geo.resample(geo.decode(encoded), SHAPE_POINTS))


def _rides(db: DbSession, athlete_id: int) -> list[Activity]:
    rows = db.scalars(
        select(Activity)
        .where(Activity.user_id == athlete_id, Activity.polyline.is_not(None), Activity.distance_m >= MIN_KM * 1000)
        .order_by(Activity.start_time.desc())
    ).all()
    return [a for a in rows if is_ride(a) and is_outdoor(a)]


def _same(a: dict, b: dict) -> bool:
    if abs(a["km"] - b["km"]) > LENGTH_SHARE * max(a["km"], b["km"]):
        return False
    if geo.distance_m(a["shape"][0], b["shape"][0]) > START_M:
        return False
    return geo.mean_gap_m(a["shape"], b["shape"]) <= GAP_M and geo.mean_gap_m(b["shape"], a["shape"]) <= GAP_M


def _strava_url(a: Activity) -> str | None:
    return f"https://www.strava.com/activities/{a.external_id}" if a.source == "strava" else None


def _avg(values: list) -> float | None:
    vals = [v for v in values if v]
    return sum(vals) / len(vals) if vals else None


def ride_groups(db: DbSession, athlete_id: int, today: date | None = None) -> list[dict]:
    """The athlete's ridden routes, newest ride first in each, with the numbers for each route."""
    today = today or date.today()
    groups: list[dict] = []
    for a in _rides(db, athlete_id):
        shape = _shape(a.polyline)
        if len(shape) < 2:
            continue
        me = {"km": a.distance_m / 1000, "shape": shape}
        for g in groups:
            if _same(g["key_ride"], me):
                g["rides"].append(a)
                break
        else:
            groups.append({"key_ride": me, "rides": [a]})
    out = []
    for g in groups:
        rides = g["rides"]
        latest = rides[0]
        times = [r.duration_s for r in rides if r.duration_s]
        out.append(
            {
                "key": f"ride-{latest.id}",
                "source": "rides",
                "name": latest.name or "Ride",
                "category": category(latest),
                "polyline": latest.polyline,
                "strava_url": _strava_url(latest),
                "distance_km": round(_avg([r.distance_m for r in rides]) / 1000, 1),
                "elevation_m": round(_avg([r.elevation_m for r in rides]) or 0),
                "avg_minutes": round(_avg(times) / 60) if times else None,
                "fastest_minutes": round(min(times) / 60) if times else None,
                "avg_speed_kmh": round(sum(r.distance_m for r in rides) / sum(times) * 3.6, 1) if times else None,
                "avg_hr": round(_avg([r.avg_hr for r in rides])) if _avg([r.avg_hr for r in rides]) else None,
                "avg_power": round(_avg([r.avg_power for r in rides])) if _avg([r.avg_power for r in rides]) else None,
                "count": len(rides),
                "this_year": sum(1 for r in rides if r.start_time.year == today.year),
                "first": rides[-1].start_time.date(),
                "last": latest.start_time.date(),
                "rides": [
                    {
                        "id": r.id,
                        "date": r.start_time.date(),
                        "name": r.name,
                        "minutes": round(r.duration_s / 60),
                        "avg_power": r.avg_power,
                        "avg_hr": r.avg_hr,
                        "strava_url": _strava_url(r),
                    }
                    for r in rides[:10]
                ],
            }
        )
    return out


def favourites(db: DbSession, athlete_id: int) -> list[dict]:
    """Favourite routes (and rides saved as routes) from the Routes page; segments are too short."""
    rows = db.scalars(select(Segment).where(Segment.athlete_id == athlete_id, Segment.kind != "segment")).all()
    return [
        {
            "key": f"fav-{s.id}",
            "source": "favourite",
            "segment_id": s.id,
            "name": s.name,
            "category": "Road" if s.sport != "run" else "Run",
            "polyline": s.polyline,
            "strava_url": segments.url(s),
            "distance_km": round((s.distance_m or 0) / 1000, 1),
            "elevation_m": s.elevation_m or 0,
            "avg_minutes": s.est_minutes,
            "count": 0,
        }
        for s in rows
    ]


def all_routes(db: DbSession, athlete_id: int) -> list[dict]:
    return favourites(db, athlete_id) + ride_groups(db, athlete_id)
