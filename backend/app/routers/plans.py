"""Training plans written by the AI coach, tracked day by day against what was logged."""

import copy
import re
from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from .. import (
    comments,
    health,
    library,
    localtime,
    plan_approval,
    plan_tracker,
    plan_workouts,
    platform_catalog,
    runtime,
    segments,
    strength,
    sync_engine,
    zwo,
)
from ..coach import PHASES, CoachError, build_facts, generate_day, generate_plan, has_data
from ..db import Comment, Plan, PlatformWorkout, User, get_db
from ..deps import active_grant, allowed_scopes, current_user, is_friend, require_scope, resolve_athlete_id
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
    # True after the person saw the "no data yet" warning and wants a plan from the goal and hours alone.
    without_data: bool = False
    # From the athlete's human coach: the AI must follow them (only a coach can send these).
    coach_notes: str = Field(default="", max_length=2000)
    # Indoor days become structured workouts on the calendar (and go to the athlete's platforms).
    structured_workouts: bool = True
    # "event": building to the goal or event date; "maintain": keep fitness, in 4-week blocks that renew.
    kind: Literal["event", "maintain"] = "event"


MAINTAIN_WEEKS = 4


def plan_out(p: Plan, db: DbSession, full: bool = False, today: date | None = None, viewer: User | None = None) -> dict:
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
        "approval": p.approval or plan_approval.APPROVED,
        "has_pending": bool(p.pending),
    }
    if (p.request or {}).get("kind") == "maintain" and p.start_date:
        # Maintain plans renew in 4-week blocks: when the next one starts, and whether it's planned.
        planned = db.scalar(select(Plan.id).where(Plan.athlete_id == p.athlete_id, Plan.start_date >= _block_end(p)))
        out["next_block"] = {"start": _next_block_start(db, p), "ends": _block_end(p), "planned": planned is not None}
    if full:
        athlete = db.get(User, p.athlete_id)
        today = today or localtime.today(athlete)
        facts = p.facts
        if facts and "health" in facts and not (viewer and health.can_see(db, viewer, p.athlete_id)):
            facts = {k: v for k, v in facts.items() if k != "health"}  # health data: athlete and coaches only
        out.update(content_md=p.content_md, facts=facts, history=p.history or [])
        if p.pending:
            out["pending"] = {k: v for k, v in p.pending.items() if k != "fresh"}
        if viewer is not None:
            friend = is_friend(db, viewer, p.athlete_id)
            out["viewer_role"] = "friend" if friend else plan_approval.role(viewer, p.athlete_id)
            # Friends, and admins looking without a share, only look: the page hides its editing controls.
            out["read_only"] = friend or (
                viewer.id != p.athlete_id and viewer.is_admin and active_grant(db, p.athlete_id, viewer.id) is None
            )
            waiting = p.approval != plan_approval.APPROVED or bool(p.pending)
            out["can_approve"] = waiting and plan_approval.can_approve(db, viewer, p.athlete_id, p)
            if waiting and viewer.id == p.athlete_id and plan_approval.required(db, viewer):
                at = plan_approval.athlete_may_decide_at(p, viewer)
                out["athlete_decides_at"] = at.isoformat() if at else None
        if p.weeks:
            # A day early: a ride late on the first local day can be stored as the day before in UTC.
            start = datetime.combine(date.fromisoformat(p.weeks[0]["start"]), datetime.min.time()) - timedelta(1)
            acts = activities_since(db, p.athlete_id, start)
            out["weeks"] = plan_tracker.with_actuals(p.weeks, acts, today, localtime.zone(athlete.timezone))
            out["platform_matching"] = _add_matches(db, athlete, out["weeks"], today)
            _add_segments(db, p.athlete_id, out["weeks"])
            out["max_sessions_per_day"] = runtime.max_sessions_per_day()
            out["exercise_photos"] = strength.photos_on()
    return out


