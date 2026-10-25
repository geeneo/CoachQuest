"""Training plans written by the AI coach, tracked day by day against what was logged."""

import copy
from datetime import date, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from .. import localtime, plan_tracker, plan_workouts, sync_engine
from ..coach import PHASES, CoachError, build_facts, generate_plan
from ..db import Grant, Plan, PlanComment, User, get_db, utcnow
from ..deps import allowed_scopes, current_user, require_scope, resolve_athlete_id
from ..notifications import notify
from ..queries import activities_since
from .preferences import SESSION_TYPES, preferences_out

router = APIRouter(prefix="/api/athletes/{athlete}/plans", tags=["plans"])


class PlanRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1, max_length=500)
    event_date: date | None = None
    start_date: date | None = None  # plan starts on the first day of this date's week; default next week
    weeks: int = Field(default=4, ge=1, le=16)
    hours_per_week: float = Field(default=8, ge=1, le=30)
    available_days: list[str] = Field(default_factory=lambda: ["Tue", "Thu", "Sat", "Sun"])
    notes: str = Field(default="", max_length=2000)
    # Indoor days become structured workouts on the calendar (and go to the athlete's platforms).
    structured_workouts: bool = True


def plan_out(p: Plan, db: DbSession, full: bool = False, today: date | None = None) -> dict:
    author = db.get(User, p.author_id) if p.author_id else None
    out = {
        "id": p.id,
        "title": p.title,
        "author": author.display_name if author else None,
        "model": p.model,
        "created_at": p.created_at,
        "request": p.request,
        "start_date": p.start_date,
        "structured": bool(p.weeks),
    }
    if full:
        athlete = db.get(User, p.athlete_id)
        today = today or localtime.today(athlete)
        out.update(content_md=p.content_md, facts=p.facts)
        if p.weeks:
            # A day early: a ride late on the first local day can be stored as the day before in UTC.
            start = datetime.combine(date.fromisoformat(p.weeks[0]["start"]), datetime.min.time()) - timedelta(1)
            acts = activities_since(db, p.athlete_id, start)
            out["weeks"] = plan_tracker.with_actuals(p.weeks, acts, today, localtime.zone(athlete.timezone))
    return out


def _plan(db: DbSession, user: User, athlete: str, plan_id: int) -> Plan:
    athlete_id = resolve_athlete_id(athlete, user)
    require_scope(db, user, athlete_id, "plans")
    p = db.get(Plan, plan_id)
    if p is None or p.athlete_id != athlete_id:
        raise HTTPException(status_code=404, detail="Plan not found")
    return p


def _editable(p: Plan) -> list[dict]:
    """A deep copy to change. Editing p.weeks in place would hide the change from SQLAlchemy."""
    return copy.deepcopy(p.weeks or [])


def _save_weeks(db: DbSession, p: Plan, weeks: list[dict], background: BackgroundTasks | None = None) -> None:
    """Store the weeks and bring the plan's calendar workouts in line (sent on in the background)."""
    p.weeks = weeks
    db.commit()
    _workouts(db, p, background)


def _workouts(db: DbSession, p: Plan, background: BackgroundTasks | None) -> None:
    if plan_workouts.reconcile(db, p, localtime.today(db.get(User, p.athlete_id))) and background:
        background.add_task(sync_engine.run_due)


