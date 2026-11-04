"""Athlete data, readable by the athlete and by coaches holding the matching scope.

`{athlete}` is a user id or "me".
"""

from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .. import activity_delete, dashboard, localtime, profile_sync, runtime, strava_notes, sync_options, tp_thresholds
from ..activity_types import CHOICES
from ..datefmt import DATE_FORMATS, TIME_FORMATS
from ..db import Activity, Connection, Grant, Race, User, get_db, utcnow
from ..deps import active_grant, allowed_scopes, current_user, is_friend, require_scope, resolve_athlete_id
from ..fitness import THRESHOLD_FIELDS
from ..providers import garmin, strava
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
from .load_audit import _csv_from_zip
from .preferences import preferences_out

router = APIRouter(prefix="/api", tags=["athletes"])


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    ftp_watts: int | None = Field(default=None, ge=50, le=600)
    run_ftp_watts: int | None = Field(default=None, ge=50, le=800)
    lthr_bpm: int | None = Field(default=None, ge=80, le=220)
    max_hr_bpm: int | None = Field(default=None, ge=100, le=240)
    weight_kg: float | None = Field(default=None, ge=30, le=200)
    goal: str | None = Field(default=None, max_length=2000)
    week_start: int | None = Field(default=None, ge=0, le=6)
    notify_sharing: bool | None = None
    notify_comments: bool | None = None
    notify_inactivity: bool | None = None
    notify_news: bool | None = None
    data_analysis: bool | None = None
    timezone: str | None = Field(default=None, max_length=64)
    birth_date: date | None = None
    date_format: Literal[DATE_FORMATS] | None = None
    time_format: Literal[TIME_FORMATS] | None = None
    # The threshold values sent were corrections: they count for all earlier workouts too.
    correct_history: bool = False
    # Your plan in your Strava activity descriptions (strava_notes.py).
    strava_notes: Literal["off", "manual", "auto"] | None = None

    @field_validator("birth_date")
    @classmethod
    def _birth_date(cls, v):
        if v is not None and not (date(1900, 1, 1) <= v <= date.today() - timedelta(days=5 * 365)):
            raise ValueError("Enter a real birth date")
        return v

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, v):
        if v is not None and not localtime.valid(v):
            raise ValueError("Pick a timezone from the list, e.g. Africa/Johannesburg")
        return v