def _add_segments(db: DbSession, athlete_id: int, weeks: list[dict]) -> None:
    """Put the saved Strava segment (name and link) on each session that names one."""
    saved = {s.id: segments.segment_out(s) for s in segments.for_athlete(db, athlete_id)}
    if not saved:
        return
    for week in weeks:
        for d in week["days"]:
            for session in (d, *plan_tracker.extras(d)):
                # Not on indoor days, also on plans written before they lost their segment.
                if session.get("segment_id") in saved and plan_tracker.takes_route(session.get("type")):
                    session["segment"] = saved[session["segment_id"]]


def _add_matches(db: DbSession, athlete: User, weeks: list[dict], today: date) -> dict:
    """Put the closest Zwift / MyWhoosh workouts on each indoor day from today on (platform_catalog.py)."""
    if not platform_catalog.enabled():
        return {"enabled": False}
    platforms = platform_catalog.athlete_platforms(athlete)
    catalog = platform_catalog.load(db, platforms) if platforms else []
    days = matched = from_library = 0
    for week in weeks:
        for d in week["days"]:
            w = d.get("workout")
            if w and w.get("steps") and date.fromisoformat(d["date"]) >= today:
                days += 1
                # A swapped day is matched on what the plan asked for.
                steps = (w.get("original") or w)["steps"]
                if catalog:
                    d["platform_matches"] = platform_catalog.best_matches(db, steps, platforms, catalog)
                    matched += bool(d["platform_matches"])
                if not d.get("platform_matches"):
                    # No Zwift / MyWhoosh workout close enough: suggest one from CoachQuest's own library.
                    d["library_match"] = library.best_match(steps)
                    from_library += bool(d["library_match"])
    # Enough for the plan page to say why a day shows no match (no platform, empty catalog, none close).
    return {
        "enabled": True,
        "platforms": platforms,
        "platform_names": {p: platform_catalog.PLATFORMS[p] for p in platforms},
        "catalog_size": len(catalog),
        "catalog": {p: sum(w.platform == p for w in catalog) for p in platforms},
        "indoor_days": days,
        "matched_days": matched,
        "library_days": from_library,
        "min_score": platform_catalog.MIN_SCORE,
    }


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
    # Nothing goes to the calendar (or on to Zwift) before a coach approves the plan.
    if (p.approval or plan_approval.APPROVED) != plan_approval.APPROVED:
        return
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
        select(Plan)
        .where(Plan.athlete_id == athlete_id, Plan.start_date.is_not(None), Plan.approval == plan_approval.APPROVED)
        .order_by(Plan.created_at.desc())
    ).all()
    for p in rows:
        end = p.start_date + timedelta(weeks=len(p.weeks or []))
        if p.start_date - timedelta(days=7) <= today < end:
            return plan_out(p, db, full=True, today=today, viewer=user)
    return None


class ApprovalSetting(BaseModel):
    required: bool | None = None
    wait_hours: int | None = None


