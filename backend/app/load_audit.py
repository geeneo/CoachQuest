"""Training load audit: how CoachQuest got an athlete's CTL, ATL and TSB, day by day and activity by
activity, to compare with another platform (TrainingPeaks). Read only: it changes nothing.

For every activity in the period: its source and external ID, whether it was counted or dropped as
a copy of another (and which one), its TSS and how that was worked out (power and FTP, heart rate
and LTHR, Strava's Relative Effort, or 50 an hour from the duration), and the power intensity. For
every day, rest days included: the TSS counted, CTL, ATL and TSB, exactly as the Fitness chart has
them. Warnings point at what usually explains a difference. A TrainingPeaks export (CSV with a date
and a TSS column) can be compared day by day, with the first day the two differ.
"""

import csv
import io
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import localtime
from .activity_types import category
from .db import Activity, User
from .fitness import ATL_DAYS, CTL_DAYS, dedupe, pmc, same_session
from .localtime import local_date
from .queries import WARMUP_DAYS
from .sync_options import hidden_sources, primary_source

VERSION = "load-audit 2"
METHODS = {
    "power": "Power and FTP",
    "hr": "Heart rate and LTHR",
    "effort": "Strava Relative Effort, used as TSS",
    "duration": "Estimate: 50 TSS an hour",
    "intervals_icu": "Intervals.icu training load",
    "light": "Walk or hike: light (heart rate, at most 15 an hour)",
    "not scored": "Strength, yoga, workouts: not scored (0)",
    "none": "No duration",
}
ESTIMATES = ("effort", "duration")


def audit(db: DbSession, athlete: User, days: int = 180, today: date | None = None) -> dict:
    tz = localtime.zone(athlete.timezone)
    today = today or localtime.today(athlete)
    start = today - timedelta(days=days - 1)
    warm = start - timedelta(days=WARMUP_DAYS)
    rows = db.scalars(
        select(Activity)
        .where(
            Activity.user_id == athlete.id,
            Activity.start_time >= datetime.combine(warm - timedelta(days=1), datetime.min.time()),
        )
        .order_by(Activity.start_time)
    ).all()
    hidden = hidden_sources(db, athlete.id, "activities")
    primary = primary_source(db, athlete.id)
    visible = [a for a in rows if a.source not in hidden]
    kept = dedupe(visible, primary)
    kept_ids = {a.id for a in kept}

    def counted_as(a: Activity) -> int | None:
        return next((k.id for k in kept if k.id != a.id and same_session(a, k)), None)

    per_day: dict[date, float] = defaultdict(float)
    for a in kept:
        per_day[local_date(a.start_time, tz)] += a.tss or 0
    curve = {p.day: p for p in pmc(dict(per_day), warm, today)}

    activities = []
    for a in rows:
        day = local_date(a.start_time, tz)
        if day < start:
            continue
        if a.source in hidden:
            status, canonical = "hidden source", None
        elif a.id in kept_ids:
            status, canonical = "counted", a.id
        else:
            canonical = counted_as(a)
            status = "duplicate"
        power = a.norm_power or a.avg_power
        activities.append(
            {
                "date": day.isoformat(),
                "start_local": a.start_time.replace(tzinfo=UTC).astimezone(tz).strftime("%Y-%m-%d %H:%M"),
                "utc_date_differs": a.start_time.date() != day,
                "id": a.id,
                "source": a.source,
                "external_id": a.external_id,
                "canonical_id": canonical,
                "status": status,
                "name": a.name,
                "sport": category(a),
                "minutes": round((a.duration_s or 0) / 60),
                "tss": round(a.tss or 0, 1),
                "counted_tss": round(a.tss or 0, 1) if status == "counted" else 0,
                "method": a.tss_method,
                "power_w": round(power) if power else None,
                "intensity": round(power / athlete.ftp_watts, 2) if power and athlete.ftp_watts else None,
                "avg_hr": round(a.avg_hr) if a.avg_hr else None,
                "relative_effort": a.relative_effort,
            }
        )
    days_out = []
    for i in range(days):
        d = start + timedelta(days=i)
        p = curve[d]
        n = sum(1 for x in activities if x["date"] == d.isoformat() and x["status"] == "counted")
        days_out.append(
            {
                "date": d.isoformat(),
                "activities": n,
                "tss": p.tss,
                "ctl": p.ctl,
                "atl": p.atl,
                "tsb": p.tsb,
                "rest": n == 0,
            }
        )

    counted = [x for x in activities if x["status"] == "counted"]
    total = sum(x["counted_tss"] for x in counted) or 0
    by_method: dict[str, dict] = {}
    for x in counted:
        m = by_method.setdefault(
            x["method"],
            {"method": x["method"], "label": METHODS.get(x["method"], x["method"]), "activities": 0, "tss": 0.0},
        )
        m["activities"] += 1
        m["tss"] += x["counted_tss"]
    for m in by_method.values():
        m["tss"] = round(m["tss"])
        m["share"] = round(100 * m["tss"] / total) if total else 0
    warnings = _warnings(athlete, activities, by_method, total)
    return {
        "meta": {
            "athlete": athlete.display_name,
            "from": start.isoformat(),
            "to": today.isoformat(),
            "timezone": athlete.timezone or "UTC",
            "ftp_watts": athlete.ftp_watts,
            "lthr_bpm": athlete.lthr_bpm,
            "primary_source": primary,
            "hidden_sources": sorted(hidden),
            "calculation": (
                f"CTL = {CTL_DAYS}-day and ATL = {ATL_DAYS}-day exponential averages of daily TSS, from 0 on "
                f"{warm.isoformat()} ({WARMUP_DAYS} days before the period); TSB = the previous day's CTL - ATL. "
                "Days by the athlete's local date; a session imported from more than one source counts once."
            ),
            "version": VERSION,
        },
        "summary": {
            "activities": len(activities),
            "counted": len(counted),
            "duplicates": sum(1 for x in activities if x["status"] == "duplicate"),
            "hidden_source": sum(1 for x in activities if x["status"] == "hidden source"),
            "tss": round(total),
            "by_method": sorted(by_method.values(), key=lambda m: -m["tss"]),
        },
        "warnings": warnings,
        "days": days_out,
        "activities": activities,
    }


