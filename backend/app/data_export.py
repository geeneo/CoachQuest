"""Anonymised data for improving CoachQuest's logic (Admin → Data, super admins).

All users who haven't opted out (Profile: `data_analysis`), as tables of plain numbers:

- users: a code, age band, FTP, LTHR, max HR, weight (to 5 kg), week start, races planned;
- activities: date, sport, indoor, minutes, km, climbing, power, heart rate, TSS and how it was scored;
- load: each day's TSS, CTL, ATL, TSB;
- plan_days: planned type, minutes, TSS and zones, against what was done (status, minutes, TSS),
  and whether the plan followed a change or a move;
- wellness: resting HR, HRV, sleep, sleep score, Body Battery, stress, steps;
- assessments: the readiness verdicts (go / easy / rest) and when weekly reviews were written (no text).

Anonymised: users are codes (HMAC of their id, stable between exports, not reversible without the
server's key), no names, emails, goals, notes or activity names; each user's dates move by a fixed
number of whole weeks (weekdays and spacing stay right, real dates don't match public activities);
weight is rounded and age is a 10-year band.

Strava data is left out, as Strava's API agreement doesn't allow using it to develop or train AI
applications (CoachQuest's coach is one): activities from Strava aren't exported, and load and plan
statuses are worked out from the other activities (Garmin, Intervals.icu, manual) only.
"""

import csv
import hashlib
import hmac
import io
import zipfile
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import localtime, plan_tracker
from .activity_types import category, is_outdoor
from .config import settings
from .db import Activity, Assessment, Plan, Race, User, WellnessDay
from .fitness import daily_tss, dedupe, pmc
from .sync_options import primary_source

LEFT_OUT = {"strava"}
VERSION = "data-export 1"


def code(user_id: int) -> str:
    key = (settings.token_encryption_key or "coachquest").encode()
    return "u_" + hmac.new(key, f"user:{user_id}".encode(), hashlib.sha256).hexdigest()[:10]


def _shift(user_id: int) -> timedelta:
    """A fixed move of -52..+52 whole weeks per user (weekdays and spacing stay right)."""
    key = (settings.token_encryption_key or "coachquest").encode()
    n = int(hmac.new(key, f"shift:{user_id}".encode(), hashlib.sha256).hexdigest()[:8], 16)
    return timedelta(weeks=(n % 105) - 52)


def _age_band(birth: date | None, today: date) -> str | None:
    if birth is None:
        return None
    age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
    lo = age // 10 * 10
    return f"{lo}-{lo + 9}"


def _r(v, n=0):
    return None if v is None else round(v, n) if n else round(v)


def users_in(db: DbSession) -> list[User]:
    return list(db.scalars(select(User).where(User.approved, User.data_analysis.is_(True)).order_by(User.id)).all())


