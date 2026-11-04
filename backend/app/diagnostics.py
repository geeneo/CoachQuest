"""Data health for one athlete: is everything CoachQuest needs coming in, and is it sound?

Five sections, each item ok / warn / bad with what to do: connections (each source's last sync and
errors), activities (per source, copies counted once, hidden sources, the latest one), the profile
values training load needs (FTP, LTHR, weight, time zone) and how much TSS is estimated, wellness
(days with data, which values never come), and the plan (current plan, calendar workouts and their
delivery). Read only; the download is the same as a file, with the training load audit's summary.
"""

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from . import load_audit, localtime, plan_approval
from .db import Activity, Connection, Plan, ScheduledWorkout, SyncJob, User, WellnessDay, utcnow
from .fitness import dedupe
from .sync_options import hidden_sources, primary_source

NAMES = {"strava": "Strava", "garmin": "Garmin", "intervals_icu": "Intervals.icu"}
# How long without a sync is still normal: Strava and Intervals.icu every 6 h, Garmin twice a day.
EXPECTED_H = {"strava": 6, "garmin": 12, "intervals_icu": 6}


def _item(level: str, text: str, fix: str | None = None, link: str | None = None) -> dict:
    out = {"level": level, "text": text}
    if fix:
        out["fix"] = fix
    if link:
        out["link"] = link
    return out


def _friendly(error: str | None) -> str:
    """A provider error in plain words (the raw text stays in the download)."""
    e = error or ""
    if "401" in e or "403" in e or "Unauthorized" in e:
        return "it refused CoachQuest's access: the link expired or was revoked"
    if "429" in e or "Rate Limit" in e:
        return "it asked CoachQuest to slow down (rate limit); CoachQuest tries again later"
    if any(x in e for x in ("Timeout", "ConnectError", "ConnectTimeout", "timed out")):
        return "CoachQuest couldn't reach it last time"
    return (e[:140] + "…") if len(e) > 140 else (e or "needs attention")


def _section(sid: str, title: str, items: list[dict]) -> dict:
    levels = [i["level"] for i in items]
    status = "bad" if "bad" in levels else "warn" if "warn" in levels else "ok"
    return {"id": sid, "title": title, "status": status, "items": items}


def _ago(when: datetime | None, now: datetime) -> str:
    if when is None:
        return "never"
    h = (now - when).total_seconds() / 3600
    return f"{round(h * 60)} min ago" if h < 1 else f"{round(h)} h ago" if h < 48 else f"{round(h / 24)} days ago"


def connections(db: DbSession, athlete: User, now: datetime) -> dict:
    conns = db.scalars(select(Connection).where(Connection.user_id == athlete.id)).all()
    items = []
    if not [c for c in conns if c.provider in ("strava", "garmin", "intervals_icu")]:
        items.append(
            _item("bad", "No activity source connected.", "Connect Strava, Garmin or Intervals.icu.", "/connections")
        )
    for c in conns:
        name = NAMES.get(c.provider, c.provider)
        if c.status != "active":
            items.append(_item("bad", f"{name}: {_friendly(c.last_error)}.", "Connect it again.", "/connections"))
            continue
        late = c.last_sync_at is None or now - c.last_sync_at > timedelta(hours=2 * EXPECTED_H.get(c.provider, 12))
        text = f"{name}: connected, last synced {_ago(c.last_sync_at, now)}."
        if c.last_error:
            items.append(_item("warn", f"{text} Last error: {_friendly(c.last_error)}."))
        elif late:
            items.append(_item("warn", f"{text} That's later than usual.", "Sync now on Connections.", "/connections"))
        else:
            items.append(_item("ok", text))
        b = c.backfill or {}
        if b.get("status") in ("running", "waiting"):
            items.append(_item("ok", f"{name}: importing older data ({b.get('stored', 0)} items so far)."))
        elif b.get("status") == "error":
            items.append(
                _item(
                    "warn",
                    f"{name}: importing older data stopped: {b.get('message') or 'unknown error'}.",
                    None,
                    "/connections",
                )
            )
    return _section("connections", "Connections", items)