@router.get("")
def list_plans(athlete: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    athlete_id = resolve_athlete_id(athlete, user)
    require_scope(db, user, athlete_id, "plans")
    rows = db.scalars(select(Plan).where(Plan.athlete_id == athlete_id).order_by(Plan.created_at.desc())).all()
    return [plan_out(p, db) for p in rows]


@router.get("/current")
def current_plan(athlete: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """The newest structured plan that covers today (or starts within a week), or null."""
    athlete_id = resolve_athlete_id(athlete, user)
    require_scope(db, user, athlete_id, "plans")
    today = localtime.today(db.get(User, athlete_id))
    rows = db.scalars(
        select(Plan).where(Plan.athlete_id == athlete_id, Plan.start_date.is_not(None)).order_by(Plan.created_at.desc())
    ).all()
    for p in rows:
        end = p.start_date + timedelta(weeks=len(p.weeks or []))
        if p.start_date - timedelta(days=7) <= today < end:
            return plan_out(p, db, full=True, today=today)
    return None


@router.get("/{plan_id}")
def get_plan(athlete: str, plan_id: int, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    return plan_out(_plan(db, user, athlete, plan_id), db, full=True)


@router.post("")
async def create_plan(
    athlete: str,
    body: PlanRequest,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    athlete_id = resolve_athlete_id(athlete, user)
    require_scope(db, user, athlete_id, "plans")
    target = db.get(User, athlete_id)
    monday = plan_tracker.first_week_start(body.start_date, localtime.today(target), target.week_start or 0)
    request = body.model_dump(mode="json", exclude={"title"})
    request["start_date"] = monday.isoformat()
    facts = build_facts(db, target, allowed_scopes(db, user, athlete_id), request)
    try:
        answer, model = await generate_plan(db, user, target, facts)
    except CoachError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    weeks = plan_tracker.build_weeks(answer.get("weeks", []), monday, body.weeks)
    plan = Plan(
        athlete_id=athlete_id,
        author_id=user.id,
        title=body.title,
        request=request,
        facts=facts,
        content_md=(answer.get("summary_md") or "").strip() + "\n\n" + plan_tracker.markdown(weeks),
        start_date=monday,
        weeks=weeks,
        model=model,
    )
    db.add(plan)
    db.commit()
    _workouts(db, plan, background)
    return plan_out(plan, db, full=True)


class DayEdit(BaseModel):
    type: str | None = None
    description: str | None = Field(default=None, max_length=1000)
    duration_min: int | None = Field(default=None, ge=0, le=1440)
    intensity: list[str] | None = Field(default=None, max_length=8)
    gear: str | None = Field(default=None, max_length=80)
    route: str | None = Field(default=None, max_length=300)
    locked: bool | None = None
    missed_reason: str | None = Field(default=None, max_length=40)


@router.patch("/{plan_id}/days/{day}")
def edit_day(
    athlete: str,
    plan_id: int,
    day: date,
    body: DayEdit,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """Edit one day. The athlete and coaches with the plans scope can edit."""
    p = _plan(db, user, athlete, plan_id)
    if not p.weeks:
        raise HTTPException(status_code=400, detail="This older plan has no day-by-day schedule")
    changes = body.model_dump(exclude_unset=True)
    if "type" in changes and changes["type"] not in SESSION_TYPES:
        raise HTTPException(status_code=422, detail=f"Type must be one of: {', '.join(SESSION_TYPES)}")
    weeks = _editable(p)
    try:
        wi, di = plan_tracker.find_day(weeks, day.isoformat())
    except KeyError:
        raise HTTPException(status_code=404, detail="That day is not in this plan") from None
    if changes.get("intensity") is not None:
        changes["intensity"] = [c.strip()[:30] for c in changes["intensity"] if c.strip()]
    weeks[wi]["days"][di].update(changes)
    _save_weeks(db, p, weeks, background)
    return plan_out(p, db, full=True)


class WeekEdit(BaseModel):
    phase: str | None = None
    focus: str | None = Field(default=None, max_length=300)
    status: str | None = Field(default=None, pattern="^(draft|confirmed)$")


@router.patch("/{plan_id}/weeks/{index}")
def edit_week(
    athlete: str,
    plan_id: int,
    index: int,
    body: WeekEdit,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    p = _plan(db, user, athlete, plan_id)
    if not p.weeks or not 0 <= index < len(p.weeks):
        raise HTTPException(status_code=404, detail="Week not found")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("phase") and changes["phase"] not in PHASES:
        raise HTTPException(status_code=422, detail="Unknown phase")
    weeks = _editable(p)
    weeks[index].update(changes)
    _save_weeks(db, p, weeks)
    return plan_out(p, db, full=True)


class Swap(BaseModel):
    a: date
    b: date


@router.post("/{plan_id}/swap")
def swap_days(
    athlete: str,
    plan_id: int,
    body: Swap,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """Swap the sessions on two days (dates stay put). Locked days can't be swapped."""
    p = _plan(db, user, athlete, plan_id)
    weeks = _editable(p)
    try:
        wa, da = plan_tracker.find_day(weeks, body.a.isoformat())
        wb, db_ = plan_tracker.find_day(weeks, body.b.isoformat())
    except KeyError:
        raise HTTPException(status_code=404, detail="Both days must be in this plan") from None
    day_a, day_b = weeks[wa]["days"][da], weeks[wb]["days"][db_]
    if day_a["locked"] or day_b["locked"]:
        raise HTTPException(status_code=409, detail="Unlock both days first")
    fields = ("type", "description", "duration_min", "intensity", "gear", "route", "workout")
    moved_a, moved_b = {k: day_a.get(k) for k in fields}, {k: day_b.get(k) for k in fields}
    day_a.update(moved_b)
    day_b.update(moved_a)
    _save_weeks(db, p, weeks, background)
    return plan_out(p, db, full=True)


@router.post("/{plan_id}/apply-preferences")
def apply_preferences(
    athlete: str,
    plan_id: int,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """Set future, unlocked days to the athlete's preferred type for that weekday."""
    p = _plan(db, user, athlete, plan_id)
    weeks = _editable(p)
    athlete_user = db.get(User, p.athlete_id)
    prefs = preferences_out(athlete_user)["weekday_prefs"]
    changed = plan_tracker.apply_preferences(weeks, prefs, localtime.today(athlete_user))
    _save_weeks(db, p, weeks, background)
    return {**plan_out(p, db, full=True), "changed": changed}


class Replan(BaseModel):
    reason: str = Field(default="", max_length=1000)


@router.post("/{plan_id}/replan")
async def replan(
    athlete: str,
    plan_id: int,
    body: Replan,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """Claude rewrites the plan from this week on. Past and locked days stay as they are."""
    p = _plan(db, user, athlete, plan_id)
    if not p.weeks:
        raise HTTPException(status_code=400, detail="This older plan has no day-by-day schedule")
    target = db.get(User, p.athlete_id)
    today = localtime.today(target)
    weeks = _editable(p)
    first = plan_tracker.replan_from(weeks, today)
    if first == len(weeks):
        raise HTTPException(status_code=409, detail="This plan is over. Create a new plan instead.")
    tracked = plan_out(p, db, full=True, today=today)["weeks"]
    keep = [
        {k: d[k] for k in ("date", "weekday", "type", "description", "duration_min", "status")}
        for w in tracked[first:]
        for d in w["days"]
        if plan_tracker.kept(d, today)
    ]
    request = {
        **(p.request or {}),
        "start_date": weeks[first]["start"],
        "weeks": len(weeks) - first,
        "replan": {
            "reason": body.reason,
            "keep": keep,
            "so_far": [{"start": w["start"], "phase": w["phase"], **w["summary"]} for w in tracked[:first]],
            # What the athlete and their coach said about the plan (newest 30).
            "comments": [
                {"by": c["role"], "day": c["day"], "text": c["text"]}
                for c in [{"role": x["role"], "day": x["day"], "text": x["body"]} for x in _comments(db, p, user)][-30:]
            ],
        },
    }
    facts = build_facts(db, target, allowed_scopes(db, user, p.athlete_id), request, today)
    try:
        answer, model = await generate_plan(db, user, target, facts)
    except CoachError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    start = date.fromisoformat(weeks[first]["start"])
    fresh = plan_tracker.build_weeks(answer.get("weeks", []), start, len(weeks) - first)
    changed = plan_tracker.merge_replan(weeks, fresh, today)
    summary = (answer.get("summary_md") or "").strip()
    p.content_md = f"**Re-planned {today.isoformat()}.** {summary}\n\n" + plan_tracker.markdown(weeks)
    p.model = model
    _save_weeks(db, p, weeks, background)
    return {**plan_out(p, db, full=True), "changed": changed}


# ---- Comments ----


def _role(p: Plan, user_id: int | None) -> str:
    return "athlete" if user_id == p.athlete_id else "coach"


def comment_out(c: PlanComment, p: Plan, viewer: User, names: dict[int, str]) -> dict:
    return {
        "id": c.id,
        "author": names.get(c.author_id, "Former user"),
        "role": _role(p, c.author_id),
        "day": c.day.isoformat() if c.day else None,
        "body": c.body,
        "created_at": c.created_at,
        "edited_at": c.edited_at,
        "edited_by": names.get(c.edited_by) if c.edited_by else None,
        # Everyone who can see the plan (the athlete and coaches with the plans scope) can edit and delete.
        "can_edit": True,
        "can_delete": True,
    }


def _comments(db: DbSession, p: Plan, viewer: User) -> list[dict]:
    rows = db.scalars(
        select(PlanComment).where(PlanComment.plan_id == p.id).order_by(PlanComment.created_at, PlanComment.id)
    ).all()
    ids = {c.author_id for c in rows if c.author_id} | {c.edited_by for c in rows if c.edited_by}
    names = {u.id: u.display_name for u in db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}
    return [comment_out(c, p, viewer, names) for c in rows]


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    day: date | None = None


@router.get("/{plan_id}/comments")
def list_comments(athlete: str, plan_id: int, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    return _comments(db, _plan(db, user, athlete, plan_id), user)


def _others(db: DbSession, p: Plan, author: User) -> list[User]:
    """Who hears about a comment: the athlete, and coaches who can see the plan, except the author."""
    ids = {p.athlete_id} | {
        g.coach_id
        for g in db.scalars(select(Grant).where(Grant.athlete_id == p.athlete_id, Grant.status == "active"))
        if "plans" in (g.scopes or [])
    }
    ids.discard(author.id)
    return list(db.scalars(select(User).where(User.id.in_(ids)))) if ids else []


@router.post("/{plan_id}/comments")
def add_comment(
    athlete: str,
    plan_id: int,
    body: CommentIn,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """The athlete and coaches with the plans scope can comment on the plan or on one of its days."""
    p = _plan(db, user, athlete, plan_id)
    if body.day is not None:
        try:
            plan_tracker.find_day(p.weeks or [], body.day.isoformat())
        except KeyError:
            raise HTTPException(status_code=404, detail="That day is not in this plan") from None
    c = PlanComment(plan_id=p.id, author_id=user.id, day=body.day, body=body.body.strip())
    db.add(c)
    db.commit()
    where = f" on {body.day.strftime('%a %d %b')}" if body.day else ""
    path = f"/athletes/{p.athlete_id}/plans/{p.id}"
    for other in _others(db, p, user):
        notify(
            background,
            other,
            f"{user.display_name} commented on {p.title}",
            f'{user.display_name} commented{where} on the training plan "{p.title}":\n\n{c.body}',
            ("the plan", path),
            setting="notify_comments",
        )
    return _comments(db, p, user)


@router.patch("/{plan_id}/comments/{comment_id}")
def edit_comment(
    athlete: str,
    plan_id: int,
    comment_id: int,
    body: CommentIn,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    p = _plan(db, user, athlete, plan_id)
    c = db.get(PlanComment, comment_id)
    if c is None or c.plan_id != p.id:
        raise HTTPException(status_code=404, detail="Comment not found")
    c.body, c.edited_at, c.edited_by = body.body.strip(), utcnow(), user.id
    db.commit()
    return _comments(db, p, user)


@router.delete("/{plan_id}/comments/{comment_id}")
def delete_comment(
    athlete: str, plan_id: int, comment_id: int, user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    p = _plan(db, user, athlete, plan_id)
    c = db.get(PlanComment, comment_id)
    if c is None or c.plan_id != p.id:
        raise HTTPException(status_code=404, detail="Comment not found")
    db.delete(c)
    db.commit()
    return _comments(db, p, user)


@router.delete("/{plan_id}")
def delete_plan(
    athlete: str,
    plan_id: int,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    p = _plan(db, user, athlete, plan_id)
    if user.id not in (p.athlete_id, p.author_id):
        raise HTTPException(status_code=403, detail="Only the athlete or the author can delete a plan")
    plan_workouts.plan_deleted(db, p, localtime.today(db.get(User, p.athlete_id)))
    background.add_task(sync_engine.run_due)
    db.execute(delete(PlanComment).where(PlanComment.plan_id == p.id))
    db.delete(p)
    db.commit()
    return {"ok": True}