def tables(db: DbSession, since: date | None = None, until: date | None = None) -> dict[str, list[dict]]:
    """Every table, for the users in, from `since` to `until` (real dates; the export shows them moved)."""
    today = date.today()
    until = until or today
    since = since or until - timedelta(days=365)
    out: dict[str, list[dict]] = {
        k: [] for k in ("users", "activities", "load", "plan_days", "wellness", "assessments")
    }
    for u in users_in(db):
        uc, shift = code(u.id), _shift(u.id)
        tz = localtime.zone(u.timezone)

        def moved(d: date, shift: timedelta = shift) -> str:
            return (d + shift).isoformat()

        races = db.scalars(select(Race).where(Race.user_id == u.id)).all()
        out["users"].append(
            {
                "user": uc,
                "age_band": _age_band(u.birth_date, today),
                "ftp_w": u.ftp_watts,
                "lthr_bpm": u.lthr_bpm,
                "max_hr_bpm": u.max_hr_bpm,
                "weight_kg": round(u.weight_kg / 5) * 5 if u.weight_kg else None,
                "week_start": u.week_start or 0,
                "races": len(races),
                "races_multi_day": sum(1 for r in races if (r.days or 1) > 1),
            }
        )
        warm = since - timedelta(days=120)  # load needs its warm-up, as on the Fitness chart
        rows = db.scalars(
            select(Activity)
            .where(
                Activity.user_id == u.id,
                Activity.source.not_in(LEFT_OUT),
                Activity.start_time >= datetime.combine(warm, datetime.min.time()),
                Activity.start_time < datetime.combine(until + timedelta(days=1), datetime.min.time()),
            )
            .order_by(Activity.start_time)
        ).all()
        acts = dedupe(list(rows), primary_source(db, u.id))
        for a in acts:
            day = localtime.local_date(a.start_time, tz)
            if day < since:
                continue
            out["activities"].append(
                {
                    "user": uc,
                    "date": moved(day),
                    "weekday": day.strftime("%a"),
                    "hour": a.start_time.replace(tzinfo=localtime.UTC).astimezone(tz).hour,
                    "sport": category(a),
                    "indoor": not is_outdoor(a),
                    "source": a.source,
                    "minutes": _r((a.duration_s or 0) / 60),
                    "km": _r((a.distance_m or 0) / 1000, 1),
                    "climb_m": _r(a.elevation_m),
                    "avg_power_w": _r(a.avg_power),
                    "norm_power_w": _r(a.norm_power),
                    "avg_hr": _r(a.avg_hr),
                    "max_hr": _r(a.max_hr),
                    "avg_cadence": _r(a.avg_cadence),
                    "tss": _r(a.tss, 1),
                    "tss_method": a.tss_method,
                    "is_race": bool(a.is_race),
                }
            )
        for p in pmc(daily_tss([(a.start_time, a.tss) for a in acts], tz), warm, until):
            if p.day >= since:
                out["load"].append(
                    {"user": uc, "date": moved(p.day), "tss": p.tss, "ctl": p.ctl, "atl": p.atl, "tsb": p.tsb}
                )
        for plan_no, p in enumerate(
            db.scalars(select(Plan).where(Plan.athlete_id == u.id, Plan.start_date.is_not(None)).order_by(Plan.id)), 1
        ):
            weeks = plan_tracker.with_actuals(p.weeks or [], acts, today, tz)
            for wi, w in enumerate(weeks):
                for d in w["days"]:
                    day = date.fromisoformat(d["date"])
                    if not since <= day <= until:
                        continue
                    a = d["actual"] or {}
                    out["plan_days"].append(
                        {
                            "user": uc,
                            "plan": plan_no,
                            "plan_kind": (p.request or {}).get("kind") or "event",
                            "week": wi + 1,
                            "phase": w["phase"],
                            "date": moved(day),
                            "weekday": d["weekday"],
                            "type": d["type"],
                            "extra_sessions": "+".join(e["type"] for e in plan_tracker.extras(d)),
                            "planned_min": plan_tracker.day_minutes(d),
                            "planned_tss": d["planned_tss"],
                            "zones": " ".join(d.get("intensity") or []),
                            "structured_workout": bool(d.get("workout")),
                            "route": bool(d.get("segment_id")),
                            "status": d["status"],
                            "done_min": a.get("minutes"),
                            "done_tss": a.get("tss"),
                            "done_types": "+".join(a.get("types") or []),
                            "missed_reason": d.get("missed_reason") or "",
                            "changed_from": (d.get("changed_from") or {}).get("type", ""),
                            "moved": "from" if d.get("moved_from") else "to" if d.get("moved_to") else "",
                            "locked": bool(d.get("locked")),
                        }
                    )
        for w in db.scalars(
            select(WellnessDay)
            .where(WellnessDay.user_id == u.id, WellnessDay.day >= since, WellnessDay.day <= until)
            .order_by(WellnessDay.day)
        ):
            out["wellness"].append(
                {
                    "user": uc,
                    "date": moved(w.day),
                    "source": w.source,
                    "resting_hr": _r(w.resting_hr),
                    "hrv_ms": _r(w.hrv_ms, 1),
                    "sleep_h": round(w.sleep_s / 3600, 2) if w.sleep_s else None,
                    "sleep_score": _r(w.sleep_score),
                    "body_battery_max": _r(w.body_battery_max),
                    "stress_avg": _r(w.stress_avg),
                    "steps": w.steps,
                }
            )
        for x in db.scalars(
            select(Assessment)
            .where(Assessment.athlete_id == u.id, Assessment.period_start >= since, Assessment.period_start <= until)
            .order_by(Assessment.period_start)
        ):
            out["assessments"].append(
                {"user": uc, "date": moved(x.period_start), "kind": x.kind, "verdict": x.verdict or ""}
            )
    return out


def _csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return buf.getvalue()


README = """CoachQuest anonymised data export ({version}), {made} (real dates {since} to {until}).

For improving CoachQuest's logic. Users who opted out (Profile) aren't in it.

Anonymised:
- "user" is a code, the same for one person in every export, not reversible without the server's key.
- No names, emails, goals, notes, activity names or exact weights; age as a 10-year band.
- Each user's dates are moved by a fixed number of whole weeks: weekdays and the spacing between days
  are right, the dates aren't the real ones. Compare users by weekday, phase or day counts, not by date.

Left out: activities from Strava (its API agreement doesn't allow its data in developing or training AI
applications). Load (CTL/ATL/TSB) and plan statuses are worked out from the other activities only, so
for users who record only on Strava they show no training.

Files:
- users.csv: age_band, ftp_w, lthr_bpm, max_hr_bpm, weight_kg (to 5 kg), week_start (0 = Monday), races.
- activities.csv: one row per session (copies from two sources counted once); tss_method = power, hr,
  effort (Strava Relative Effort), duration (50 an hour estimate) or intervals_icu.
- load.csv: per day: tss, ctl (42-day), atl (7-day), tsb (the previous day's ctl - atl).
- plan_days.csv: per planned day: plan number per user, week, phase, type, planned minutes and TSS
  (estimated for outdoor sessions), zones, status (goal_met, partial, missed, rest, extra, moved,
  planned, today), done minutes / TSS / types, missed_reason, changed_from (done as another type),
  moved (from / to another day), locked.
- wellness.csv: resting_hr, hrv_ms, sleep_h, sleep_score, body_battery_max, stress_avg, steps.
- assessments.csv: AI readiness verdicts (go / easy / rest) and weekly reviews (no text).
"""


def zip_bytes(data: dict[str, list[dict]], since: date, until: date) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "README.txt",
            README.format(
                version=VERSION, made=date.today().isoformat(), since=since.isoformat(), until=until.isoformat()
            ),
        )
        for name, rows in data.items():
            z.writestr(f"{name}.csv", _csv(rows))
    return buf.getvalue()
