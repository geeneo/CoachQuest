"""Planned vs actual: how scheduled workouts went, week by week.

All numbers are computed here from the workouts' planned steps and the rides
matched to them (completion.py). Nothing is estimated for a ride: a missing
power or heart rate stays missing. What a viewer sees follows their scopes:
power and TSS of rides need "activities", planned watts need "profile".

Per workout:
- completion: ridden time / planned time, capped at 100%.
- power: ride's normalised power / planned normalised power (both in watts,
  so it needs the athlete's FTP).
- flags: "short" under 70% of the planned time, "under_target" / "over_target"
  when normalised power is more than 10% below / above plan.
"""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import completion, localtime, workouts
from .db import Activity, ScheduledWorkout, User
from .fitness import week_start_of
from .plan_tracker import GOAL_SHARE

POWER_TOLERANCE = 0.10


def workout_result(sw: ScheduledWorkout, ride: Activity | None, ftp: int | None, today: date) -> dict:
    est = workouts.estimate(sw.steps, ftp)
    planned_s = est["duration_s"]
    out = {
        "id": sw.id,
        "date": sw.day.isoformat(),
        "name": sw.name,
        "planned_min": round(planned_s / 60),
        "planned_tss": est["tss"],
        "planned_if": est["intensity_factor"],
        "planned_np": est.get("np_watts"),
        "flags": [],
    }
    if sw.status in ("skipped", "cancelled"):
        return {**out, "status": sw.status}
    if ride is None:
        return {**out, "status": "missed" if sw.day < today else ("today" if sw.day == today else "planned")}
    share = ride.duration_s / planned_s if planned_s else 1
    out.update(
        status="done" if share >= GOAL_SHARE else "partial",
        actual_min=round(ride.duration_s / 60),
        completion_pct=min(100, round(100 * share)),
        actual_np=round(ride.norm_power) if ride.norm_power else None,
        actual_avg_power=round(ride.avg_power) if ride.avg_power else None,
        actual_hr=round(ride.avg_hr) if ride.avg_hr else None,
        actual_tss=round(ride.tss) if ride.tss else None,
        activity=ride.name,
    )
    if share < GOAL_SHARE:
        out["flags"].append("short")
    if out["planned_np"] and out["actual_np"]:
        ratio = out["actual_np"] / out["planned_np"]
        out["power_pct"] = round(100 * ratio)
        if ratio < 1 - POWER_TOLERANCE:
            out["flags"].append("under_target")
        elif ratio > 1 + POWER_TOLERANCE:
            out["flags"].append("over_target")
    return out


def _visible(r: dict, scopes: set[str]) -> dict:
    """Drop what the viewer may not see."""
    if "activities" not in scopes:
        for k in ("actual_np", "actual_avg_power", "actual_hr", "actual_tss", "activity", "power_pct"):
            r.pop(k, None)
        r["flags"] = [f for f in r["flags"] if f == "short"]
    if "profile" not in scopes:
        r.pop("planned_np", None)
        r.pop("power_pct", None)
    return r


def summarise(results: list[dict], today: date) -> dict:
    due = [r for r in results if r["status"] not in ("planned", "today", "cancelled") or r.get("actual_min")]
    planned_due = sum(r["planned_min"] for r in due if r["status"] != "skipped")
    done_min = sum(min(r.get("actual_min", 0), r["planned_min"]) for r in due)
    counts = {k: sum(1 for r in results if r["status"] == k) for k in ("done", "partial", "missed", "skipped")}
    return {
        "scheduled": len([r for r in results if r["status"] != "cancelled"]),
        **counts,
        "upcoming": sum(1 for r in results if r["status"] in ("planned", "today")),
        "planned_min": sum(r["planned_min"] for r in results if r["status"] != "cancelled"),
        "actual_min": sum(r.get("actual_min", 0) for r in results),
        "planned_tss": sum(r["planned_tss"] or 0 for r in results if r["status"] != "cancelled") or None,
        "actual_tss": sum(r.get("actual_tss") or 0 for r in results) or None,
        # Of the time due so far (skipped workouts don't count against it).
        "compliance_pct": round(100 * done_min / planned_due) if planned_due else None,
        "under_target": sum(1 for r in results if "under_target" in r["flags"]),
        "short": sum(1 for r in results if "short" in r["flags"]),
    }


def week(db: DbSession, athlete: User, scopes: set[str], week_start: date, today: date | None = None) -> dict:
    """One week's planned vs actual (summary plus each workout)."""
    today = today or localtime.today(athlete)
    week_end = week_start + timedelta(days=6)
    completion.refresh(db, athlete, week_start, week_end)
    rows = db.scalars(
        select(ScheduledWorkout)
        .where(
            ScheduledWorkout.athlete_id == athlete.id,
            ScheduledWorkout.day >= week_start,
            ScheduledWorkout.day <= week_end,
        )
        .order_by(ScheduledWorkout.day, ScheduledWorkout.id)
    ).all()
    ids = [r.activity_id for r in rows if r.activity_id]
    rides = {a.id: a for a in db.scalars(select(Activity).where(Activity.id.in_(ids)))} if ids else {}
    results = [workout_result(sw, rides.get(sw.activity_id), athlete.ftp_watts, today) for sw in rows]
    out = {
        "week_start": week_start.isoformat(),
        "is_current": week_start <= today <= week_end,
        **summarise(results, today),
        "workouts": [_visible(r, scopes) for r in results],
    }
    if "activities" not in scopes:
        out.pop("actual_tss", None)
        out.pop("under_target", None)
    return out


def weekly(db: DbSession, athlete: User, scopes: set[str], weeks: int = 6) -> dict:
    """The last `weeks` weeks including this one, newest first."""
    today = localtime.today(athlete)
    current = week_start_of(today, athlete.week_start or 0)
    return {
        "today": today.isoformat(),
        "weeks": [week(db, athlete, scopes, current - timedelta(weeks=i), today) for i in range(weeks)],
    }
