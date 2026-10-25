"""Athlete data, readable by the athlete and by coaches holding the matching scope.

`{athlete}` is a user id or "me".
"""

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .. import localtime, profile_sync
from ..activity_types import CHOICES
from ..db import Activity, Connection, Grant, Race, User, get_db, utcnow
from ..deps import allowed_scopes, current_user, require_scope, resolve_athlete_id
from ..providers import garmin
from ..queries import (
    activities_since,
    activity_out,
    load_curve,
    profile_out,
    volume_summary,
    wellness_out,
    wellness_since,
)
from .auth import user_out
from .preferences import preferences_out

router = APIRouter(prefix="/api", tags=["athletes"])


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    ftp_watts: int | None = Field(default=None, ge=50, le=600)
    lthr_bpm: int | None = Field(default=None, ge=80, le=220)
    max_hr_bpm: int | None = Field(default=None, ge=100, le=240)
    weight_kg: float | None = Field(default=None, ge=30, le=200)
    goal: str | None = Field(default=None, max_length=2000)
    week_start: int | None = Field(default=None, ge=0, le=6)
    notify_sharing: bool | None = None
    timezone: str | None = Field(default=None, max_length=64)

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, v):
        if v is not None and not localtime.valid(v):
            raise ValueError("Pick a timezone from the list, e.g. Africa/Johannesburg")
        return v


@router.patch("/me")
def update_profile(body: ProfileUpdate, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(user, key, value)
    if "weight_kg" in changes:
        # A value typed in by hand wins until Garmin records a newer weigh-in.
        user.weight_source = "manual" if changes["weight_kg"] is not None else None
        user.weight_updated_at = utcnow()
    profile_sync.mark_manual(user, changes)
    if {"ftp_watts", "lthr_bpm"} & changes.keys():
        profile_sync.recalculate_tss(db, user)
    db.commit()
    return user_out(user)


@router.post("/me/profile/pull-garmin")
async def pull_profile_from_garmin(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """Fill FTP, LTHR, max HR and weight from Garmin right now and say what Garmin had."""
    conn = db.scalar(select(Connection).where(Connection.user_id == user.id, Connection.provider == "garmin"))
    if conn is None:
        raise HTTPException(status_code=404, detail="Connect Garmin first (Connections page)")
    try:
        result = await garmin.pull_profile(db, conn)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Garmin didn't answer: {type(exc).__name__}") from exc
    return {**result, "user": user_out(user)}


@router.get("/athletes")
def my_athletes(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """Athletes who share data with the current user (coach view)."""
    grants = db.scalars(select(Grant).where(Grant.coach_id == user.id, Grant.status == "active")).all()
    out = []
    for g in grants:
        athlete = db.get(User, g.athlete_id)
        row = {"id": athlete.id, "display_name": athlete.display_name, "scopes": g.scopes, "grant_id": g.id}
        if "fitness" in g.scopes:
            curve, _ = load_curve(db, athlete.id, 1)
            row["today"] = {"ctl": curve[-1].ctl, "atl": curve[-1].atl, "tsb": curve[-1].tsb}
        out.append(row)
    return out


@router.get("/athletes/{athlete}")
def athlete_summary(athlete: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    athlete_id = resolve_athlete_id(athlete, user)
    scopes = allowed_scopes(db, user, athlete_id)
    if not scopes:
        require_scope(db, user, athlete_id, "activities")  # raises 404
    a = db.get(User, athlete_id)
    out = {"id": a.id, "display_name": a.display_name, "scopes": sorted(scopes), "is_me": a.id == user.id}
    out.update(profile_out(a, scopes))
    conns = db.scalars(select(Connection).where(Connection.user_id == a.id)).all()
    out["sources"] = [{"provider": c.provider, "last_sync_at": c.last_sync_at} for c in conns]
    return out


@router.get("/athletes/{athlete}/activities")
def activities(
    athlete: str,
    days: int | None = Query(default=42, ge=1, le=36600),
    since: date | None = None,
    until: date | None = None,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """Newest first. Either the last `days`, or `since`..`until` (inclusive) for a month or year view."""
    athlete_id = resolve_athlete_id(athlete, user)
    require_scope(db, user, athlete_id, "activities")
    start = datetime.combine(since, datetime.min.time()) if since else datetime.now() - timedelta(days=days or 42)
    acts = activities_since(db, athlete_id, start)
    if until:
        end = datetime.combine(until + timedelta(days=1), datetime.min.time())
        acts = [a for a in acts if a.start_time < end]
    return [activity_out(a) for a in reversed(acts)]


@router.get("/activity-types")
def activity_types(_: User = Depends(current_user)):
    return CHOICES


class ActivityEdit(BaseModel):
    type_override: str | None = None
    race_id: int | None = None
    note_tag: str | None = None


@router.patch("/activities/{activity_id}")
def edit_activity(
    activity_id: int, body: ActivityEdit, user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    """The athlete's own labels on an activity. Stored in CoachQuest only, never sent to Strava or Garmin."""
    act = db.get(Activity, activity_id)
    if act is None or act.user_id != user.id:
        raise HTTPException(status_code=404, detail="Activity not found")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("type_override") and changes["type_override"] not in CHOICES:
        raise HTTPException(status_code=422, detail=f"Type must be one of: {', '.join(CHOICES)}")
    if changes.get("race_id") is not None:
        race = db.get(Race, changes["race_id"])
        if race is None or race.user_id != user.id:
            raise HTTPException(status_code=422, detail="Unknown race")
    if changes.get("note_tag"):
        changes["note_tag"] = changes["note_tag"].strip().lower()
        if changes["note_tag"] not in preferences_out(user)["note_tags"]:
            raise HTTPException(status_code=422, detail="Add that tag under Profile → Activity note tags first")
    for key, value in changes.items():
        setattr(act, key, value or None)
    db.commit()
    return activity_out(act)


@router.get("/athletes/{athlete}/summary")
def summary(
    athlete: str,
    days: int = Query(default=30, ge=1, le=3660),
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """Volume stats for the period, activity mix and 12 weeks of elevation."""
    athlete_id = resolve_athlete_id(athlete, user)
    require_scope(db, user, athlete_id, "activities")
    today = date.today()
    since = datetime.combine(min(today - timedelta(days=days), today - timedelta(weeks=12)), datetime.min.time())
    week_start = db.get(User, athlete_id).week_start or 0
    return volume_summary(activities_since(db, athlete_id, since), days, today, week_start)


@router.get("/athletes/{athlete}/fitness")
def fitness(
    athlete: str,
    days: int = Query(default=90, ge=7, le=730),
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    athlete_id = resolve_athlete_id(athlete, user)
    require_scope(db, user, athlete_id, "fitness")
    curve, _ = load_curve(db, athlete_id, days)
    return [{"day": d.day, "tss": d.tss, "ctl": d.ctl, "atl": d.atl, "tsb": d.tsb} for d in curve]


@router.get("/athletes/{athlete}/wellness")
def wellness(
    athlete: str,
    days: int = Query(default=30, ge=1, le=365),
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    athlete_id = resolve_athlete_id(athlete, user)
    require_scope(db, user, athlete_id, "wellness")
    return [wellness_out(w) for w in wellness_since(db, athlete_id, date.today() - timedelta(days=days))]
