"""Coach dashboard: every athlete's training week on one page.

One row per athlete who shares with the coach, built from what CoachQuest
already computes (compliance, completion, readiness, load). Each part needs the
scope it needs elsewhere, so a coach never sees more here than on the
athlete's own pages: plans for the week, workouts, readiness, races and
comments; fitness for load; activities for volume.

`attention` ranks athletes who need a look first; `flags` say why.
"""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import compliance, localtime
from .assessments import _current_plan_day
from .db import AccessLog, Assessment, Comment, Connection, Grant, Plan, SyncJob, User, utcnow
from .deps import SCOPES
from .fitness import week_start_of
from .queries import activities_since, load_curve
from .routers.races import race_out, upcoming

FATIGUE_TSB = -30


def athlete_row(db: DbSession, coach: User, athlete: User, scopes: set[str]) -> dict:
    today = localtime.today(athlete)
    ws = week_start_of(today, athlete.week_start or 0)
    row: dict = {
        "id": athlete.id,
        "name": athlete.display_name,
        "scopes": sorted(scopes),
        "today": today.isoformat(),
        "week_start": ws.isoformat(),
        "flags": [],
    }
    flags, attention = row["flags"], 0

    conns = db.scalars(
        select(Connection).where(Connection.user_id == athlete.id, Connection.provider.in_(("strava", "garmin")))
    ).all()
    synced = [c.last_sync_at for c in conns if c.last_sync_at]
    row["last_sync_at"] = max(synced) if synced else None
    if any(c.status == "error" for c in conns):
        flags.append("sync problem")
        attention += 1
    elif not conns:
        flags.append("no data source")

    if "plans" in scopes:
        week = compliance.week(db, athlete, scopes, ws, today)
        row["week"] = {k: v for k, v in week.items() if k not in ("workouts", "week_start", "is_current")}
        row["today_workouts"] = [
            {"id": w["id"], "name": w["name"], "status": w["status"], "planned_min": w["planned_min"]}
            for w in week["workouts"]
            if w["date"] == today.isoformat()
        ]
        row["today_plan"] = _current_plan_day(db, athlete.id, today)
        if week["missed"]:
            flags.append(f"{week['missed']} missed")
            attention += 2 * week["missed"]
        if week.get("under_target"):
            flags.append(f"{week['under_target']} under target")
            attention += week["under_target"]
        note = db.scalar(
            select(Assessment)
            .where(Assessment.athlete_id == athlete.id, Assessment.kind == "daily", Assessment.period_start == today)
            .order_by(Assessment.created_at.desc())
        )
        row["readiness"] = note.verdict if note else None
        if row["readiness"] in ("rest", "easy"):
            flags.append(f"readiness: {row['readiness']}")
            attention += 2 if row["readiness"] == "rest" else 1
        races = upcoming(db, athlete.id, today)
        row["next_race"] = (
            {k: v for k, v in race_out(races[0], today).items() if k in ("name", "target_date", "days_to_go")}
            if races
            else None
        )
        row["new_comments"] = len(
            db.scalars(
                select(Comment.id).where(
                    Comment.athlete_id == athlete.id,
                    Comment.created_at >= utcnow() - timedelta(days=7),
                    Comment.author_id != coach.id,
                )
            ).all()
        )
        waiting = db.scalars(
            select(Plan.id).where(
                Plan.athlete_id == athlete.id, (Plan.approval == "awaiting") | Plan.pending.is_not(None)
            )
        ).all()
        row["plans_waiting"] = len(waiting)
        if waiting:
            flags.append(f"{len(waiting)} plan{'s' if len(waiting) > 1 else ''} to approve")
            attention += 2
        failed = db.scalars(
            select(SyncJob.id).where(SyncJob.athlete_id == athlete.id, SyncJob.status.in_(("failed", "blocked")))
        ).all()
        if failed:
            flags.append("workout delivery failed")
            attention += 1

    if "fitness" in scopes:
        curve, _ = load_curve(db, athlete.id, 8, today)
        now = curve[-1]
        row["load"] = {
            "ctl": now.ctl,
            "atl": now.atl,
            "tsb": now.tsb,
            "ctl_change_7d": round(now.ctl - curve[0].ctl, 1),
        }
        if now.tsb < FATIGUE_TSB:
            flags.append("fatigue")
            attention += 3

    if "activities" in scopes:
        acts = activities_since(db, athlete.id, datetime.combine(ws - timedelta(days=1), datetime.min.time()))
        tz = localtime.zone(athlete.timezone)
        week_acts = [a for a in acts if localtime.local_date(a.start_time, tz) >= ws]
        row["volume"] = {
            "activities": len(week_acts),
            "minutes": round(sum(a.duration_s for a in week_acts) / 60),
            "km": round(sum(a.distance_m for a in week_acts) / 1000, 1),
        }
        last = max((a.start_time for a in acts), default=None)
        row["last_activity_at"] = last

    row["attention"] = attention
    return row


def coach_dashboard(db: DbSession, coach: User, include_self: bool = False) -> list[dict]:
    """Athletes sharing with `coach` (and the coach's own row if asked), most in need of attention first."""
    rows = []
    grants = db.scalars(select(Grant).where(Grant.coach_id == coach.id, Grant.status == "active")).all()
    for g in grants:
        athlete = db.get(User, g.athlete_id)
        if athlete is None or not athlete.is_active:
            continue
        scopes = set(g.scopes or []) & set(SCOPES)
        db.add(AccessLog(athlete_id=athlete.id, viewer_id=coach.id, resource="dashboard"))
        rows.append(athlete_row(db, coach, athlete, scopes))
    db.commit()
    if include_self:
        rows.append({**athlete_row(db, coach, coach, set(SCOPES)), "is_me": True})
    return sorted(rows, key=lambda r: (-r["attention"], r["name"].lower()))
