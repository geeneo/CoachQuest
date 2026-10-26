"""Structured training plans: dated weeks and days, and plan vs actual.

Stored on Plan.weeks as:

    [{"start": "2026-10-26", "phase": "Build", "focus": "...", "status": "draft",
      "days": [{"date": "2026-10-26", "weekday": "mon", "type": "Rest", "description": "",
                "duration_min": 0, "intensity": [], "gear": null, "route": null,
                "locked": false, "missed_reason": null}, ...]}, ...]

Whether a day was done is decided here, in code, from the logged activities.
"""

from collections import defaultdict
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from . import workouts
from .activity_types import category
from .localtime import local_date

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
GOAL_SHARE = 0.7  # logged time at least 70% of planned time counts as done


def first_week_start(start: date | None, today: date, week_start: int = 0) -> date:
    """The plan starts on the first day of `start`'s week, or of next week (today if a week starts today)."""
    if start:
        return start - timedelta(days=(start.weekday() - week_start) % 7)
    return today + timedelta(days=(week_start - today.weekday()) % 7)


def _blank_day(d: date) -> dict:
    return {
        "date": d.isoformat(),
        "weekday": WEEKDAYS[d.weekday()],
        "type": "Rest",
        "description": "",
        "duration_min": 0,
        "intensity": [],
        "gear": None,
        "route": None,
        "locked": False,
        "missed_reason": None,
        "workout": None,  # {"name", "steps"} for indoor sessions; see plan_workouts.py
    }


def _workout(raw) -> dict | None:
    """Claude's structured workout for a day, checked like any other workout; dropped if invalid."""
    if not isinstance(raw, dict) or not raw.get("steps"):
        return None
    try:
        steps = workouts.validate_steps(raw["steps"])
    except ValueError:
        return None
    return {"name": (str(raw.get("name") or "Workout").strip() or "Workout")[:120], "steps": steps}


def build_weeks(ai_weeks: list[dict], first_day: date, n_weeks: int) -> list[dict]:
    """Give Claude's weeks real dates. Missing days become Rest; duplicate weekdays keep the first."""
    weeks = []
    for i in range(n_weeks):
        src = ai_weeks[i] if i < len(ai_weeks) else {"phase": "Base", "focus": "", "days": []}
        start = first_day + timedelta(weeks=i)
        by_day = {}
        for day in src.get("days", []):
            by_day.setdefault(day.get("weekday"), day)
        days = []
        for j in range(7):
            d = _blank_day(start + timedelta(days=j))
            key = d["weekday"]
            if key in by_day:
                src_day = by_day[key]
                d.update(
                    type=src_day.get("type") or "Rest",
                    description=(src_day.get("description") or "").strip(),
                    duration_min=max(0, int(src_day.get("duration_min") or 0)),
                    intensity=[str(x) for x in src_day.get("intensity") or []][:6],
                    workout=_workout(src_day.get("workout")),
                )
            days.append(d)
        weeks.append(
            {
                "start": start.isoformat(),
                "phase": src.get("phase") or "Base",
                "focus": (src.get("focus") or "").strip(),
                "status": "draft",
                "days": days,
            }
        )
    return weeks


def _actual(acts: list) -> dict:
    return {
        "count": len(acts),
        "km": round(sum(a.distance_m for a in acts) / 1000, 1),
        "elevation_m": round(sum(a.elevation_m for a in acts)),
        "minutes": round(sum(a.duration_s for a in acts) / 60),
        "relative_effort": round(sum(a.relative_effort or 0 for a in acts)) or None,
        "avg_power": round(max((a.avg_power or 0) for a in acts)) or None,
        "avg_hr": round(max((a.avg_hr or 0) for a in acts)) or None,
        "types": sorted({category(a) for a in acts}),
        "names": [a.name for a in acts][:3],
    }


def with_actuals(weeks: list[dict], activities: list, today: date, tz: ZoneInfo | None = None) -> list[dict]:
    """Copy of the plan with each day's status and what was logged that day (in the athlete's timezone)."""
    by_date = defaultdict(list)
    for a in activities:
        day = local_date(a.start_time, tz) if tz else a.start_time.date()
        by_date[day.isoformat()].append(a)
    out = []
    for week in weeks:
        days = []
        for day in week["days"]:
            d = dict(day)
            acts = by_date.get(day["date"], [])
            day_date = date.fromisoformat(day["date"])
            d["actual"] = _actual(acts) if acts else None
            d["status"] = _status(day, acts, day_date, today)
            d["is_today"] = day_date == today
            days.append(d)
        done = [d for d in days if d["status"] in ("goal_met", "partial")]
        planned = [d for d in days if d["type"] != "Rest" and date.fromisoformat(d["date"]) <= today]
        out.append(
            {
                **week,
                "days": days,
                "is_current": date.fromisoformat(week["start"])
                <= today
                < date.fromisoformat(week["start"]) + timedelta(7),
                "summary": {
                    "planned_minutes": sum(d["duration_min"] for d in days),
                    "logged_minutes": sum(d["actual"]["minutes"] for d in days if d["actual"]),
                    "sessions_done": len(done),
                    "sessions_due": len(planned),
                },
            }
        )
    return out