def _warnings(athlete: User, activities: list[dict], by_method: dict, total: float) -> list[str]:
    out = []
    if not athlete.ftp_watts:
        out.append("No FTP in Profile: rides with power can't be scored by power, so estimates are used.")
    if not athlete.lthr_bpm:
        out.append("No LTHR (threshold heart rate) in Profile: sessions without power can't be scored by heart rate.")
    estimated = sum(m["tss"] for k, m in by_method.items() if k in ESTIMATES)
    if total and estimated / total >= 0.1:
        parts = ", ".join(f"{by_method[k]['label']} {by_method[k]['share']}%" for k in ESTIMATES if k in by_method)
        out.append(
            f"{round(100 * estimated / total)}% of the TSS is estimated ({parts}). Other platforms often score "
            "these sessions lower or not at all."
        )
    if athlete.ftp_watts:
        out.append(
            f"Power TSS uses FTP {athlete.ftp_watts} W for every ride, also older ones (it's recalculated when FTP "
            "changes); TrainingPeaks keeps each workout's TSS from the FTP it had then. A lower FTP here raises "
            "TSS by the square: 10% lower FTP is about 23% more TSS."
        )
    dup = [x for x in activities if x["status"] == "duplicate"]
    if dup:
        out.append(f"{len(dup)} copies of sessions imported from more than one source were counted once (not added).")
    shifted = [x for x in activities if x["utc_date_differs"] and x["status"] == "counted"]
    if shifted:
        out.append(f"{len(shifted)} sessions start near midnight: they count on their local date.")
    return out


def csv_text(rows: list[dict]) -> str:
    out = io.StringIO()
    if rows:
        w = csv.DictWriter(out, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return out.getvalue()


DATE_COLUMNS = ("workoutday", "date", "day", "workout day")
TSS_COLUMNS = ("tss", "trainingstressscore", "training stress score", "load", "training load")
CTL_COLUMNS = ("ctl", "fitness")
ATL_COLUMNS = ("atl", "fatigue")


def parse_other(text: str) -> dict[str, dict]:
    """A day-by-day (or workout-by-workout) CSV from another platform: {date: {tss, ctl?, atl?}}.

    Finds the date column (WorkoutDay, Date, Day) and a TSS column (TSS, TrainingStressScore, Load);
    workouts on one day are added up. CTL / ATL (Fitness / Fatigue) are used when there."""
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    cols = {(c or "").strip().lower(): c for c in reader.fieldnames or []}

    def pick(names):
        return next((cols[n] for n in names if n in cols), None)

    dcol, tcol, ccol, acol = pick(DATE_COLUMNS), pick(TSS_COLUMNS), pick(CTL_COLUMNS), pick(ATL_COLUMNS)
    if not dcol or not (tcol or ccol):
        raise ValueError("The CSV needs a date column (WorkoutDay or Date) and a TSS (or CTL) column")
    out: dict[str, dict] = {}
    for row in reader:
        day = _date(row.get(dcol, ""))
        if day is None:
            continue
        d = out.setdefault(day, {"tss": 0.0})
        if tcol:
            d["tss"] += _num(row.get(tcol)) or 0
        for key, col in (("ctl", ccol), ("atl", acol)):
            if col and _num(row.get(col)) is not None:
                d[key] = _num(row.get(col))
    return out


def _num(v) -> float | None:
    try:
        return float(str(v).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None


def _date(v: str) -> str | None:
    v = (v or "").strip()[:10]
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(v, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def compare(audit_days: list[dict], other: dict[str, dict]) -> dict:
    """Day by day: CoachQuest's TSS (and CTL/ATL) against the other platform's, and where they part."""
    rows, first = [], None
    lo, hi = (min(other), max(other)) if other else ("", "")
    for d in audit_days:
        if not lo <= d["date"] <= hi:
            continue
        # A day without a workout in the other export is a zero there (a walk CoachQuest counts, say).
        o = other.get(d["date"], {"tss": 0.0})
        row = {"date": d["date"], "cq_tss": d["tss"], "other_tss": round(o.get("tss", 0), 1)}
        row["tss_diff"] = round(row["cq_tss"] - row["other_tss"], 1)
        for key in ("ctl", "atl"):
            if key in o:
                row[f"cq_{key}"], row[f"other_{key}"] = d[key], round(o[key], 1)
        rows.append(row)
        if first is None and abs(row["tss_diff"]) > max(5, 0.1 * max(row["cq_tss"], row["other_tss"])):
            first = d["date"]
    cq = sum(r["cq_tss"] for r in rows)
    ot = sum(r["other_tss"] for r in rows)
    return {
        "days_compared": len(rows),
        "first_difference": first,
        "cq_tss": round(cq),
        "other_tss": round(ot),
        "ratio": round(cq / ot, 2) if ot else None,
        "days": rows,
    }
