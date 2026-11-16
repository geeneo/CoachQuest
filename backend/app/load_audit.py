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
import math
from datetime import UTC, date, datetime, timedelta
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import localtime
from .activity_types import category
from .db import Activity, User
from .fitness import ATL_DAYS, CTL_DAYS, RUNS, counted_tss, dedupe, pmc, same_session, threshold_at
from .localtime import local_date
from .queries import WARMUP_DAYS, daily_load, history_start
from .sync_options import hidden_sources, primary_source

VERSION = "load-audit 4"
METHODS = {
    "power": "Power and FTP",
    "hr": "Heart rate and LTHR (average; zones once its heart rate stream is fetched)",
    "hr zones": "Heart rate: time in zones and LTHR, as TrainingPeaks' hrTSS",
    "walk hr zones": "Walk or hike: time in heart rate zones, x 0.65",
    "effort": "Strava Relative Effort, used as TSS",
    "duration": "Estimate: 50 TSS an hour",
    "intervals_icu": "Intervals.icu training load",
    "walk hr": "Walk or hike: heart rate and LTHR, x 0.65",
    "no heart rate": "Strength, yoga, walk without heart rate: 0",
    "light": "Walk or hike: light (old scoring)",
    "not scored": "Strength, yoga: not scored (old scoring)",
    "none": "No duration",
}
ESTIMATES = ("effort", "duration")


