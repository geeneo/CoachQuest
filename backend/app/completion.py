"""Which ride completed which scheduled workout.

Rides arrive through Strava or Garmin (Zwift and MyWhoosh upload there), so
completion comes from those activities. The match is stored on the workout
(activity_id, match) instead of being guessed again on every view:

- auto: chosen here. A bike ride on the workout's local day; when there are
  several, the one named like the workout (Zwift calls a ride "Zwift - <workout
  name>"), indoor, and closest in length wins. One ride completes at most one
  workout. Re-checked whenever the days are looked at, so late uploads count.
- manual: the athlete picked the ride. Never changed here.
- none: the athlete said it wasn't done. Never changed here.

Strava/Garmin duplicates of one ride are already merged by activities_since.
"""

import re
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import localtime, workouts
from .activity_types import category
from .db import Activity, ScheduledWorkout, User
from .queries import activities_since

BIKE = {"Road", "Virtual", "MTB", "E-MTB", "E-Bike", "Gravel"}


def is_ride(a: Activity) -> bool:
    return category(a) in BIKE


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 3}


def score(sw: ScheduledWorkout, a: Activity) -> float:
    """Higher is a better match."""
    s = 0.0
    if sw.name.lower() in (a.name or "").lower():
        s += 3
    elif _words(sw.name) & _words(a.name or ""):
        s += 1.5
    if a.indoor or category(a) == "Virtual":
        s += 1
    planned = workouts.duration(sw.steps) or 1
    s -= min(2.0, abs(1 - a.duration_s / planned))
    return s


def rides_by_day(db: DbSession, athlete: User, start: date, end: date) -> dict[date, list[Activity]]:
    tz = localtime.zone(athlete.timezone)
    out: dict[date, list[Activity]] = {}
    for a in activities_since(db, athlete.id, datetime.combine(start - timedelta(days=1), datetime.min.time())):
        d = localtime.local_date(a.start_time, tz)
        if start <= d <= end and is_ride(a):
            out.setdefault(d, []).append(a)
    return out


def refresh(db: DbSession, athlete: User, start: date, end: date) -> int:
    """Update the automatic matches for workouts from `start` to `end` (up to today). Returns changes."""
    end = min(end, localtime.today(athlete))
    if end < start:
        return 0
    rows = db.scalars(
        select(ScheduledWorkout).where(
            ScheduledWorkout.athlete_id == athlete.id,
            ScheduledWorkout.day >= start,
            ScheduledWorkout.day <= end,
        )
    ).all()
    if not rows:
        return 0
    rides = rides_by_day(db, athlete, start, end)
    # Rides picked by hand are taken, whichever day their workout is on (it may be outside this range).
    taken = set(
        db.scalars(
            select(ScheduledWorkout.activity_id).where(
                ScheduledWorkout.athlete_id == athlete.id,
                ScheduledWorkout.match == "manual",
                ScheduledWorkout.activity_id.is_not(None),
            )
        )
    )
    changes = 0
    by_day: dict[date, list[ScheduledWorkout]] = {}
    for sw in rows:
        if sw.match == "auto":
            by_day.setdefault(sw.day, []).append(sw)
    for day, day_rows in by_day.items():
        live = [sw for sw in day_rows if sw.status == "planned"]
        free = [a for a in rides.get(day, []) if a.id not in taken]
        pairs = sorted(((score(sw, a), sw.id, a.id) for sw in live for a in free), reverse=True)
        chosen: dict[int, int] = {}
        used: set[int] = set()
        for _, sw_id, a_id in pairs:
            if sw_id not in chosen and a_id not in used:
                chosen[sw_id] = a_id
                used.add(a_id)
        for sw in day_rows:
            new = chosen.get(sw.id)
            if sw.activity_id != new:
                sw.activity_id = new
                changes += 1
    if changes:
        db.commit()
    return changes


def candidates(db: DbSession, athlete: User, sw: ScheduledWorkout) -> list[Activity]:
    """Rides the athlete could pick for this workout: the day before, the day, the day after."""
    rides = rides_by_day(db, athlete, sw.day - timedelta(days=1), sw.day + timedelta(days=1))
    return sorted((a for day in rides.values() for a in day), key=lambda a: a.start_time)