def activities(db: DbSession, athlete: User, today: date) -> dict:
    since = datetime.combine(today - timedelta(days=90), datetime.min.time())
    rows = db.scalars(select(Activity).where(Activity.user_id == athlete.id, Activity.start_time >= since)).all()
    hidden = hidden_sources(db, athlete.id, "activities")
    visible = [a for a in rows if a.source not in hidden]
    kept = dedupe(visible, primary_source(db, athlete.id))
    items = []
    by_source: dict[str, int] = {}
    for a in rows:
        by_source[a.source] = by_source.get(a.source, 0) + 1
    if not rows:
        items.append(_item("bad", "No activities in the last 90 days.", "Check the connections above."))
    else:
        items.append(
            _item(
                "ok",
                f"{len(kept)} sessions in the last 90 days ("
                + ", ".join(f"{NAMES.get(s, s)} {n}" for s, n in sorted(by_source.items()))
                + ").",
            )
        )
    copies = len(visible) - len(kept)
    if copies:
        items.append(_item("ok", f"{copies} copies of the same session from more than one source, counted once."))
    if hidden:
        items.append(_item("ok", f"Left out as you chose: {', '.join(NAMES.get(h, h) for h in sorted(hidden))}."))
    synced = [src for src in by_source if src in NAMES]  # manual entries aren't a source to choose
    if rows and not primary_source(db, athlete.id) and len(synced) > 1:
        items.append(
            _item(
                "warn",
                "No main activity source chosen: copies keep the first source's.",
                "Choose it on Connections.",
                "/connections",
            )
        )
    latest = max((a.start_time for a in rows), default=None)
    if latest and (today - latest.date()).days > 14:
        items.append(_item("warn", f"Latest activity {latest:%d %b}: nothing for {(today - latest.date()).days} days."))
    no_time = [a for a in visible if not a.duration_s]
    if no_time:
        items.append(_item("warn", f"{len(no_time)} activities have no duration, so no training load."))
    return _section("activities", "Activities", items)


def profile(db: DbSession, athlete: User, today: date) -> dict:
    items = []
    for field, label, why in (
        ("ftp_watts", "FTP", "rides with power are scored by it"),
        ("lthr_bpm", "Threshold heart rate (LTHR)", "sessions without power are scored by heart rate"),
        ("weight_kg", "Weight", "W/kg and race estimates need it"),
    ):
        value = getattr(athlete, field)
        if value:
            items.append(_item("ok", f"{label}: {value}."))
        else:
            items.append(_item("warn", f"{label} not set: {why}.", "Set it in Profile.", "/profile"))
    if not athlete.timezone:
        items.append(_item("warn", "No time zone: days are counted in UTC.", "Set it in Profile.", "/profile"))
    else:
        items.append(_item("ok", f"Time zone: {athlete.timezone}."))
    summary = load_audit.audit(db, athlete, 90, today)["summary"]
    estimated = sum(m["share"] for m in summary["by_method"] if m["method"] in load_audit.ESTIMATES)
    if estimated >= 10:
        items.append(
            _item(
                "warn",
                f"{estimated}% of the last 90 days' training load is estimated (no power or heart rate to score it).",
                "See the training load audit.",
                f"/load-audit/{athlete.id}",
            )
        )
    else:
        items.append(
            _item(
                "ok",
                f"Training load is measured, not estimated, for {100 - estimated}% of the last 90 days.",
                None,
                f"/load-audit/{athlete.id}",
            )
        )
    return _section("profile", "Profile values for training load", items)


