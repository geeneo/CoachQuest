"""Comments by the athlete and their coaches on plans, AI coach notes and calendar workouts.

One set of rules for every target:
- Who: the athlete, and coaches holding the plans scope (the same people who
  can see plans, the AI coach and the calendar). They can all add, edit and
  delete any comment there; edits record who made them.
- New comments are emailed to the others, if their Profile allows it
  (notify_comments).
- The AI coach reads them: re-plans get the plan's comments, readiness notes
  and weekly reviews get recent comments on notes and workouts. A coach's
  comment carries the most weight (see the prompts).
"""

from datetime import date, timedelta

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from . import datefmt, plan_tracker
from .db import Assessment, Comment, Grant, Plan, ScheduledWorkout, User, utcnow
from .notifications import notify

TARGETS = ("plan", "assessment", "workout")


def resolve(db: DbSession, target: str, target_id: int, athlete_id: int):
    """The plan, note or workout, if it belongs to this athlete; else 404."""
    model = {"plan": Plan, "assessment": Assessment, "workout": ScheduledWorkout}.get(target)
    obj = db.get(model, target_id) if model else None
    if obj is None or obj.athlete_id != athlete_id:
        raise HTTPException(status_code=404, detail="Not found")
    return obj


def describe(target: str, obj, reader: User) -> str:
    """What a comment is about, with dates in the reader's format."""
    if target == "plan":
        return f'the training plan "{obj.title}"'
    if target == "workout":
        return f'the workout "{obj.name}" on {datefmt.day(obj.day, reader, weekday=True)}'
    if obj.kind == "weekly":
        return f"the weekly review for the week of {datefmt.day(obj.period_start, reader)}"
    return f"the readiness note for {datefmt.day(obj.period_start, reader, weekday=True)}"


def page(target: str, obj, athlete_id: int, for_athlete: bool) -> str:
    if target == "plan":
        return f"/athletes/{athlete_id}/plans/{obj.id}"
    return "/" if for_athlete else f"/athletes/{athlete_id}"


def role(c: Comment) -> str:
    return "athlete" if c.author_id == c.athlete_id else "coach"


def out(c: Comment, names: dict[int, str]) -> dict:
    return {
        "id": c.id,
        "target": c.target,
        "target_id": c.target_id,
        "author": names.get(c.author_id, "Former user"),
        "role": role(c),
        "day": c.day.isoformat() if c.day else None,
        "body": c.body,
        "created_at": c.created_at,
        "edited_at": c.edited_at,
        "edited_by": names.get(c.edited_by) if c.edited_by else None,
        "can_edit": True,
        "can_delete": True,
    }


def listing(db: DbSession, rows: list[Comment]) -> list[dict]:
    ids = {c.author_id for c in rows if c.author_id} | {c.edited_by for c in rows if c.edited_by}
    names = {u.id: u.display_name for u in db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}
    return [out(c, names) for c in rows]


def for_target(db: DbSession, target: str, target_id: int) -> list[dict]:
    rows = db.scalars(
        select(Comment)
        .where(Comment.target == target, Comment.target_id == target_id)
        .order_by(Comment.created_at, Comment.id)
    ).all()
    return listing(db, rows)


def counts(db: DbSession, target: str, ids: list[int]) -> dict[int, int]:
    if not ids:
        return {}
    rows = db.execute(
        select(Comment.target_id, func.count())
        .where(Comment.target == target, Comment.target_id.in_(ids))
        .group_by(Comment.target_id)
    ).all()
    return dict(rows)


def _recipients(db: DbSession, athlete_id: int, author: User) -> list[User]:
    ids = {athlete_id} | {
        g.coach_id
        for g in db.scalars(
            select(Grant).where(Grant.athlete_id == athlete_id, Grant.status == "active", Grant.role == "coach")
        )
        if "plans" in (g.scopes or [])
    }
    ids.discard(author.id)
    return list(db.scalars(select(User).where(User.id.in_(ids)))) if ids else []


