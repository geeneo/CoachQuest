"""Workout library, the athlete's training calendar, and .zwo / ZIP downloads.

The library is private to its owner. Scheduling, the calendar and downloads
work like plans: the athlete and coaches holding the plans scope.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .. import localtime, platforms, workouts, zwo
from ..activity_types import category
from ..db import Plan, ScheduledWorkout, User, Workout, get_db, utcnow
from ..deps import allowed_scopes, current_user, require_scope, resolve_athlete_id
from ..plan_tracker import GOAL_SHARE
from ..queries import activities_since

router = APIRouter(prefix="/api", tags=["workouts"])

BIKE = {"Road", "Virtual", "MTB", "E-MTB", "E-Bike", "Gravel"}
MAX_RANGE_DAYS = 120


def _steps(raw: list) -> list[dict]:
    try:
        return workouts.validate_steps(raw)
    except ValidationError as exc:
        err = exc.errors()[0]
        where = ".".join(str(x) for x in err["loc"][:2])
        raise HTTPException(status_code=422, detail=f"Step {where}: {err['msg']}") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


class WorkoutBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    instructions: str = Field(default="", max_length=2000)
    steps: list


def workout_out(w: Workout | ScheduledWorkout, ftp: int | None = None) -> dict:
    return {
        "id": w.id,
        "name": w.name,
        "description": w.description,
        "instructions": w.instructions,
        "sport": w.sport,
        "steps": w.steps,
        "estimate": workouts.estimate(w.steps, ftp),
        "blocks": workouts.blocks(w.steps),
        "updated_at": w.updated_at,
    }


# ---- Library ----


def _own(db: DbSession, user: User, workout_id: int) -> Workout:
    w = db.get(Workout, workout_id)
    if w is None or w.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Workout not found")
    return w


@router.get("/workouts")
def list_workouts(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    rows = db.scalars(select(Workout).where(Workout.owner_id == user.id).order_by(Workout.name)).all()
    return [workout_out(w, user.ftp_watts) for w in rows]


@router.post("/workouts")
def create_workout(body: WorkoutBody, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    w = Workout(owner_id=user.id, **body.model_dump(exclude={"steps"}), steps=_steps(body.steps))
    db.add(w)
    db.commit()
    return workout_out(w, user.ftp_watts)


class Preview(BaseModel):
    steps: list
    ftp: int | None = Field(default=None, ge=50, le=600)


@router.post("/workouts/preview")
def preview(body: Preview, user: User = Depends(current_user)):
    """Timeline and estimate for the builder, while editing. Nothing is saved."""
    steps = _steps(body.steps)
    ftp = body.ftp or user.ftp_watts
    return {"estimate": workouts.estimate(steps, ftp), "blocks": workouts.blocks(steps), "ftp": ftp}


@router.get("/workouts/{workout_id}")
def get_workout(workout_id: int, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    return workout_out(_own(db, user, workout_id), user.ftp_watts)


@router.put("/workouts/{workout_id}")
def update_workout(
    workout_id: int, body: WorkoutBody, user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    w = _own(db, user, workout_id)
    for k, v in body.model_dump(exclude={"steps"}).items():
        setattr(w, k, v)
    w.steps = _steps(body.steps)
    w.updated_at = utcnow()
    db.commit()
    return workout_out(w, user.ftp_watts)


@router.delete("/workouts/{workout_id}")
def delete_workout(workout_id: int, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """Workouts already on a calendar keep their own copy."""
    db.delete(_own(db, user, workout_id))
    db.commit()
    return {"ok": True}


def _zwo_response(name: str, xml: str, day: date | None = None) -> Response:
    return Response(
        xml,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{zwo.filename(name, day)}"'},
    )


@router.get("/workouts/{workout_id}/zwo")
def library_zwo(workout_id: int, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    w = _own(db, user, workout_id)
    return _zwo_response(w.name, zwo.zwo(workout_out(w), user.display_name))


# ---- Calendar ----


def _athlete(db: DbSession, user: User, athlete: str) -> User:
    athlete_id = resolve_athlete_id(athlete, user)
    require_scope(db, user, athlete_id, "plans")
    return db.get(User, athlete_id)


def _activity_brief(a, day: date) -> dict:
    return {
        "id": a.id,
        "date": day.isoformat(),
        "name": a.name,
        "type": category(a),
        "minutes": round(a.duration_s / 60),
        "km": round(a.distance_m / 1000, 1),
        "avg_power": round(a.avg_power) if a.avg_power else None,
        "norm_power": round(a.norm_power) if a.norm_power else None,
        "avg_hr": round(a.avg_hr) if a.avg_hr else None,
        "avg_cadence": round(a.avg_cadence) if a.avg_cadence else None,
        "tss": round(a.tss) if a.tss else None,
        "source": a.source,
    }


def scheduled_out(
    sw: ScheduledWorkout,
    athlete: User,
    today: date,
    rides: list[dict],
    names: dict[int, str],
    scopes: set[str],
) -> dict:
    """A calendar workout with its status and, once ridden, planned vs actual.

    `rides` are the bike activities matched to it. Only measured numbers are shown;
    a missing power or heart rate stays missing. Watts (which reveal FTP) need the
    profile scope, and ride details the activities scope."""
    ftp = athlete.ftp_watts if "profile" in scopes else None
    est = workouts.estimate(sw.steps, ftp)
    planned_min = round(est["duration_s"] / 60)
    actual = None
    if rides:
        minutes = sum(r["minutes"] for r in rides)
        actual = {
            "minutes": minutes,
            "completion_pct": min(100, round(100 * minutes / planned_min)) if planned_min else None,
            "avg_power": rides[0]["avg_power"] if len(rides) == 1 else None,
            "norm_power": rides[0]["norm_power"] if len(rides) == 1 else None,
            "avg_hr": rides[0]["avg_hr"] if len(rides) == 1 else None,
            "avg_cadence": rides[0]["avg_cadence"] if len(rides) == 1 else None,
            "tss": sum(r["tss"] or 0 for r in rides) or None,
            "intensity_factor": (
                round(rides[0]["norm_power"] / ftp, 2) if len(rides) == 1 and rides[0]["norm_power"] and ftp else None
            ),
            "activities": [{"id": r["id"], "name": r["name"], "source": r["source"]} for r in rides],
        }
        if "activities" not in scopes:
            # Like the plan tracker: done or not, and how much of it, but no ride details.
            actual = {"minutes": minutes, "completion_pct": actual["completion_pct"], "activities": []}
    if sw.status in ("skipped", "cancelled"):
        status = sw.status
    elif actual:
        status = "done" if minutes >= GOAL_SHARE * planned_min else "partial"
    elif sw.day < today:
        status = "missed"
    else:
        status = "today" if sw.day == today else "planned"
    return {
        **workout_out(sw, ftp),
        "date": sw.day.isoformat(),
        "status": status,
        "actual": actual,
        "assigned_by": names.get(sw.assigned_by),
        # Phase 1 has no automatic delivery: every workout is a manual download.
        "delivery": "manual",
    }


def _plan_days(db: DbSession, athlete_id: int, start: date, end: date) -> dict[str, dict]:
    """Days of the athlete's structured plans in range. Where plans overlap the newest wins."""
    plans = db.scalars(
        select(Plan).where(Plan.athlete_id == athlete_id, Plan.start_date.is_not(None)).order_by(Plan.created_at)
    ).all()
    out = {}
    for p in plans:
        for week in p.weeks or []:
            for d in week["days"]:
                if start.isoformat() <= d["date"] <= end.isoformat():
                    out[d["date"]] = {
                        "plan_id": p.id,
                        "plan_title": p.title,
                        "phase": week["phase"],
                        **{k: d[k] for k in ("type", "description", "duration_min", "intensity", "locked")},
                    }
    return out