def wellness(db: DbSession, athlete: User, today: date) -> dict:
    rows = db.scalars(
        select(WellnessDay).where(WellnessDay.user_id == athlete.id, WellnessDay.day >= today - timedelta(days=14))
    ).all()
    items = []
    if not rows:
        items.append(
            _item(
                "warn",
                "No wellness data in the last 14 days (resting HR, HRV, sleep).",
                "Connect Garmin or Intervals.icu.",
                "/connections",
            )
        )
        return _section("wellness", "Wellness", items)
    items.append(
        _item("ok", f"{len(rows)} of the last 14 days have wellness data; latest {max(r.day for r in rows):%d %b}.")
    )
    for field, label in (("resting_hr", "resting HR"), ("hrv_ms", "HRV"), ("sleep_s", "sleep")):
        if not any(getattr(r, field) for r in rows):
            items.append(
                _item(
                    "warn",
                    f"No {label} in the last 14 days: that source doesn't send it, or the watch didn't record it.",
                )
            )
    return _section("wellness", "Wellness", items)


def plan(db: DbSession, athlete: User, today: date, now: datetime) -> dict:
    items = []
    current = None
    for p in db.scalars(
        select(Plan).where(Plan.athlete_id == athlete.id, Plan.start_date.is_not(None)).order_by(Plan.created_at.desc())
    ):
        weeks = p.weeks or []
        if (
            weeks
            and weeks[0]["start"]
            <= today.isoformat()
            < (date.fromisoformat(weeks[-1]["start"]) + timedelta(days=7)).isoformat()
        ):
            current = p
            break
    if current is None:
        items.append(_item("ok", "No current training plan."))
    else:
        state = current.approval or plan_approval.APPROVED
        level = "ok" if state == plan_approval.APPROVED else "warn"
        items.append(_item(level, f"Current plan: {current.title} ({state})."))
    upcoming = db.scalar(
        select(func.count())
        .select_from(ScheduledWorkout)
        .where(ScheduledWorkout.athlete_id == athlete.id, ScheduledWorkout.day >= today)
    )
    items.append(_item("ok", f"{upcoming} workouts on the calendar from today."))
    failed = db.scalars(
        select(SyncJob).where(
            SyncJob.athlete_id == athlete.id,
            SyncJob.status.in_(("failed", "blocked")),
            SyncJob.created_at >= now - timedelta(days=30),
        )
    ).all()
    if failed:
        last = max(failed, key=lambda j: j.created_at)
        items.append(
            _item(
                "bad",
                f"{len(failed)} workout deliveries failed in the last 30 days (latest: "
                f"{last.workout_name or 'a workout'} to {NAMES.get(last.provider, last.provider)}: "
                f"{last.last_error or last.status}).",
                "Retry them on Connections → sync history.",
                "/connections",
            )
        )
    queued = db.scalar(
        select(func.count()).select_from(SyncJob).where(SyncJob.athlete_id == athlete.id, SyncJob.status == "queued")
    )
    if queued:
        items.append(_item("ok", f"{queued} workout deliveries waiting to go out."))
    return _section("plan", "Plan and calendar", items)


def check(db: DbSession, athlete: User) -> dict:
    now = utcnow()
    today = localtime.today(athlete)
    sections = [
        connections(db, athlete, now),
        activities(db, athlete, today),
        profile(db, athlete, today),
        wellness(db, athlete, today),
        plan(db, athlete, today, now),
    ]
    levels = [s["status"] for s in sections]
    return {
        "athlete": {"id": athlete.id, "name": athlete.display_name},
        "checked_at": now.isoformat() + "Z",
        "status": "bad" if "bad" in levels else "warn" if "warn" in levels else "ok",
        "sections": sections,
    }


def report(db: DbSession, athlete: User, build: str) -> dict:
    """The download: the check, the last 90 days' training load summary and days, and the version."""
    audit = load_audit.audit(db, athlete, 90)
    return {
        "coachquest_build": build,
        "diagnostics": check(db, athlete),
        "training_load": {k: audit[k] for k in ("meta", "summary", "warnings", "days")},
    }
