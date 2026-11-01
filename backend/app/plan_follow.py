"""The plan follows what the athlete actually did, on past days and today.

Two cases, both written into the plan (Plan.weeks) so the plan page, the calendar and the AI coach's
re-plans all see what really happened:

- Another kind of session that day: planned Road, rode Zwift; planned Walk, ran outdoors. The session
  becomes what was done, and keeps the plan in `changed_from` ({type, description, duration_min,
  intensity}) so the day can show "planned Road · 4h 55m". If the athlete later corrects the
  activity's type so it fits the plan again, the session goes back to what was planned.
- A session done on another day of the same week: planned the long ride Saturday, rode it Sunday (a
  rest day) and nothing on Saturday. The session moves to Sunday (`moved_from`: "2026-10-24") and
  Saturday becomes a rest day marked `moved_to`, so it isn't counted as missed.

Locked days are left alone, and so are days in the future. Whether a day was done is still decided by
time (plan_tracker._status).
"""

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm.attributes import flag_modified

from . import localtime
from .activity_types import category
from .db import Plan, ScheduledWorkout, User
from .localtime import local_date
from .plan_tracker import extras, takes_route
from .plan_workouts import WORKOUT_TYPES
from .queries import activities_since

# What an activity's category (activity_types.py) is as a plan session type; categories not here
# (rowing, skiing, climbing...) don't change the plan.
SESSION_FOR = {
    "Road": "Road",
    "E-Bike": "Road",
    "Gravel": "Gravel",
    "MTB": "MTB",
    "E-MTB": "E-MTB",
    "Virtual": "Zwift / indoor",
    "Run": "Outdoor run",
    "Trail run": "Trail run",
    "Treadmill run": "Treadmill run",
    "Walk": "Walk",
    "Hike": "Hike",
    "Swim": "Swim",
    "Strength": "Strength",
    "Workout": "Strength",
    "Yoga": "Yoga / mobility",
}
OUTDOOR_RIDES = {"Road", "E-Bike", "Gravel", "MTB", "E-MTB"}
# Which categories count as doing a session type (anything else is "another kind of session").
FITS = {
    "Road": {"Road", "E-Bike"},
    "Gravel": {"Gravel", "Road"},
    "MTB": {"MTB", "E-MTB"},
    "E-MTB": {"E-MTB", "MTB"},
    "Hill repeats": OUTDOOR_RIDES,
    "Zwift / indoor": {"Virtual"},
    "Treadmill run": {"Treadmill run"},
    "Outdoor run": {"Run", "Trail run"},
    "Trail run": {"Trail run", "Run"},
    "Walk": {"Walk", "Hike"},
    "Hike": {"Hike", "Walk"},
    "Swim": {"Swim"},
    "Strength": {"Strength", "Workout"},
    "Yoga / mobility": {"Yoga"},
}
SESSION_FIELDS = ("type", "description", "duration_min", "intensity")
# A moved session takes the whole day with it.
MOVED_FIELDS = (*SESSION_FIELDS, "workout", "segment_id", "strength", "extra_sessions")


def fits(session_type: str, cat: str) -> bool:
    """Whether an activity of this category counts as doing this session ("Race" fits anything)."""
    if session_type == "Race":
        return True
    allowed = FITS.get(session_type)
    return cat in allowed if allowed is not None else SESSION_FOR.get(cat) == session_type


def _restore(session: dict) -> None:
    """Undo an earlier change, so it's worked out afresh from the activities as they are now."""
    before = session.pop("changed_from", None)
    if before:
        session.update(before)


def _follow_day(day: dict, cats: list[str]) -> None:
    """Pair the day's sessions with its activities; a session nothing fits becomes what was done."""
    sessions = [day, *extras(day)] if day["type"] != "Rest" else []
    for s in sessions:
        _restore(s)
    left = list(cats)
    unmatched = []
    for s in sessions:
        hit = next((c for c in left if fits(s["type"], c)), None)
        if hit is None:
            unmatched.append(s)
        else:
            left.remove(hit)
    for s in unmatched:
        cat = next((c for c in left if c in SESSION_FOR), None)
        if cat is None:
            continue
        left.remove(cat)
        s["changed_from"] = {k: s.get(k) for k in SESSION_FIELDS}
        s["type"] = SESSION_FOR[cat]
        if s is day and not takes_route(s["type"]):
            day["segment_id"] = None  # an indoor session rides no route