@router.patch("/me")
def update_profile(body: ProfileUpdate, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    changes = body.model_dump(exclude_unset=True)
    correct = changes.pop("correct_history", False)
    changed = {k for k, v in changes.items() if getattr(user, k) != v}  # the form sends every field
    if correct:
        changed |= {k for k in changes if k in THRESHOLD_FIELDS}
    for key, value in changes.items():
        # Thresholds: from today on, or for every workout when it's a correction.
        profile_sync.record_change(user, key, getattr(user, key), value, correct=correct)
        setattr(user, key, value)
    if "weight_kg" in changes:
        # A value typed in by hand wins until Garmin records a newer weigh-in.
        user.weight_source = "manual" if changes["weight_kg"] is not None else None
        user.weight_updated_at = utcnow()
    profile_sync.mark_manual(user, changed)  # a value a coach or Garmin set stays theirs until changed
    if {"ftp_watts", "lthr_bpm", "run_ftp_watts"} & changed:
        profile_sync.recalculate_tss(db, user)
    db.commit()
    return user_out(user)


class ThresholdEntry(BaseModel):
    field: Literal["ftp_watts", "run_ftp_watts", "lthr_bpm"]
    start: date | None = Field(default=None, alias="from")  # None: before the first change
    value: int | None = Field(default=None, ge=50, le=800)


class ThresholdHistory(BaseModel):
    entries: list[ThresholdEntry] = Field(max_length=200)


def _apply_history(db: DbSession, target: User, body: ThresholdHistory) -> None:
    today = localtime.today(target)
    seen = set()
    for e in body.entries:
        if e.start and e.start > today:
            raise HTTPException(status_code=422, detail="Dates can't be in the future")
        if e.field == "lthr_bpm" and e.value is not None and not 80 <= e.value <= 220:
            raise HTTPException(status_code=422, detail="Threshold heart rate must be 80-220 bpm")
        if (e.field, e.start) in seen:
            raise HTTPException(status_code=422, detail="Two values for the same date")
        seen.add((e.field, e.start))
    hist = [
        {"field": e.field, "from": e.start.isoformat() if e.start else None, "value": e.value} for e in body.entries
    ]
    profile_sync.set_history(db, target, hist)


@router.put("/me/threshold-history")
def set_threshold_history(body: ThresholdHistory, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """FTP, run threshold power and LTHR over time: each workout is scored with the value of its date."""
    _apply_history(db, user, body)
    profile_sync.mark_manual(user, {e.field for e in body.entries})
    db.commit()
    return user_out(user)


class ThresholdsUpdate(BaseModel):
    ftp_watts: int | None = Field(default=None, ge=50, le=600)
    run_ftp_watts: int | None = Field(default=None, ge=50, le=800)
    lthr_bpm: int | None = Field(default=None, ge=80, le=220)
    max_hr_bpm: int | None = Field(default=None, ge=100, le=240)
    correct_history: bool = False  # the values sent count for every earlier workout too


def _coached(db: DbSession, user: User, athlete: str) -> User:
    """The athlete a coach changes thresholds for: needs the profile share (friends and admins only look)."""
    athlete_id = resolve_athlete_id(athlete, user)
    require_scope(db, user, athlete_id, "profile")
    return db.get(User, athlete_id)


@router.patch("/athletes/{athlete}/thresholds")
def set_athlete_thresholds(
    athlete: str, body: ThresholdsUpdate, user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    """A coach with the profile share sets the athlete's FTP, run threshold power, LTHR and max HR. A change
    counts from today (earlier workouts keep theirs); the athlete's Profile says the coach set it."""
    target = _coached(db, user, athlete)
    changes = body.model_dump(exclude_unset=True)
    correct = changes.pop("correct_history", False)
    for key, value in changes.items():
        profile_sync.record_change(target, key, getattr(target, key), value, correct=correct)
        setattr(target, key, value)
    profile_sync.mark_set_by(target, changes, user)
    if {"ftp_watts", "lthr_bpm", "run_ftp_watts"} & changes.keys():
        profile_sync.recalculate_tss(db, target)
    db.commit()
    return profile_out(target, allowed_scopes(db, user, target.id))


class TpExport(BaseModel):
    csv: str = Field(default="", max_length=5_000_000)
    zip_b64: str = Field(default="", max_length=8_000_000)  # TrainingPeaks' export can be a ZIP


@router.post("/athletes/{athlete}/thresholds/from-trainingpeaks")
def thresholds_from_trainingpeaks(
    athlete: str, body: TpExport, user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    """The thresholds TrainingPeaks used, from its Workout Summary export; nothing is saved (the athlete
    or coach ticks which to take, then saves them with PATCH .../thresholds)."""
    target = _coached(db, user, athlete)
    text = _csv_from_zip(body.zip_b64) if body.zip_b64 else body.csv
    if len(text.strip()) < 10:
        raise HTTPException(status_code=422, detail="That file is empty")
    try:
        out = tp_thresholds.estimate(text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    out["current"] = {k: getattr(target, k) for k in ("ftp_watts", "run_ftp_watts", "lthr_bpm", "max_hr_bpm")}
    return out


@router.put("/athletes/{athlete}/threshold-history")
def set_athlete_threshold_history(
    athlete: str, body: ThresholdHistory, user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    """A coach with the profile share edits the athlete's threshold history; everything is scored again."""
    target = _coached(db, user, athlete)
    _apply_history(db, target, body)
    profile_sync.mark_set_by(target, {e.field for e in body.entries}, user)
    db.commit()
    return profile_out(target, allowed_scopes(db, user, target.id))


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
    """Athletes who share data with the current user: as their coach, or as a friend (view only)."""
    grants = db.scalars(select(Grant).where(Grant.coach_id == user.id, Grant.status == "active")).all()
    out = []
    for g in grants:
        athlete = db.get(User, g.athlete_id)
        row = {
            "id": athlete.id,
            "display_name": athlete.display_name,
            "scopes": g.scopes,
            "grant_id": g.id,
            "role": g.role,
        }
        if not athlete.is_active:
            out.append({**row, "disabled": True})
            continue
        if "fitness" in g.scopes:
            curve, _ = load_curve(db, athlete.id, 1)
            row["today"] = {"ctl": curve[-1].ctl, "atl": curve[-1].atl, "tsb": curve[-1].tsb}
        out.append(row)
    return out


@router.get("/coach/dashboard")
def coach_dashboard(me: bool = False, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """Every athlete's training week on one page, those needing attention first (see dashboard.py)."""
    return dashboard.coach_dashboard(db, user, include_self=me)


@router.get("/athletes/{athlete}")
def athlete_summary(athlete: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    athlete_id = resolve_athlete_id(athlete, user)
    scopes = allowed_scopes(db, user, athlete_id)
    if not scopes:
        require_scope(db, user, athlete_id, "activities")  # raises 404
    a = db.get(User, athlete_id)
    out = {"id": a.id, "display_name": a.display_name, "scopes": sorted(scopes), "is_me": a.id == user.id}
    # An admin looking without a grant: the page says it is read only.
    out["view_only"] = is_friend(db, user, a.id)
    if a.id == user.id:  # My training points to Connections until a main activity source is picked
        mine = db.scalars(select(Connection).where(Connection.user_id == a.id)).all()
        out["sources_need_confirm"] = sync_options.overview(mine, sync_options.primary_source(db, a.id))[
            "needs_primary"
        ]
    out["admin_view"] = (
        user.is_admin
        and a.id != user.id
        and runtime.get("admin_view_data") == "on"
        and active_grant(db, a.id, user.id) is None
    )
    out.update(profile_out(a, scopes))
    conns = db.scalars(
        select(Connection).where(Connection.user_id == a.id, Connection.provider.in_(("strava", "garmin")))
    ).all()
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


class ActivityIds(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)


@router.post("/activities/delete")
def delete_activities(body: ActivityIds, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """The athlete deletes their own activities from CoachQuest (never from Strava, Garmin or Intervals.icu)."""
    return {"deleted": activity_delete.delete(db, user, body.ids)}


@router.post("/activities/remove-duplicates")
def remove_duplicate_activities(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """Delete the extra copies of sessions recorded or imported more than once."""
    return {"removed": activity_delete.remove_duplicates(db, user)}


@router.get("/activities/deleted")
def deleted_activities(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    return activity_delete.listing(db, user)


@router.post("/activities/deleted/restore")
def restore_activities(body: ActivityIds, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    return {"restored": activity_delete.restore(db, user, body.ids)}


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
    days: int = Query(default=90, ge=7, le=1830),  # up to 5 years
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
    days: int = Query(default=30, ge=1, le=1830),  # up to 5 years
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    athlete_id = resolve_athlete_id(athlete, user)
    require_scope(db, user, athlete_id, "wellness")
    return [wellness_out(w) for w in wellness_since(db, athlete_id, date.today() - timedelta(days=days))]


@router.get("/me/strava-notes")
def strava_notes_status(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """The Profile → Strava card: the mode, and whether Strava lets CoachQuest write descriptions."""
    conn = db.scalar(select(Connection).where(Connection.user_id == user.id, Connection.provider == "strava"))
    return {
        "mode": user.strava_notes or "off",
        "connected": conn is not None,
        "can_write": conn is not None and strava.can_write(conn),
        "host": strava_notes._host(),
    }


@router.post("/me/activities/{activity_id}/strava-note")
async def strava_note(
    activity_id: int, preview: bool = False, user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    """Write (or preview) the plan lines in one of your Strava activities' description. Only your own:
    coaches never write to an athlete's Strava."""
    act = db.get(Activity, activity_id)
    if act is None or act.user_id != user.id:
        raise HTTPException(status_code=404, detail="Activity not found")
    try:
        return await strava_notes.write(db, user, act, preview=preview)
    except strava_notes.NoteError as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": str(exc)}) from exc