def add(
    db: DbSession,
    background: BackgroundTasks,
    author: User,
    athlete_id: int,
    target: str,
    target_id: int,
    body: str,
    day: date | None = None,
) -> Comment:
    obj = resolve(db, target, target_id, athlete_id)
    if day is not None:
        if target != "plan":
            raise HTTPException(status_code=422, detail="Only plan comments can be about a single day")
        try:
            plan_tracker.find_day(obj.weeks or [], day.isoformat())
        except KeyError:
            raise HTTPException(status_code=404, detail="That day is not in this plan") from None
    c = Comment(
        athlete_id=athlete_id, target=target, target_id=target_id, author_id=author.id, day=day, body=body.strip()
    )
    db.add(c)
    db.commit()
    for other in _recipients(db, athlete_id, author):
        where = f" (about {datefmt.day(day, other, weekday=True)})" if day else ""
        what = describe(target, obj, other)
        notify(
            background,
            other,
            f"{author.display_name} commented on {what}",
            f"{author.display_name} commented on {what}{where}:\n\n{c.body}",
            ("CoachQuest", page(target, obj, athlete_id, other.id == athlete_id)),
            setting="notify_comments",
        )
    return c


def get(db: DbSession, athlete_id: int, comment_id: int) -> Comment:
    c = db.get(Comment, comment_id)
    if c is None or c.athlete_id != athlete_id:
        raise HTTPException(status_code=404, detail="Comment not found")
    return c


def edit(db: DbSession, editor: User, c: Comment, body: str) -> None:
    c.body, c.edited_at, c.edited_by = body.strip(), utcnow(), editor.id
    db.commit()


# ---- For the AI coach ----


def _brief(db: DbSession, rows: list[Comment], label) -> list[dict]:
    return [{"by": r["role"], "about": label(r), "day": r["day"], "text": r["body"]} for r in listing(db, rows)]


def for_plan(db: DbSession, plan: Plan, limit: int = 30) -> list[dict]:
    """Comments on the plan and on the workouts it put on the calendar, oldest first."""
    workout_ids = list(db.scalars(select(ScheduledWorkout.id).where(ScheduledWorkout.plan_id == plan.id)))
    names = {
        w.id: f"workout {w.name} on {w.day.isoformat()}"
        for w in db.scalars(select(ScheduledWorkout).where(ScheduledWorkout.id.in_(workout_ids)))
    }
    rows = db.scalars(
        select(Comment)
        .where(
            ((Comment.target == "plan") & (Comment.target_id == plan.id))
            | ((Comment.target == "workout") & Comment.target_id.in_(workout_ids))
        )
        .order_by(Comment.created_at)
    ).all()[-limit:]
    return _brief(db, rows, lambda r: "plan" if r["target"] == "plan" else names.get(r["target_id"], "workout"))


def recent(db: DbSession, athlete_id: int, start: date, end: date, limit: int = 20) -> list[dict]:
    """Comments on AI coach notes and calendar workouts from `start` to `end` (for readiness and reviews)."""
    notes = {
        a.id: f"{a.kind} note {a.period_start.isoformat()}"
        for a in db.scalars(
            select(Assessment).where(
                Assessment.athlete_id == athlete_id,
                Assessment.period_start >= start - timedelta(days=7),
                Assessment.period_start <= end,
            )
        )
    }
    workouts = {
        w.id: f"workout {w.name} on {w.day.isoformat()}"
        for w in db.scalars(
            select(ScheduledWorkout).where(
                ScheduledWorkout.athlete_id == athlete_id, ScheduledWorkout.day >= start, ScheduledWorkout.day <= end
            )
        )
    }
    rows = db.scalars(
        select(Comment)
        .where(
            Comment.athlete_id == athlete_id,
            ((Comment.target == "assessment") & Comment.target_id.in_(list(notes)))
            | ((Comment.target == "workout") & Comment.target_id.in_(list(workouts))),
        )
        .order_by(Comment.created_at)
    ).all()[-limit:]
    return _brief(
        db, rows, lambda r: (notes if r["target"] == "assessment" else workouts).get(r["target_id"], r["target"])
    )
