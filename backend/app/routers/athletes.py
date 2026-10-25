"""Athlete data, readable by the athlete and by coaches holding the matching scope.

`{athlete}` is a user id or "me".
"""

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..db import Connection, Grant, User, get_db
from ..deps import allowed_scopes, current_user, require_scope, resolve_athlete_id
from ..fitness import estimate_tss
from ..queries import activities_since, activity_out, load_curve, wellness_out, wellness_since
from .auth import user_out

router = APIRouter(prefix="/api", tags=["athletes"])


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    ftp_watts: int | None = Field(default=None, ge=50, le=600)
    lthr_bpm: int | None = Field(default=None, ge=80, le=220)
    max_hr_bpm: int | None = Field(default=None, ge=100, le=240)
    weight_kg: float | None = Field(default=None, ge=30, le=200)
    goal: str | None = Field(default=None, max_length=2000)


@router.patch("/me")
def update_profile(body: ProfileUpdate, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(user, key, value)
    if {"ftp_watts", "lthr_bpm"} & changes.keys():
        # Thresholds changed, so every activity's TSS changes too.
        for a in activities_since(db, user.id, datetime(1970, 1, 1)):
            a.tss, a.tss_method = estimate_tss(
                a.duration_s, a.norm_power, a.avg_power, a.avg_hr, a.relative_effort, user.ftp_watts, user.lthr_bpm
            )
    db.commit()
    return user_out(user)


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
    if a.id == user.id or "plans" in scopes:
        out.update(
            ftp_watts=a.ftp_watts, lthr_bpm=a.lthr_bpm, max_hr_bpm=a.max_hr_bpm, weight_kg=a.weight_kg, goal=a.goal
        )
    conns = db.scalars(select(Connection).where(Connection.user_id == a.id)).all()
    out["sources"] = [{"provider": c.provider, "last_sync_at": c.last_sync_at} for c in conns]
    return out


@router.get("/athletes/{athlete}/activities")
def activities(
    athlete: str,
    days: int = Query(default=42, ge=1, le=730),
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    athlete_id = resolve_athlete_id(athlete, user)
    require_scope(db, user, athlete_id, "activities")
    acts = activities_since(db, athlete_id, datetime.now() - timedelta(days=days))
    return [activity_out(a) for a in reversed(acts)]


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
