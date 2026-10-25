"""Training plans put their indoor sessions on the calendar as structured workouts.

When the AI coach writes or re-plans a plan, each "Zwift / indoor" day carries a
workout (steps). `reconcile` keeps the calendar in step with the plan from today
on: it creates, updates or removes the workouts the plan manages, and queues
them for delivery like any other change. Past days are never touched.

A plan workout that someone edits or moves on the calendar stops being managed:
the plan leaves it alone and won't make a second one for that plan day.
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import sync_engine
from .db import Plan, ScheduledWorkout

WORKOUT_TYPES = {"Zwift / indoor"}


def wanted(plan: Plan, today: date) -> dict[date, dict]:
    """Plan days from today on that should have a workout: {day: {name, description, steps}}."""
    if not plan.weeks or not (plan.request or {}).get("structured_workouts", True):
        return {}
    out = {}
    for week in plan.weeks:
        for d in week["days"]:
            day = date.fromisoformat(d["date"])
            w = d.get("workout")
            if day >= today and w and d["type"] in WORKOUT_TYPES:
                out[day] = {"name": w["name"], "description": d.get("description") or "", "steps": w["steps"]}
    return out


def reconcile(db: DbSession, plan: Plan, today: date) -> int:
    """Bring the plan's calendar workouts in line with the plan. Returns how many changed."""
    rows = db.scalars(
        select(ScheduledWorkout).where(ScheduledWorkout.plan_id == plan.id, ScheduledWorkout.day >= today)
    ).all()
    managed = {sw.plan_day: sw for sw in rows if sw.plan_managed}
    handled = {sw.plan_day for sw in rows if not sw.plan_managed}  # edited by hand; the plan stays out
    changed: list[ScheduledWorkout] = []
    for day, w in wanted(plan, today).items():
        if day in handled:
            continue
        sw = managed.pop(day, None)
        if sw is None:
            sw = ScheduledWorkout(
                athlete_id=plan.athlete_id,
                assigned_by=plan.author_id,
                day=day,
                plan_id=plan.id,
                plan_managed=True,
                plan_day=day,
                instructions="",
                **w,
            )
            db.add(sw)
            changed.append(sw)
        elif (sw.name, sw.description, sw.steps) != (w["name"], w["description"], w["steps"]):
            sw.name, sw.description, sw.steps = w["name"], w["description"], w["steps"]
            changed.append(sw)
    removed = [(sw.id, sw.name) for sw in managed.values()]
    for sw in managed.values():
        db.delete(sw)
    db.commit()
    for sw in changed:
        sync_engine.workout_changed(db, sw, "plan")
    for sw_id, name in removed:
        sync_engine.workout_removed(db, plan.athlete_id, sw_id, name)
    return len(changed) + len(removed)


def plan_deleted(db: DbSession, plan: Plan, today: date) -> None:
    """Remove the plan's upcoming managed workouts; anything else keeps its place on the calendar."""
    for sw in db.scalars(select(ScheduledWorkout).where(ScheduledWorkout.plan_id == plan.id)).all():
        if sw.plan_managed and sw.day >= today and sw.status == "planned":
            sw_id, name = sw.id, sw.name
            db.delete(sw)
            db.commit()
            sync_engine.workout_removed(db, plan.athlete_id, sw_id, name)
        else:
            sw.plan_id = None
    db.commit()
