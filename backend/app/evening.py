"""The evening preview: tomorrow's session and a verdict on training load alone, by email the evening before.

For early riders who want to know tonight what tomorrow brings. Written in code (no AI request, so it
doesn't count toward the monthly allowance): tomorrow's planned session from the plan, tomorrow morning's
form (today's logged load; today's planned session when nothing is logged yet), and the verdict that
form gives (assessments.readiness_verdict without wellness; the taper rules within two weeks of a race).
The morning note confirms it, or changes it, once last night's sleep and HRV are in.

Sent once a day at the athlete's "preview_time" (local, default 20:00); the date it was sent for is kept in
ai_settings["preview_sent_for"].
"""

import logging
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm.attributes import flag_modified

from . import assessments, localtime, mailer, plan_tracker, taper
from .db import SessionLocal, User
from .queries import load_curve

log = logging.getLogger("coachquest.evening")

DEFAULT_TIME = "20:00"


def _time(user: User) -> time:
    try:
        return time.fromisoformat((user.ai_settings or {}).get("preview_time") or DEFAULT_TIME)
    except ValueError:
        return time.fromisoformat(DEFAULT_TIME)


def _session(day: dict | None) -> str:
    if day is None:
        return "Nothing planned yet."
    if day["type"] == "Rest":
        return "Rest day."
    parts = [day["type"]]
    if day.get("duration_min"):
        parts.append(f"{day['duration_min']} min")
    if day.get("intensity"):
        parts.append(", ".join(day["intensity"]))
    text = " · ".join(parts)
    if day.get("description"):
        text += f": {day['description']}"
    for extra in day.get("extra_sessions") or []:
        text += f"\n- Also: {extra['type']}" + (f", {extra['duration_min']} min" if extra.get("duration_min") else "")
    return text


def preview(db: DbSession, user: User, today: date) -> dict:
    """Tomorrow's session, tomorrow morning's form and the verdict it gives (code only)."""
    tomorrow = today + timedelta(days=1)
    planned_today = assessments._current_plan_day(db, user.id, today)
    planned = assessments._current_plan_day(db, user.id, tomorrow)
    curve, _ = load_curve(db, user.id, 2, today)
    now, before = curve[-1], curve[-2]
    counted = "today's logged training"
    if now.tss == 0 and planned_today and planned_today["type"] != "Rest":
        tss = plan_tracker.day_tss({**planned_today, "extra_sessions": planned_today.get("extra_sessions") or []})
        load = taper.project(before.ctl, before.atl, [tss])
        counted = "today's planned session (nothing logged yet)"
    else:
        load = {"ctl": now.ctl, "atl": now.atl, "tsb": round(now.ctl - now.atl, 1)}
    race = taper.race_ahead(db, user.id, tomorrow)
    days_to_go = (race.target_date - tomorrow).days if race else None
    verdict, reasons, _ = assessments.readiness_verdict([], load["tsb"], days_to_go, tomorrow)
    if verdict == "go":
        reasons = [f"Form (TSB) {load['tsb']:+.0f} is fine for it"]
    return {
        "tomorrow": tomorrow,
        "planned": planned,
        "load": load,
        "counted": counted,
        "verdict": verdict,
        "reasons": reasons,
        "race": race,
        "days_to_go": days_to_go,
    }


def markdown(p: dict, user: User) -> str:
    load, verdict = p["load"], p["verdict"].upper()
    lines = [
        f"**Tomorrow, {taper.label(p['tomorrow'])}: {verdict} on training load**",
        "",
        _session(p["planned"]),
        "",
        f"Tomorrow morning's form: {load['tsb']:+.0f} (fitness {load['ctl']:.0f}, fatigue {load['atl']:.0f}), "
        f"counting {p['counted']}.",
    ]
    if p["reasons"]:
        lines.append("Why: " + "; ".join(p["reasons"]) + ".")
    if p["race"] is not None:
        lines.append(f"{p['race'].name} is {p['days_to_go']} day{'s' if p['days_to_go'] != 1 else ''} away.")
    if verdict == "EASY" and p["planned"] and p["planned"]["type"] != "Rest":
        lines += ["", "Keep it in Z1-Z2 and shorter, unless the morning note says otherwise."]
    elif verdict == "REST":
        lines += ["", "Plan on resting, unless the morning note says otherwise."]
    s = user.ai_settings or {}
    if s.get("daily"):
        lines += [
            "",
            f"This rests on training load only. Your morning note (from {s.get('daily_time') or '06:30'}) "
            "confirms it, or changes it, once last night's sleep and HRV are in.",
        ]
    return "\n".join(lines)


def due(user: User, now: datetime) -> date | None:
    """Today's local date when the preview is due now and not sent yet, else None."""
    s = user.ai_settings or {}
    if not (s.get("preview") and s.get("email")):
        return None
    local = now.astimezone(localtime.zone(user.timezone))
    today = local.date()
    if local.time() < _time(user) or s.get("preview_sent_for") == (today + timedelta(days=1)).isoformat():
        return None
    return today


async def send(db: DbSession, user: User, today: date) -> None:
    p = preview(db, user, today)
    subject = f"Tomorrow: {p['verdict'].upper()}" + (f" · {p['planned']['type']}" if p["planned"] else "")
    md = markdown(p, user)
    s = dict(user.ai_settings or {})
    s["preview_sent_for"] = p["tomorrow"].isoformat()  # also when the email fails: no retry storm
    user.ai_settings = s
    flag_modified(user, "ai_settings")
    db.commit()
    try:
        await mailer.send(user.email, subject, *assessments.email_bodies(user, subject, md))
    except mailer.MailError as exc:
        log.warning("Emailing the evening preview to user %s failed: %s", user.id, exc)


async def run(now: datetime | None = None) -> None:
    """Scheduler job, every few minutes."""
    now = now or datetime.now(UTC)
    if not mailer.configured():
        return
    db = SessionLocal()
    try:
        for user in db.scalars(select(User).where(User.is_active)).all():
            today = due(user, now)
            if today is None or user.ai_disabled or user.emails_disabled:
                continue
            if not assessments.has_recent_data(db, user):
                continue
            await send(db, user, today)
    finally:
        db.close()
