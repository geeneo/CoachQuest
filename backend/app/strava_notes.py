"""The athlete's plan in their Strava activity description, e.g.

    🎯 Planned: Road · Long ride on the Sillos route (4h 55m)
    ✅ Goal met
    📋 Training plan by CoachQuest · coachquest.mmc24.com

Written from CoachQuest's own plan, never by the AI from Strava data (Strava's API agreement).
The athlete opts in under Profile → Strava (`User.strava_notes`): "manual" adds a button per
activity, "auto" writes after each Strava sync. Their own text stays; these lines go under it, once,
and are replaced (not added again) when the day's status changes. It needs Strava's activity:write
scope, which the athlete gives by connecting Strava again from Profile.
"""

import logging
import re
from datetime import date, datetime, time, timedelta
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import localtime, plan_approval, plan_tracker
from .config import settings
from .db import Activity, Connection, Plan, User
from .providers import strava
from .queries import activities_since

log = logging.getLogger("coachquest.strava_notes")

MODES = ("off", "manual", "auto")
START = "🎯 Planned:"
SIGN = "Training plan by CoachQuest"
# Our lines in a description: from "🎯 Planned:" to the signature line, wherever they are.
_BLOCK = re.compile(r"\n*^🎯 Planned:.*?^📋 " + re.escape(SIGN) + r"[^\n]*\n?", re.S | re.M)
AUTO_DAYS = 3  # auto mode looks at Strava activities from the last few days
AUTO_MAX = 10  # and writes at most this many per sync (two Strava calls each)


class NoteError(Exception):
    """Why a note can't be written; `code` lets the app offer the fix (e.g. connect Strava again)."""

    def __init__(self, message: str, code: str = "", status: int = 409):
        super().__init__(message)
        self.code, self.status = code, status


def duration_text(seconds: int) -> str:
    """4h 55m, 45m."""
    h, m = divmod(round(seconds / 60), 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def _host() -> str:
    return urlparse(settings.public_base_url).netloc or "CoachQuest"


def _plan_day(db: DbSession, athlete_id: int, day: date) -> dict | None:
    """The day in the newest approved plan that covers this date."""
    plans = db.scalars(
        select(Plan)
        .where(
            Plan.athlete_id == athlete_id,
            Plan.start_date.is_not(None),
            Plan.start_date <= day,
            Plan.approval == plan_approval.APPROVED,
        )
        .order_by(Plan.created_at.desc())
    ).all()
    for p in plans:
        for week in p.weeks or []:
            for d in week["days"]:
                if d["date"] == day.isoformat():
                    return d
    return None


def _first_sentence(text: str, limit: int = 110) -> str:
    text = " ".join((text or "").split())
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    text = (m.group(1) if m else text).rstrip(".")
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def note_for(db: DbSession, athlete: User, act: Activity, today: date | None = None) -> str | None:
    """The plan lines for this activity, or None when its day had nothing planned (or isn't done)."""
    tz = localtime.zone(athlete.timezone)
    day = localtime.local_date(act.start_time, tz)
    planned = _plan_day(db, athlete.id, day)
    if not planned or planned["type"] == "Rest":
        return None
    start = datetime.combine(day - timedelta(days=1), time.min)
    same_day = [a for a in activities_since(db, athlete.id, start) if localtime.local_date(a.start_time, tz) == day]
    if act not in same_day:
        same_day.append(act)
    status = plan_tracker._status(planned, same_day, day, today or localtime.today(athlete))
    if status not in ("goal_met", "partial"):
        return None
    minutes = plan_tracker.day_minutes(planned)
    what = _first_sentence(planned.get("description", ""))
    head = f"{START} {planned['type']}" + (f" · {what}" if what else "")
    if minutes:
        head += f" ({duration_text(minutes * 60)})"
    extras = [
        f"+ {e['type']}" + (f" {e['duration_min']} min" if e.get("duration_min") else "")
        for e in plan_tracker.extras(planned)
    ]
    if extras:
        head += " " + " ".join(extras)
    if status == "goal_met":
        result = "✅ Goal met"
    else:
        logged = round(sum(a.duration_s for a in same_day) / 60)
        result = f"⚠️ Partly done ({duration_text(logged * 60)} of {duration_text(minutes * 60)})"
    return f"{head}\n{result}\n📋 {SIGN} · {_host()}"


def merge(description: str | None, note: str) -> str:
    """The athlete's own text first, then our lines once (an older version of them is replaced)."""
    own = _BLOCK.sub("\n", description or "").strip()
    return f"{own}\n\n{note}" if own else note


def _strava(db: DbSession, athlete_id: int) -> Connection | None:
    return db.scalar(
        select(Connection).where(
            Connection.user_id == athlete_id, Connection.provider == "strava", Connection.status == "active"
        )
    )


async def write(db: DbSession, athlete: User, act: Activity, preview: bool = False) -> dict:
    """Write (or with `preview`, only show) the plan lines on one Strava activity. Raises NoteError."""
    if act.source != "strava":
        raise NoteError("Only activities imported from Strava can get the plan in their description")
    note = note_for(db, athlete, act)
    if note is None:
        raise NoteError("Nothing planned that day, or the session isn't done yet", "no_plan")
    if preview:
        return {"note": note, "written": False}
    conn = _strava(db, athlete.id)
    if conn is None:
        raise NoteError("Strava isn't connected", "no_strava")
    if not strava.can_write(conn):
        raise NoteError(
            "CoachQuest may not change your Strava activities yet: allow it in Profile → Strava", "strava_write"
        )
    try:
        current = (await strava.get_activity(db, conn, act.external_id)).get("description")
        new = merge(current, note)
        if new != (current or ""):
            await strava.update_activity(db, conn, act.external_id, {"description": new})
    except LookupError as exc:
        raise NoteError(str(exc), "not_found", 404) from exc
    except Exception as exc:  # httpx errors, odd answers
        log.warning("Strava note for activity %s failed: %s", act.id, exc)
        raise NoteError("Strava didn't answer; try again in a minute", "strava_error", 502) from exc
    act.strava_note = note
    db.commit()
    return {"note": note, "written": True}


async def auto(db: DbSession, conn: Connection) -> int:
    """After a Strava sync, in auto mode: write the plan lines on recent activities whose lines are
    new or changed (e.g. a second ride turned "partly done" into "goal met"). Returns how many."""
    athlete = db.get(User, conn.user_id)
    if athlete is None or athlete.strava_notes != "auto" or not strava.can_write(conn):
        return 0
    since = datetime.combine(localtime.today(athlete) - timedelta(days=AUTO_DAYS), time.min)
    recent = db.scalars(
        select(Activity)
        .where(Activity.user_id == athlete.id, Activity.source == "strava", Activity.start_time >= since)
        .order_by(Activity.start_time)
    ).all()
    written = 0
    for act in recent:
        if written >= AUTO_MAX:
            break
        note = note_for(db, athlete, act)
        if note is None or note == act.strava_note:
            continue
        try:
            await write(db, athlete, act)
            written += 1
        except NoteError as exc:
            log.info("Auto Strava note for activity %s skipped: %s", act.id, exc)
    return written