def _label(method: str) -> str:
    """'hr zones (garmin copy)' -> the method's label, and that the Garmin copy's scoring counts."""
    base, _, rest = method.partition(" (")
    label = METHODS.get(base, base)
    return f"{label}, from the {rest.split()[0].capitalize()} copy (not Intervals.icu's load)" if rest else label


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
    copies: dict = {}
    kept = dedupe(visible, primary, copies)
    kept_ids = {a.id for a in kept}

    def counted_as(a: Activity) -> int | None:
        return next((k.id for k in kept if k.id != a.id and same_session(a, k)), None)

    # The same curve as the Fitness chart: the whole history, from the first training day.
    by_day = daily_load(db, athlete.id)
    first = history_start(by_day, start)
    curve = {p.day: p for p in pmc(by_day, first, today)}

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
        sport = category(a)
        ftp = threshold_at(athlete, "run_ftp_watts" if sport in RUNS else "ftp_watts", a.start_time.date())
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
                "sport": sport,
                "minutes": round((a.duration_s or 0) / 60),
                "tss": round(a.tss or 0, 1),
                "counted_tss": round(counted_tss(a, copies)[0], 1) if status == "counted" else 0,
                "method": counted_tss(a, copies)[1] if status == "counted" else a.tss_method,
                "power_w": round(power) if power else None,
                "ftp_w": ftp,
                "intensity": round(power / ftp, 2) if power and ftp else None,
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
            {"method": x["method"], "label": _label(x["method"]), "activities": 0, "tss": 0.0},
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
            "threshold_history": athlete.threshold_history or [],
            "primary_source": primary,
            "hidden_sources": sorted(hidden),
            "calculation": (
                f"CTL = {CTL_DAYS}-day and ATL = {ATL_DAYS}-day exponential averages of daily TSS over the whole "
                f"history, from 0 on the first training day ({first.isoformat()}), as TrainingPeaks does; "
                "TSB = the previous day's CTL - ATL. "
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
    if athlete.ftp_watts and not any(h.get("field") == "ftp_watts" for h in athlete.threshold_history or []):
        out.append(
            f"No FTP history: every ride is scored with today's FTP {athlete.ftp_watts} W. TrainingPeaks keeps "
            "each workout's TSS from the FTP it had then; add earlier values in Profile → Threshold history. "
            "A lower FTP raises TSS by the square: 10% lower FTP is about 23% more TSS."
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
# Per workout, when the export has them (TrainingPeaks' Workout Summary does): to compare intensity.
IF_COLUMNS = ("if", "intensityfactor", "intensity factor")
HOURS_COLUMNS = ("timetotalinhours", "time total in hours", "hours")
TITLE_COLUMNS = ("title", "name")
TYPE_COLUMNS = ("workouttype", "workout type", "type", "sport")


def parse_other(text: str | io.TextIOBase) -> dict[str, dict]:
    """A day-by-day (or workout-by-workout) CSV from another platform: {date: {tss, ctl?, atl?}}.

    Finds the date column (WorkoutDay, Date, Day) and a TSS column (TSS, TrainingStressScore, Load);
    workouts on one day are added up. CTL / ATL (Fitness / Fatigue) are used when there."""
    # Text, or a text stream (a CSV read straight out of a ZIP, so a big export is never held whole).
    src = io.StringIO(text.lstrip("\ufeff")) if isinstance(text, str) else text
    # Free-text columns (descriptions, comments) can be long, and one stray quote makes a field run on:
    # past the csv module's 128 KB default that was an error page (500). The upload itself is capped.
    csv.field_size_limit(OTHER_FIELD_LIMIT)
    try:
        return _parse_other(csv.DictReader(src))
    except csv.Error as exc:
        raise ValueError(f"Couldn't read that CSV: {exc}") from exc


# Bounded by the upload limits (routers/load_audit.py): 30 MB of CSV.
OTHER_FIELD_LIMIT = 32_000_000


def _parse_other(reader: csv.DictReader) -> dict[str, dict]:
    cols = {(c or "").strip().lower(): c for c in reader.fieldnames or []}

    def pick(names):
        return next((cols[n] for n in names if n in cols), None)

    dcol, tcol, ccol, acol = pick(DATE_COLUMNS), pick(TSS_COLUMNS), pick(CTL_COLUMNS), pick(ATL_COLUMNS)
    icol, hcol, ncol, ycol = pick(IF_COLUMNS), pick(HOURS_COLUMNS), pick(TITLE_COLUMNS), pick(TYPE_COLUMNS)
    if not dcol or not (tcol or ccol):
        raise ValueError("The CSV needs a date column (WorkoutDay or Date) and a TSS (or CTL) column")
    out: dict[str, dict] = {}
    for row in reader:
        day = _date(row.get(dcol, ""))
        if day is None:
            continue
        d = out.setdefault(day, {"tss": 0.0})
        if tcol:
            tss = _num(row.get(tcol)) or 0
            d["tss"] += tss
            workout = _workout(row, tss, icol, hcol, ncol, ycol)
            if workout:
                d.setdefault("workouts", []).append(workout)
        for key, col in (("ctl", ccol), ("atl", acol)):
            if col and _num(row.get(col)) is not None:
                d[key] = _num(row.get(col))
    return out


def _workout(row: dict, tss: float, icol, hcol, ncol, ycol) -> dict | None:
    """One workout of the export with its intensity: the IF column, else worked out from TSS and duration
    (TSS = hours × IF² × 100). None for a workout without TSS (planned only, or no data)."""
    if tss <= 0:
        return None
    hours = _num(row.get(hcol)) if hcol else None
    intensity = _num(row.get(icol)) if icol else None
    if not intensity and hours:
        intensity = math.sqrt(tss / (hours * 100))
    return {
        "title": (row.get(ncol) or "").strip() if ncol else "",
        "type": (row.get(ycol) or "").strip() if ycol else "",
        "tss": round(tss, 1),
        "minutes": round(hours * 60) if hours else None,
        "if": round(intensity, 2) if intensity else None,
    }


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


def _effective_if(x: dict) -> float | None:
    """A CoachQuest session's intensity: power against FTP when scored by power, else the IF its TSS and
    duration imply (TSS = hours × IF² × 100), which is what heart-rate scoring amounts to."""
    if x["method"] == "power" and x.get("intensity"):
        return x["intensity"]
    hours = (x.get("minutes") or 0) / 60
    return round(math.sqrt(x["counted_tss"] / (hours * 100)), 2) if hours and x["counted_tss"] > 0 else None


def sessions(activities: list[dict], other: dict[str, dict], lo: str, hi: str) -> list[dict]:
    """Each of the other platform's workouts beside the CoachQuest session it most likely is: the same day,
    the closest duration (within a quarter, or 15 minutes). Unpaired ones are listed with one side empty."""
    out = []
    by_day: dict[str, list[dict]] = {}
    for x in activities:
        if x["status"] == "counted" and x["counted_tss"] > 0 and lo <= x["date"] <= hi:
            by_day.setdefault(x["date"], []).append(x)
    for day in sorted(set(by_day) | {d for d in other if lo <= d <= hi and other[d].get("workouts")}):
        ours = sorted(by_day.get(day, []), key=lambda x: -x["counted_tss"])
        theirs = sorted(other.get(day, {}).get("workouts", []), key=lambda w: -w["tss"])
        used: set[int] = set()
        timed = [w for w in theirs if w["minutes"] is not None]
        untimed = [w for w in theirs if w["minutes"] is None]
        for w in timed:
            match = None
            for i, x in enumerate(ours):
                gap = abs(x["minutes"] - w["minutes"])
                if i in used or gap > max(15, 0.25 * max(x["minutes"], w["minutes"])):
                    continue
                if match is None or gap < abs(ours[match]["minutes"] - w["minutes"]):
                    match = i
            if match is not None:
                used.add(match)
            out.append(_pair(day, ours[match] if match is not None else None, w))
        # Without a duration there is nothing to go by: only one left on each side is taken as the same.
        left = [i for i in range(len(ours)) if i not in used]
        if len(untimed) == 1 and len(left) == 1:
            used.add(left[0])
            out.append(_pair(day, ours[left[0]], untimed[0]))
        else:
            out.extend(_pair(day, None, w) for w in untimed)
        out.extend(_pair(day, x, None) for i, x in enumerate(ours) if i not in used)
    return out


def _pair(day: str, x: dict | None, w: dict | None) -> dict:
    row = {"date": day}
    if x:
        row.update(
            cq_name=x["name"],
            cq_sport=x["sport"],
            cq_method=x["method"],
            cq_minutes=x["minutes"],
            cq_tss=x["counted_tss"],
            cq_if=_effective_if(x),
            cq_power=x["power_w"] if x["method"] == "power" else None,
            cq_ftp=x["ftp_w"] if x["method"] == "power" else None,
        )
    if w:
        row.update(
            other_title=w["title"] or w["type"],
            other_minutes=w["minutes"],
            other_tss=w["tss"],
            other_if=w["if"],
        )
    # The FTP the other platform's IF implies for the same (normalized) power.
    if x and w and row.get("cq_power") and w["if"]:
        row["other_ftp"] = round(row["cq_power"] / w["if"])
    return row


def intensity_summary(pairs: list[dict]) -> dict | None:
    """Where the TSS difference comes from, over the sessions on both sides: intensity (IF, squared in TSS)
    or duration; and for rides scored by power, the FTP each platform used (median)."""
    both = [p for p in pairs if p.get("cq_if") and p.get("other_if")]
    if not both:
        return None
    timed = [p for p in both if p.get("cq_minutes") and p.get("other_minutes")]
    power = [p for p in both if p.get("other_ftp") and p.get("cq_ftp")]
    if_ratio = median(p["cq_if"] / p["other_if"] for p in both)
    return {
        "sessions": len(both),
        "if_ratio": round(if_ratio, 2),
        # TSS goes with IF squared: this much of the TSS ratio comes from intensity alone.
        "tss_ratio_from_if": round(if_ratio**2, 2),
        "duration_ratio": round(median(p["cq_minutes"] / p["other_minutes"] for p in timed), 2) if timed else None,
        "power_sessions": len(power),
        "cq_ftp": round(median(p["cq_ftp"] for p in power)) if power else None,
        "other_ftp": round(median(p["other_ftp"] for p in power)) if power else None,
        "unpaired_other": sum(1 for p in pairs if "other_tss" in p and "cq_tss" not in p),
        "unpaired_cq": sum(1 for p in pairs if "cq_tss" in p and "other_tss" not in p),
    }


def compare(audit_days: list[dict], other: dict[str, dict], activities: list[dict] | None = None) -> dict:
    """Day by day: CoachQuest's TSS (and CTL/ATL) against the other platform's, and where they part. With
    the audit's activities, also session by session: intensity (IF) and duration on each side."""
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
    pairs = sessions(activities, other, lo, hi) if activities is not None and rows else []
    return {
        "days_compared": len(rows),
        "first_difference": first,
        "cq_tss": round(cq),
        "other_tss": round(ot),
        "ratio": round(cq / ot, 2) if ot else None,
        "days": rows,
        "sessions": pairs,
        "intensity": intensity_summary(pairs),
    }