def _status(day: dict, acts: list, day_date: date, today: date) -> str:
    if day["type"] == "Rest":
        return "extra" if acts else ("rest" if day_date <= today else "planned")
    if acts:
        logged = sum(a.duration_s for a in acts) / 60
        if not day["duration_min"] or logged >= GOAL_SHARE * day["duration_min"]:
            return "goal_met"
        return "partial"
    if day_date < today:
        return "missed"
    return "today" if day_date == today else "planned"


def markdown(weeks: list[dict]) -> str:
    """Plain-text version of the plan, kept in content_md for export and older views."""
    lines = []
    for i, w in enumerate(weeks, 1):
        lines.append(f"### Week {i} · {w['phase']} · {w['start']}\n\n{w['focus']}\n")
        lines.append("| Day | Type | Session | Min | Intensity |\n|---|---|---|---|---|")
        for d in w["days"]:
            desc = d["description"].replace("|", "/")
            lines.append(
                f"| {d['weekday'].title()} | {d['type']} | {desc} | {d['duration_min']} | {', '.join(d['intensity'])} |"
            )
        lines.append("")
    return "\n".join(lines)


def find_day(weeks: list[dict], day: str) -> tuple[int, int]:
    for wi, week in enumerate(weeks):
        for di, d in enumerate(week["days"]):
            if d["date"] == day:
                return wi, di
    raise KeyError(day)


NOT_PLANNED = "{type} session, not planned yet: re-plan from this week to fill it in, or edit it."


def apply_preferences(weeks: list[dict], prefs: dict[str, list[str]], today: date) -> tuple[int, int]:
    """Set future, unlocked days to the athlete's first preferred type for that weekday.

    Only the type changes, so a rest day that becomes a training day has no session yet: it says so
    (and is counted) instead of keeping "Rest.". A structured indoor workout stays only on indoor
    days. Returns (days changed, training days left to plan)."""
    changed = empty = 0
    for week in weeks:
        for d in week["days"]:
            wanted = prefs.get(d["weekday"]) or []
            if d["locked"] or date.fromisoformat(d["date"]) <= today or not wanted or d["type"] in wanted:
                continue
            was_rest = d["type"] == "Rest" or not d.get("duration_min")
            d["type"] = wanted[0]
            if wanted[0] == "Rest":
                d.update(description="Rest day.", duration_min=0, intensity=[], workout=None)
            elif was_rest:
                d.update(description=NOT_PLANNED.format(type=wanted[0]), duration_min=0, intensity=[], workout=None)
                empty += 1
            elif wanted[0] != "Zwift / indoor":
                d["workout"] = None  # an indoor workout doesn't belong on a road or run day
            changed += 1
    return changed, empty


def replan_from(weeks: list[dict], today: date) -> int:
    """Index of the first week to re-plan: the one holding today, or 0 before the plan starts.

    Returns len(weeks) when the plan is over."""
    for i, week in enumerate(weeks):
        if today < date.fromisoformat(week["start"]) + timedelta(7):
            return i
    return len(weeks)


def kept(day: dict, today: date) -> bool:
    """Re-planning leaves past days (what happened, happened) and locked days alone."""
    return day["locked"] or date.fromisoformat(day["date"]) < today


def merge_replan(old: list[dict], new: list[dict], today: date) -> int:
    """Put Claude's new weeks over the old ones from the same start, keeping kept() days.

    Changes `old` in place and returns how many days changed."""
    by_start = {w["start"]: w for w in new}
    changed = 0
    for week in old:
        fresh = by_start.get(week["start"])
        if fresh is None:
            continue
        for i, d in enumerate(week["days"]):
            if kept(d, today):
                continue
            n = fresh["days"][i]
            fields = ("type", "description", "duration_min", "intensity", "workout")
            if any(d.get(k) != n[k] for k in fields):  # older plans have no "workout"
                changed += 1
            d.update({k: n[k] for k in fields}, gear=None, route=None, missed_reason=None)
        if any(not kept(d, today) for d in week["days"]):
            week.update(phase=fresh["phase"], focus=fresh["focus"], status="draft")
    return changed