@router.put("/approval-setting")
def set_approval_setting(
    athlete: str, body: ApprovalSetting, user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    """A coach with the plans scope chooses whether the athlete's own AI plans wait for approval."""
    athlete_id = resolve_athlete_id(athlete, user)
    require_scope(db, user, athlete_id, "plans")
    if user.id == athlete_id:
        raise HTTPException(status_code=403, detail="Your coach (or an admin) decides this")
    target = db.get(User, athlete_id)
    if body.required is not None:
        target.plan_approval_off = not body.required
    if body.wait_hours is not None:
        if body.wait_hours not in plan_approval.WAIT_CHOICES:
            raise HTTPException(status_code=422, detail="Choose 24, 48 or 72 hours, or 0 for never")
        target.approval_wait_hours = body.wait_hours
    db.commit()
    return {
        "required": plan_approval.required(db, target),
        "off": target.plan_approval_off,
        "wait_hours": plan_approval.wait_hours(target),
    }


@router.get("/approval-setting")
def get_approval_setting(athlete: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    athlete_id = resolve_athlete_id(athlete, user)
    require_scope(db, user, athlete_id, "plans")
    target = db.get(User, athlete_id)
    return {
        "required": plan_approval.required(db, target),
        "off": target.plan_approval_off,
        "has_coach": bool(plan_approval.coaches(db, athlete_id)),
        "wait_hours": plan_approval.wait_hours(target),
        "can_change": user.id != athlete_id,
    }


@router.get("/{plan_id}")
def get_plan(athlete: str, plan_id: int, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    return plan_out(_plan(db, user, athlete, plan_id), db, full=True, viewer=user)


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
    _check_coach_notes(user, athlete_id, body.coach_notes)
    if not body.without_data and not has_data(db, athlete_id):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "no_data",
                "message": "No activities or wellness synced yet, so the plan can only use the goal, hours and "
                "days you give. Connect Strava or Garmin first for a plan based on real training.",
            },
        )
    monday = plan_tracker.first_week_start(body.start_date, localtime.today(target), target.week_start or 0)
    if body.kind == "maintain":
        body.weeks, body.event_date = MAINTAIN_WEEKS, None
    request = body.model_dump(mode="json", exclude={"title", "without_data"})
    if body.kind == "maintain":
        request["block_number"] = _maintain_blocks(db, athlete_id) + 1
    if not request["coach_notes"]:
        del request["coach_notes"]
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
        approval=plan_approval.AWAITING
        if plan_approval.needs_approval(db, athlete_id, user)
        else plan_approval.APPROVED,
    )
    plan_approval.log(plan, user, "created", coach_notes=body.coach_notes, notes=body.notes)
    db.add(plan)
    db.commit()
    if plan.approval == plan_approval.AWAITING:
        plan_approval.ask_coaches(db, background, plan, "new training plan")
    _workouts(db, plan, background)
    return plan_out(plan, db, full=True, viewer=user)


def _block_end(p: Plan) -> date:
    """The day after a plan's last week."""
    return p.start_date + timedelta(days=7 * (len(p.weeks or []) or (p.request or {}).get("weeks", 4)))


def _next_block_start(db: DbSession, p: Plan) -> date:
    """Right after the block, or next week if the block ended a while ago."""
    athlete = db.get(User, p.athlete_id)
    soonest = plan_tracker.first_week_start(None, localtime.today(athlete), athlete.week_start or 0)
    return max(_block_end(p), soonest)


def _maintain_blocks(db: DbSession, athlete_id: int) -> int:
    """How many maintain plans the athlete has had (the series' block number so far)."""
    rows = db.scalars(select(Plan.request).where(Plan.athlete_id == athlete_id)).all()
    return sum(1 for r in rows if (r or {}).get("kind") == "maintain")