def _match(scheduled: list[ScheduledWorkout], rides: list[dict]) -> dict[int, list[dict]]:
    """Pair one day's workouts with that day's rides: in order, extra rides go to the last workout."""
    live = [s for s in scheduled if s.status != "cancelled"]
    out: dict[int, list[dict]] = defaultdict(list)
    if not live:
        return out
    for i, r in enumerate(rides):
        out[live[min(i, len(live) - 1)].id].append(r)
    return out


@router.get("/athletes/{athlete}/calendar")
def calendar(
    athlete: str,
    start: date,
    end: date,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """Day by day: the plan's session, scheduled workouts with their status, and what was logged."""
    target = _athlete(db, user, athlete)
    if end < start or (end - start).days > MAX_RANGE_DAYS:
        raise HTTPException(status_code=422, detail=f"Pick a range of up to {MAX_RANGE_DAYS} days")
    scopes = allowed_scopes(db, user, target.id)
    tz = localtime.zone(target.timezone)
    today = localtime.today(target)

    # Fetch a day either side: a UTC timestamp can fall on the next or previous local day.
    since = datetime.combine(start - timedelta(days=1), datetime.min.time())
    acts_by_day: dict[str, list[dict]] = defaultdict(list)
    for a in activities_since(db, target.id, since):
        d = localtime.local_date(a.start_time, tz)
        if start <= d <= end:
            acts_by_day[d.isoformat()].append(_activity_brief(a, d))

    rows = db.scalars(
        select(ScheduledWorkout)
        .where(ScheduledWorkout.athlete_id == target.id, ScheduledWorkout.day >= start, ScheduledWorkout.day <= end)
        .order_by(ScheduledWorkout.day, ScheduledWorkout.id)
    ).all()
    by_day: dict[str, list[ScheduledWorkout]] = defaultdict(list)
    for sw in rows:
        by_day[sw.day.isoformat()].append(sw)

    ids = {sw.assigned_by for sw in rows if sw.assigned_by}
    names = {u.id: u.display_name for u in db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}
    plan_days = _plan_days(db, target.id, start, end)
    days = []
    for i in range((end - start).days + 1):
        d = start + timedelta(days=i)
        key = d.isoformat()
        acts = acts_by_day.get(key, [])
        matched = _match(by_day.get(key, []), [a for a in acts if a["type"] in BIKE])
        days.append(
            {
                "date": key,
                "is_today": d == today,
                "plan": plan_days.get(key),
                "workouts": [
                    scheduled_out(sw, target, today, matched.get(sw.id, []), names, scopes)
                    for sw in by_day.get(key, [])
                ],
                "activities": acts if "activities" in scopes else [],
            }
        )
    return {
        "today": today.isoformat(),
        "timezone": target.timezone or "UTC",
        "week_start": target.week_start or 0,
        "ftp_watts": target.ftp_watts if "profile" in scopes else None,
        "days": days,
    }


class Schedule(BaseModel):
    day: date
    template_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    instructions: str = Field(default="", max_length=2000)
    steps: list | None = None


@router.post("/athletes/{athlete}/workouts")
def schedule_workout(athlete: str, body: Schedule, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """Put a workout on the athlete's calendar: from your library (template_id) or written here."""
    target = _athlete(db, user, athlete)
    if body.template_id is not None:
        src = _own(db, user, body.template_id)
        fields = {
            "name": src.name,
            "description": src.description,
            "instructions": src.instructions,
            "steps": src.steps,
        }
    elif body.name and body.steps:
        fields = {
            "name": body.name,
            "description": body.description,
            "instructions": body.instructions,
            "steps": _steps(body.steps),
        }
    else:
        raise HTTPException(status_code=422, detail="Pick a workout from your library, or give a name and steps")
    sw = ScheduledWorkout(
        athlete_id=target.id, assigned_by=user.id, template_id=body.template_id, day=body.day, **fields
    )
    db.add(sw)
    db.commit()
    scopes = allowed_scopes(db, user, target.id)
    return scheduled_out(sw, target, localtime.today(target), [], {user.id: user.display_name}, scopes)


def _scheduled(db: DbSession, target: User, workout_id: int) -> ScheduledWorkout:
    sw = db.get(ScheduledWorkout, workout_id)
    if sw is None or sw.athlete_id != target.id:
        raise HTTPException(status_code=404, detail="Workout not found")
    return sw


class ScheduledEdit(BaseModel):
    day: date | None = None
    status: str | None = Field(default=None, pattern="^(planned|skipped|cancelled)$")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    instructions: str | None = Field(default=None, max_length=2000)
    steps: list | None = None

    @field_validator("steps")
    @classmethod
    def _not_empty(cls, v):
        if v is not None and not v:
            raise ValueError("A workout needs at least one step")
        return v


@router.patch("/athletes/{athlete}/workouts/{workout_id}")
def edit_scheduled(
    athlete: str,
    workout_id: int,
    body: ScheduledEdit,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """Move to another day (reschedule), skip, cancel, or change the workout itself."""
    target = _athlete(db, user, athlete)
    sw = _scheduled(db, target, workout_id)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("steps") is not None:
        changes["steps"] = _steps(changes["steps"])
    for k, v in changes.items():
        if v is not None:
            setattr(sw, k, v)
    sw.updated_at = utcnow()
    db.commit()
    return {"ok": True, "id": sw.id}


@router.delete("/athletes/{athlete}/workouts/{workout_id}")
def delete_scheduled(
    athlete: str, workout_id: int, user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    target = _athlete(db, user, athlete)
    db.delete(_scheduled(db, target, workout_id))
    db.commit()
    return {"ok": True}


# ---- Downloads ----


@router.get("/athletes/{athlete}/workouts/export.zip")
def export_zip(
    athlete: str,
    start: date | None = None,
    end: date | None = None,
    plan_id: int | None = Query(default=None),
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """Every scheduled workout in a date range, or in a plan's dates, as .zwo files in one ZIP."""
    target = _athlete(db, user, athlete)
    if plan_id is not None:
        p = db.get(Plan, plan_id)
        if p is None or p.athlete_id != target.id or not p.weeks:
            raise HTTPException(status_code=404, detail="Plan not found")
        start = date.fromisoformat(p.weeks[0]["start"])
        end = start + timedelta(days=7 * len(p.weeks) - 1)
    if start is None or end is None or end < start:
        raise HTTPException(status_code=422, detail="Give a start and end date, or a plan")
    rows = db.scalars(
        select(ScheduledWorkout)
        .where(
            ScheduledWorkout.athlete_id == target.id,
            ScheduledWorkout.day >= start,
            ScheduledWorkout.day <= end,
            ScheduledWorkout.status != "cancelled",
        )
        .order_by(ScheduledWorkout.day, ScheduledWorkout.id)
    ).all()
    if not rows:
        raise HTTPException(status_code=404, detail="No workouts are scheduled in these dates")
    data = zwo.plan_zip([(sw.day, workout_out(sw)) for sw in rows], user.display_name)
    name = f"CoachQuest workouts {start.isoformat()} to {end.isoformat()}.zip"
    return Response(
        data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"'}
    )


@router.get("/athletes/{athlete}/workouts/{workout_id}/zwo")
def scheduled_zwo(athlete: str, workout_id: int, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    target = _athlete(db, user, athlete)
    sw = _scheduled(db, target, workout_id)
    return _zwo_response(sw.name, zwo.zwo(workout_out(sw), user.display_name), sw.day)


# ---- Platforms ----


@router.get("/athletes/{athlete}/platforms")
def athlete_platforms(athlete: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """The athlete sees everything; a coach (plans scope) sees status without error details."""
    target = _athlete(db, user, athlete)
    return platforms.platforms_out(db, target, full=target.id == user.id)


class PlatformPrefs(BaseModel):
    preferred: list[str] = Field(default_factory=list, max_length=10)
    auto: dict[str, bool] = Field(default_factory=dict)


@router.put("/me/platforms")
def set_platform_prefs(body: PlatformPrefs, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """Preferred platforms, and automatic delivery where an integration supports it."""
    unknown = (set(body.preferred) | set(body.auto)) - set(platforms.IDS)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown platform: {', '.join(sorted(unknown))}")
    current = {p["id"]: p for p in platforms.platforms_out(db, user)}
    for pid, on in body.auto.items():
        if on and not current[pid]["auto_sync_available"]:
            raise HTTPException(
                status_code=409, detail=f"{current[pid]['name']} can't receive workouts automatically yet"
            )
    user.platform_prefs = {"preferred": body.preferred, "auto": body.auto}
    db.commit()
    return platforms.platforms_out(db, user)