def _move(week: dict, cats_on: dict[str, list[str]], today: date) -> None:
    """A session missed on one day and done on a rest day of the same week moves to that day."""
    days = [d for d in week["days"] if date.fromisoformat(d["date"]) <= today and not d.get("locked")]
    missed = [d for d in days if d["type"] != "Rest" and not cats_on.get(d["date"]) and not d.get("moved_to")]
    for m in missed:
        target = None
        for r in sorted(days, key=lambda r: abs(date.fromisoformat(r["date"]) - date.fromisoformat(m["date"]))):
            if (
                r["type"] == "Rest"
                and not r.get("moved_to")
                and any(fits(m["type"], c) for c in cats_on.get(r["date"], []))
            ):
                target = r
                break
        if target is None:
            continue
        for k in MOVED_FIELDS:
            target[k] = m.get(k)
        target["moved_from"] = m["date"]
        m.update(
            type="Rest",
            description=f"Moved to {target['weekday'].title()} {target['date'][8:]}: done that day.",
            duration_min=0,
            intensity=[],
            workout=None,
            segment_id=None,
            strength=None,
            extra_sessions=[],
            moved_to=target["date"],
        )


def follow(weeks: list[dict], activities: list, today: date, tz=None) -> bool:
    """Change `weeks` in place to what was done; True when anything changed."""
    cats_on: dict[str, list[str]] = defaultdict(list)
    for a in activities:
        day = local_date(a.start_time, tz) if tz else a.start_time.date()
        cats_on[day.isoformat()].append(category(a))
    before = repr(weeks)
    for week in weeks:
        _move(week, cats_on, today)
        for d in week["days"]:
            if date.fromisoformat(d["date"]) <= today and not d.get("locked"):
                _follow_day(d, cats_on.get(d["date"], []))
    return repr(weeks) != before


def _start(week: dict) -> str:
    return week.get("start") or week["days"][0]["date"]


def update(db: DbSession, plan: Plan, athlete: User, today: date | None = None) -> bool:
    """Bring a saved plan in line with the athlete's activities; saves and returns True on a change."""
    if not plan.weeks or plan.start_date is None:
        return False
    today = today or localtime.today(athlete)
    first = date.fromisoformat(_start(plan.weeks[0]))
    if first > today:
        return False
    # A day early: a ride late on the first local day can be stored as the day before in UTC.
    acts = activities_since(db, athlete.id, datetime.combine(first - timedelta(days=1), datetime.min.time()))
    changed = follow(plan.weeks, acts, today, localtime.zone(athlete.timezone))
    if changed:
        flag_modified(plan, "weeks")
    _skip_replaced(db, plan, today)
    db.commit()
    return changed


def _skip_replaced(db: DbSession, plan: Plan, today: date) -> None:
    """An indoor workout whose day was done as something else (a run, an outdoor ride nothing matched to
    it) counts as skipped, not missed: the session was done, just not this way."""
    replaced = {
        date.fromisoformat(d["date"])
        for w in plan.weeks
        for d in w["days"]
        if (d.get("changed_from") or {}).get("type") in WORKOUT_TYPES
        and d["type"] not in WORKOUT_TYPES
        or (d.get("moved_to") and date.fromisoformat(d["date"]) <= today)
    }
    if not replaced:
        return
    for sw in db.scalars(
        select(ScheduledWorkout).where(
            ScheduledWorkout.plan_id == plan.id,
            ScheduledWorkout.plan_managed.is_(True),
            ScheduledWorkout.day.in_(replaced),
            ScheduledWorkout.status == "planned",
            ScheduledWorkout.activity_id.is_(None),
        )
    ):
        sw.status = "skipped"


def update_all(db: DbSession, athlete: User, start: date, end: date) -> None:
    """Every plan of the athlete with days from `start` to `end` (the calendar's range)."""
    today = localtime.today(athlete)
    if start > today:
        return
    for p in db.scalars(select(Plan).where(Plan.athlete_id == athlete.id, Plan.start_date.is_not(None))):
        weeks = p.weeks or []
        if weeks and _start(weeks[0]) <= end.isoformat() and _start(weeks[-1]) >= (start - timedelta(6)).isoformat():
            update(db, p, athlete, today)