@router.post("/{plan_id}/next-block")
async def next_block(
    athlete: str,
    plan_id: int,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """A maintain plan's next 4 weeks: the same settings, starting the day after it ends."""
    athlete_id = resolve_athlete_id(athlete, user)
    require_scope(db, user, athlete_id, "plans")
    p = db.get(Plan, plan_id)
    if p is None or p.athlete_id != athlete_id:
        raise HTTPException(status_code=404, detail="Plan not found")
    req = p.request or {}
    if req.get("kind") != "maintain" or not p.start_date:
        raise HTTPException(status_code=409, detail="Only a maintain plan has a next block")
    start = _next_block_start(db, p)
    if db.scalar(select(Plan.id).where(Plan.athlete_id == athlete_id, Plan.start_date >= _block_end(p))):
        raise HTTPException(status_code=409, detail="The next block is planned already")
    base = re.sub(r" · block \d+$", "", p.title)
    body = PlanRequest(
        **{k: v for k, v in req.items() if k in PlanRequest.model_fields and k not in ("start_date", "coach_notes")},
        title=f"{base} · block {_maintain_blocks(db, athlete_id) + 1}"[:200],
        start_date=start,
        without_data=True,
        coach_notes=req.get("coach_notes", "") if user.id != athlete_id else "",
    )
    return await create_plan(athlete, body, background, user, db)


def _check_coach_notes(user: User, athlete_id: int, notes: str) -> None:
    if notes.strip() and user.id == athlete_id:
        raise HTTPException(status_code=422, detail="Coach's notes come from a coach; use the notes box instead")


class DayEdit(BaseModel):
    type: str | None = None
    description: str | None = Field(default=None, max_length=1000)
    duration_min: int | None = Field(default=None, ge=0, le=1440)
    intensity: list[str] | None = Field(default=None, max_length=8)
    gear: str | None = Field(default=None, max_length=80)
    route: str | None = Field(default=None, max_length=300)
    locked: bool | None = None
    missed_reason: str | None = Field(default=None, max_length=40)
    # The day's other sessions, all of them (see plan_tracker.extras).
    extra_sessions: list[dict] | None = Field(default=None, max_length=3)
    # One of the athlete's saved Strava segments (segments.py), or null to clear it.
    segment_id: int | None = None


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
    if changes.get("extra_sessions") is not None:
        cleaned = [plan_tracker.clean_session(s) for s in changes["extra_sessions"]]
        if None in cleaned:
            raise HTTPException(status_code=422, detail="An extra session needs a session type other than Rest")
        limit = runtime.max_sessions_per_day()
        if len(cleaned) + 1 > limit:
            raise HTTPException(status_code=422, detail=f"At most {limit} session{'s' if limit > 1 else ''} a day")
        changes["extra_sessions"] = cleaned
    if changes.get("type") == "Rest":
        changes["extra_sessions"] = []  # a rest day has no sessions
    mine = {s.id for s in segments.for_athlete(db, p.athlete_id)}
    picked = [changes.get("segment_id")] + [s.get("segment_id") for s in changes.get("extra_sessions") or []]
    if any(sid is not None and sid not in mine for sid in picked):
        raise HTTPException(status_code=422, detail="That segment isn't one of the athlete's saved segments")
    weeks[wi]["days"][di].update(changes)
    if not plan_tracker.takes_route(weeks[wi]["days"][di].get("type")):
        weeks[wi]["days"][di]["segment_id"] = None  # indoor days get a workout, not a route or segment
    _save_weeks(db, p, weeks, background)
    return plan_out(p, db, full=True, viewer=user)


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
    return plan_out(p, db, full=True, viewer=user)


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
    fields = (
        "type",
        "description",
        "duration_min",
        "intensity",
        "gear",
        "route",
        "workout",
        "segment_id",
        "strength",
        "extra_sessions",
    )
    moved_a, moved_b = {k: day_a.get(k) for k in fields}, {k: day_b.get(k) for k in fields}
    day_a.update(moved_b)
    day_b.update(moved_a)
    _save_weeks(db, p, weeks, background)
    return plan_out(p, db, full=True, viewer=user)


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
    changed, empty = plan_tracker.apply_preferences(weeks, prefs, localtime.today(athlete_user))
    _save_weeks(db, p, weeks, background)
    return {**plan_out(p, db, full=True, viewer=user), "changed": changed, "to_plan": empty}


def training_days(athlete: User, asked: list[str]) -> list[str]:
    """The days to train on: the athlete's weekday preferences where set (Rest = no), else what was asked.

    A plan keeps the days chosen when it was made; preferences set later win on re-plans."""
    prefs = preferences_out(athlete)["weekday_prefs"]
    days = []
    for key in plan_tracker.WEEKDAYS:
        name = key.capitalize()
        chosen = prefs.get(key) or []
        if (chosen and chosen[0] != "Rest") or (not chosen and name in asked):
            days.append(name)
    return days


class Replan(BaseModel):
    reason: str = Field(default="", max_length=1000)
    coach_notes: str = Field(default="", max_length=2000)


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
    _check_coach_notes(user, p.athlete_id, body.coach_notes)
    target = db.get(User, p.athlete_id)
    today = localtime.today(target)
    weeks = _editable(p)
    first = plan_tracker.replan_from(weeks, today)
    if first == len(weeks):
        raise HTTPException(status_code=409, detail="This plan is over. Create a new plan instead.")
    tracked = plan_out(p, db, full=True, today=today)["weeks"]
    keep = [
        {
            **{k: d[k] for k in ("date", "weekday", "type", "description", "duration_min", "status")},
            "extra_sessions": plan_tracker.extras(d),
        }
        for w in tracked[first:]
        for d in w["days"]
        if plan_tracker.kept(d, today)
    ]
    request = {
        **(p.request or {}),
        "available_days": training_days(target, (p.request or {}).get("available_days") or []),
        "start_date": weeks[first]["start"],
        "weeks": len(weeks) - first,
        "replan": {
            "reason": body.reason,
            "keep": keep,
            "so_far": [{"start": w["start"], "phase": w["phase"], **w["summary"]} for w in tracked[:first]],
            # What the athlete and their coaches said about the plan and its workouts (newest 15).
            "comments": comments.for_plan(db, p, limit=15),
            **({"coach_notes": body.coach_notes.strip()} if body.coach_notes.strip() else {}),
        },
    }
    facts = build_facts(db, target, allowed_scopes(db, user, p.athlete_id), request, today)
    try:
        answer, model = await generate_plan(db, user, target, facts)
    except CoachError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    start = date.fromisoformat(weeks[first]["start"])
    fresh = plan_tracker.build_weeks(answer.get("weeks", []), start, len(weeks) - first)
    summary = (answer.get("summary_md") or "").strip()
    why = {"reason": body.reason.strip(), "coach_notes": body.coach_notes.strip()}
    needs = plan_approval.needs_approval(db, p.athlete_id, user)
    if needs and p.approval == plan_approval.APPROVED:
        # The athlete keeps following the approved plan until a coach approves the new weeks.
        pending = plan_approval.propose(p, user, fresh, summary, model, today, **why)
        db.commit()
        plan_approval.ask_coaches(db, background, p, "re-planned training plan")
        return {**plan_out(p, db, full=True, viewer=user), "changed": pending["changed"], "pending": True}
    changed = _apply_replan(p, weeks, fresh, summary, model, today)
    p.pending = None
    p.approval = plan_approval.AWAITING if needs else plan_approval.APPROVED
    plan_approval.log(p, user, "replanned", **why)
    _save_weeks(db, p, weeks, background)
    if needs:
        plan_approval.ask_coaches(db, background, p, "re-planned training plan")
    return {**plan_out(p, db, full=True, viewer=user), "changed": changed}


def _apply_replan(p: Plan, weeks: list[dict], fresh: list[dict], summary: str, model: str, today: date) -> int:
    changed = plan_tracker.merge_replan(weeks, fresh, today)
    p.content_md = f"**Re-planned {today.isoformat()}.** {summary}\n\n" + plan_tracker.markdown(weeks)
    p.model = model
    return changed


class DayReplan(BaseModel):
    note: str = Field(default="", max_length=1000)
    coach_notes: str = Field(default="", max_length=2000)


@router.post("/{plan_id}/days/{day}/replan")
async def replan_day(
    athlete: str,
    plan_id: int,
    day: date,
    body: DayReplan,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """Claude rewrites one future day. It comes back as a proposal next to the current day; it's used once
    approved (the person asking approves it themselves when they may, e.g. a coach)."""
    p = _plan(db, user, athlete, plan_id)
    if not p.weeks:
        raise HTTPException(status_code=400, detail="This older plan has no day-by-day schedule")
    _check_coach_notes(user, p.athlete_id, body.coach_notes)
    if p.pending and "day_patch" not in p.pending:
        raise HTTPException(status_code=409, detail="A re-plan of the plan is waiting: approve or send it back first")
    target = db.get(User, p.athlete_id)
    today = localtime.today(target)
    try:
        wi, di = plan_tracker.find_day(p.weeks, day.isoformat())
    except KeyError:
        raise HTTPException(status_code=404, detail="That day is not in this plan") from None
    current = p.weeks[wi]["days"][di]
    if day < today:
        raise HTTPException(status_code=409, detail="That day is over; re-plan today or a day to come")
    if current.get("locked"):
        raise HTTPException(status_code=409, detail="That day is locked 🔒: unlock it first")
    if not has_data(db, p.athlete_id):
        raise HTTPException(status_code=409, detail="No activities or wellness synced yet: connect Strava or Garmin")
    keys = ("weekday", "type", "description", "duration_min", "intensity", "segment_id", "extra_sessions")
    day_comments = [
        c for c in comments.for_plan(db, p, limit=40) if c["day"] == day.isoformat() or day.isoformat() in c["about"]
    ]
    request = {
        **(p.request or {}),
        "available_days": training_days(target, (p.request or {}).get("available_days") or []),
        "replan_day": {
            "date": day.isoformat(),
            "weekday": current["weekday"],
            "current": {k: current.get(k) for k in keys},
            "week": [
                {"date": d["date"], **{k: d.get(k) for k in keys}}
                for d in p.weeks[wi]["days"]
                if d["date"] != day.isoformat()
            ],
            "comments": day_comments[-15:],
            **({"note": body.note.strip()} if body.note.strip() else {}),
            **({"coach_notes": body.coach_notes.strip()} if body.coach_notes.strip() else {}),
        },
    }
    facts = build_facts(db, target, allowed_scopes(db, user, p.athlete_id), request, today)
    try:
        answer, model = await generate_day(db, user, target, facts)
    except CoachError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    new = plan_tracker.ai_day(answer["day"])
    plan_approval.propose_day(
        p,
        user,
        day.isoformat(),
        new,
        (answer.get("why") or "").strip(),
        model,
        reason=body.note.strip(),
        coach_notes=body.coach_notes.strip(),
    )
    db.commit()
    if plan_approval.needs_approval(db, p.athlete_id, user):
        plan_approval.ask_coaches(db, background, p, "re-planned day")
    return plan_out(p, db, full=True, viewer=user)


class SendBack(BaseModel):
    note: str = Field(min_length=3, max_length=4000)


@router.post("/{plan_id}/approve")
def approve(
    athlete: str,
    plan_id: int,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """A coach approves the waiting plan or re-plan; its workouts then go to the calendar."""
    p = _plan(db, user, athlete, plan_id)
    plan_approval.require_approver(db, user, p)
    changed = None
    if p.pending and "day_patch" in p.pending:
        weeks = _editable(p)
        patch = dict(p.pending["day_patch"])
        wi, di = plan_tracker.find_day(weeks, patch.pop("date"))
        weeks[wi]["days"][di].update(patch, gear=None, route=None, missed_reason=None)
        p.weeks, p.pending, changed = weeks, None, 1
        what = "approved the re-planned day in"
    elif p.pending:
        weeks = _editable(p)
        today = localtime.today(db.get(User, p.athlete_id))
        changed = _apply_replan(p, weeks, p.pending["fresh"], p.pending["summary"], p.pending["model"], today)
        p.weeks, p.pending = weeks, None
        what = "approved the re-plan of"
    else:
        what = "approved"
    p.approval = plan_approval.APPROVED
    note = None
    if user.id == p.athlete_id and plan_approval.required(db, user):
        note = plan_approval.athlete_decided(db, background, p, user, "approved")
    plan_approval.log(p, user, "approved", note=note)
    _save_weeks(db, p, p.weeks, background)
    plan_approval.tell_athlete(db, background, p, user, what)
    return {**plan_out(p, db, full=True, viewer=user), "changed": changed}


@router.post("/{plan_id}/send-back")
def send_back(
    athlete: str,
    plan_id: int,
    body: SendBack,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """A coach turns down the waiting plan or re-plan with a note (kept as a plan comment)."""
    p = _plan(db, user, athlete, plan_id)
    plan_approval.require_approver(db, user, p)
    if p.pending:
        p.pending = None
    else:
        p.approval = plan_approval.SENT_BACK
    if user.id == p.athlete_id and plan_approval.required(db, user):
        plan_approval.athlete_decided(db, background, p, user, "sent back")
    plan_approval.log(p, user, "sent_back", note=body.note.strip())
    db.commit()
    # The comment emails the athlete and the other coaches, and the next re-plan reads it.
    comments.add(db, background, user, p.athlete_id, "plan", p.id, body.note)
    return plan_out(p, db, full=True, viewer=user)


# ---- Downloads: indoor workouts straight from the plan ----


def _day_workout(day: dict) -> dict | None:
    w = day.get("workout")
    if not w or not w.get("steps"):
        return None
    return {"name": w["name"], "description": day.get("description") or "", "instructions": "", "steps": w["steps"]}


class UsePlatformWorkout(BaseModel):
    platform_workout_id: int


def _indoor_day(p: Plan, day: date) -> tuple[list[dict], dict]:
    if not p.weeks:
        raise HTTPException(status_code=400, detail="This older plan has no day-by-day schedule")
    weeks = _editable(p)
    try:
        wi, di = plan_tracker.find_day(weeks, day.isoformat())
    except KeyError:
        raise HTTPException(status_code=404, detail="That day is not in this plan") from None
    d = weeks[wi]["days"][di]
    if not (d.get("workout") or {}).get("steps"):
        raise HTTPException(status_code=400, detail="This day has no structured workout")
    return weeks, d


@router.post("/{plan_id}/days/{day}/platform-workout")
def use_platform_workout(
    athlete: str,
    plan_id: int,
    day: date,
    body: UsePlatformWorkout,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """Swap the day's workout for a Zwift / MyWhoosh catalog workout. The plan's own one is kept to swap back."""
    if not platform_catalog.enabled():
        raise HTTPException(status_code=403, detail="Matching Zwift / MyWhoosh workouts is switched off")
    p = _plan(db, user, athlete, plan_id)
    pw = db.get(PlatformWorkout, body.platform_workout_id)
    if pw is None:
        raise HTTPException(status_code=404, detail="Workout not found")
    weeks, d = _indoor_day(p, day)
    source = {"platform": {"id": pw.id, "platform": pw.platform, "name": platform_catalog.PLATFORMS[pw.platform]}}
    _swap_in(d, pw.name, pw.steps, source, pw.features["duration_s"])
    _save_weeks(db, p, weeks, background)
    return plan_out(p, db, full=True, viewer=user)


def _swap_in(d: dict, name: str, steps: list[dict], source: dict, duration_s: int) -> None:
    """Put another workout on a plan day, keeping the plan's own one (and length) to swap back to.
    Swapping again keeps the first one."""
    w = d["workout"]
    original = w.get("original") or {"name": w["name"], "steps": w["steps"], "duration_min": d.get("duration_min")}
    d["workout"] = {"name": name, "steps": steps, **source, "original": original}
    d["duration_min"] = round(duration_s / 60)


class UseLibraryWorkout(BaseModel):
    slug: str


@router.post("/{plan_id}/days/{day}/library-workout")
def use_library_workout(
    athlete: str,
    plan_id: int,
    day: date,
    body: UseLibraryWorkout,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """Swap the day's workout for one from CoachQuest's library. "Back to the plan's workout" undoes it."""
    if not platform_catalog.enabled():
        raise HTTPException(status_code=403, detail="Matching plan workouts is switched off")
    p = _plan(db, user, athlete, plan_id)
    lw = library.get(body.slug)
    if lw is None:
        raise HTTPException(status_code=404, detail="Workout not found")
    weeks, d = _indoor_day(p, day)
    source = {"library": {"slug": lw["slug"], "name": "CoachQuest library"}}
    _swap_in(d, lw["name"], lw["steps"], source, library.FEATURES[lw["slug"]]["duration_s"])
    _save_weeks(db, p, weeks, background)
    return plan_out(p, db, full=True, viewer=user)


@router.delete("/{plan_id}/days/{day}/platform-workout")
def restore_plan_workout(
    athlete: str,
    plan_id: int,
    day: date,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """Swap back to the workout the plan had before. Works even with matching switched off."""
    p = _plan(db, user, athlete, plan_id)
    weeks, d = _indoor_day(p, day)
    original = d["workout"].get("original")
    if not original:
        raise HTTPException(status_code=400, detail="This day already has the plan's own workout")
    d["duration_min"] = original.pop("duration_min", None) or d.get("duration_min")
    d["workout"] = original
    _save_weeks(db, p, weeks, background)
    return plan_out(p, db, full=True, viewer=user)


@router.get("/{plan_id}/days/{day}/zwo")
def day_zwo(athlete: str, plan_id: int, day: date, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """The indoor workout of one plan day as a Zwift file (.zwo), also used by MyWhoosh."""
    p = _plan(db, user, athlete, plan_id)
    try:
        wi, di = plan_tracker.find_day(p.weeks or [], day.isoformat())
    except KeyError:
        raise HTTPException(status_code=404, detail="That day is not in this plan") from None
    workout = _day_workout(p.weeks[wi]["days"][di])
    if workout is None:
        raise HTTPException(status_code=404, detail="This day has no structured workout")
    return Response(
        zwo.zwo(workout, user.display_name),
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{zwo.filename(workout["name"], day)}"'},
    )


@router.get("/{plan_id}/weeks/{index}/workouts.zip")
def week_zip(
    athlete: str, plan_id: int, index: int, user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    """All indoor workouts of one plan week in a ZIP, with the install steps."""
    p = _plan(db, user, athlete, plan_id)
    if not p.weeks or not 0 <= index < len(p.weeks):
        raise HTTPException(status_code=404, detail="Week not found")
    items = [(date.fromisoformat(d["date"]), w) for d in p.weeks[index]["days"] if (w := _day_workout(d)) is not None]
    if not items:
        raise HTTPException(status_code=404, detail="This week has no structured workouts")
    name = zwo.filename(f"{p.title} week {index + 1} workouts").removesuffix(".zwo") + ".zip"
    return Response(
        zwo.plan_zip(items, user.display_name),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# ---- Comments (see comments.py; the same rules as on AI notes and workouts) ----


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    day: date | None = None


@router.get("/{plan_id}/comments")
def list_comments(athlete: str, plan_id: int, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    p = _plan(db, user, athlete, plan_id)
    return comments.for_target(db, "plan", p.id)


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
    comments.add(db, background, user, p.athlete_id, "plan", p.id, body.body, body.day)
    return comments.for_target(db, "plan", p.id)


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
    comments.edit(db, user, comments.get(db, p.athlete_id, comment_id), body.body)
    return comments.for_target(db, "plan", p.id)


@router.delete("/{plan_id}/comments/{comment_id}")
def delete_comment(
    athlete: str, plan_id: int, comment_id: int, user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    p = _plan(db, user, athlete, plan_id)
    db.delete(comments.get(db, p.athlete_id, comment_id))
    db.commit()
    return comments.for_target(db, "plan", p.id)


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
    db.execute(delete(Comment).where(Comment.target == "plan", Comment.target_id == p.id))
    db.delete(p)
    db.commit()
    return {"ok": True}
