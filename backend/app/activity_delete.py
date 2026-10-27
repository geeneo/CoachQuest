"""Athletes delete activities from CoachQuest (never on Strava, Garmin or Intervals.icu).

A deleted activity is removed, and a note of it (source + id, and a copy for
Undo) is kept in `deleted_activities`, so the next sync doesn't bring it back.
The same session from another source (the copies `fitness.dedupe` hides) goes
with it, or the hidden copy would take its place. Load, volume and plan vs
actual are computed from the activities on every request, so they follow at
once; workout completion is matched again for the days involved.
"""

from datetime import date, datetime, timedelta

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import completion, localtime
from .db import Activity, DeletedActivity, ScheduledWorkout, User
from .fitness import LONGEST_S, SAME_SESSION_S, dedupe, same_session
from .sync_options import hidden_sources, primary_source

_FIELDS = [c.name for c in Activity.__table__.columns if c.name not in ("id", "user_id")]


def is_deleted(db: DbSession, user_id: int, source: str, external_id: str) -> bool:
    """For the syncs: True when the athlete deleted this activity."""
    return (
        db.scalar(
            select(DeletedActivity.id).where(
                DeletedActivity.user_id == user_id,
                DeletedActivity.source == source,
                DeletedActivity.external_id == external_id,
            )
        )
        is not None
    )


def _copies(db: DbSession, act: Activity) -> list[Activity]:
    """`act` and its other records of the same session (fitness.same_session)."""
    near = db.scalars(
        select(Activity).where(
            Activity.user_id == act.user_id,
            Activity.start_time >= act.start_time - timedelta(seconds=LONGEST_S),
            Activity.start_time <= act.start_time + timedelta(seconds=max(act.duration_s or 0, SAME_SESSION_S)),
        )
    )
    return [a for a in near if a.id == act.id or same_session(a, act)]


def _rematch(db: DbSession, user: User, days: list[date]) -> None:
    if days:
        completion.refresh(db, user, min(days), max(days))


def delete(db: DbSession, user: User, ids: list[int]) -> int:
    """Delete the user's activities `ids` (and their copies from other sources). Returns sessions deleted."""
    acts = [a for a in db.scalars(select(Activity).where(Activity.id.in_(ids), Activity.user_id == user.id))]
    gone: dict[int, Activity] = {}
    for a in acts:
        for c in _copies(db, a):
            gone[c.id] = c
    if not gone:
        return 0
    _remove(db, user, gone)
    return len(dedupe(list(gone.values())))


def remove_duplicates(db: DbSession, user: User) -> int:
    """Clean-up: delete the extra copies `fitness.dedupe` hides, keeping the copy that is shown.

    They go to the deleted list like any deleted activity (Undo works, the next sync doesn't bring them
    back). Sources whose activities the user switched off are left alone. Returns copies removed.
    """
    hidden = hidden_sources(db, user.id, "activities")
    acts = list(
        db.scalars(
            select(Activity)
            .where(Activity.user_id == user.id, Activity.source.not_in(hidden))
            .order_by(Activity.start_time)
        )
    )
    shown = {a.id for a in dedupe(acts, primary_source(db, user.id))}
    extra = {a.id: a for a in acts if a.id not in shown}
    if extra:
        _remove(db, user, extra)
    return len(extra)


def _remove(db: DbSession, user: User, gone: dict[int, Activity]) -> None:
    tz = localtime.zone(user.timezone)
    days = [localtime.local_date(a.start_time, tz) for a in gone.values()]
    # Workouts done with these rides lose the link; automatic matching runs again below.
    for sw in db.scalars(
        select(ScheduledWorkout).where(ScheduledWorkout.athlete_id == user.id, ScheduledWorkout.activity_id.in_(gone))
    ):
        sw.activity_id, sw.match = None, "auto"
    for a in gone.values():
        data = jsonable_encoder({f: getattr(a, f) for f in _FIELDS})
        old = db.scalar(
            select(DeletedActivity).where(
                DeletedActivity.user_id == user.id,
                DeletedActivity.source == a.source,
                DeletedActivity.external_id == a.external_id,
            )
        )
        if old is None:
            db.add(
                DeletedActivity(
                    user_id=user.id,
                    source=a.source,
                    external_id=a.external_id,
                    name=a.name,
                    sport=a.sport,
                    start_time=a.start_time,
                    data=data,
                )
            )
        db.delete(a)
    db.commit()
    _rematch(db, user, days)
    db.commit()


def listing(db: DbSession, user: User) -> list[dict]:
    rows = db.scalars(
        select(DeletedActivity).where(DeletedActivity.user_id == user.id).order_by(DeletedActivity.start_time.desc())
    ).all()
    return [
        {
            "id": r.id,
            "source": r.source,
            "name": r.name,
            "sport": r.sport,
            "start_time": r.start_time,
            "distance_km": round((r.data.get("distance_m") or 0) / 1000, 1),
            "duration_s": r.data.get("duration_s") or 0,
            "deleted_at": r.deleted_at,
        }
        for r in rows
    ]


def restore(db: DbSession, user: User, ids: list[int]) -> int:
    """Undo: put the activities back as they were, and let syncs update them again."""
    rows = db.scalars(
        select(DeletedActivity).where(DeletedActivity.id.in_(ids), DeletedActivity.user_id == user.id)
    ).all()
    tz = localtime.zone(user.timezone)
    days = []
    for r in rows:
        data = dict(r.data)
        data["start_time"] = datetime.fromisoformat(data["start_time"])
        exists = db.scalar(
            select(Activity.id).where(
                Activity.user_id == user.id, Activity.source == r.source, Activity.external_id == r.external_id
            )
        )
        if exists is None:
            db.add(Activity(user_id=user.id, **{k: v for k, v in data.items() if k in _FIELDS}))
            days.append(localtime.local_date(data["start_time"], tz))
        db.delete(r)
    db.commit()
    _rematch(db, user, days)
    db.commit()
    return len(rows)
