"""Read helpers shared by the data endpoints and the AI coach."""

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from . import localtime, profile_sync
from .activity_types import category, is_outdoor, is_ride
from .db import Activity, User, WellnessDay
from .fitness import daily_tss, dedupe, pmc, week_start_of
from .sync_options import hidden_sources, primary_source


def activities_since(db: DbSession, athlete_id: int, since: datetime) -> list[Activity]:
    rows = db.scalars(
        select(Activity)
        .where(
            Activity.user_id == athlete_id,
            Activity.start_time >= since,
            Activity.source.not_in(hidden_sources(db, athlete_id, "activities")),
        )
        .order_by(Activity.start_time)
    ).all()
    return dedupe(list(rows), primary_source(db, athlete_id))


def wellness_since(db: DbSession, athlete_id: int, since: date) -> list[WellnessDay]:
    hidden = hidden_sources(db, athlete_id, "wellness")
    return list(
        db.scalars(
            select(WellnessDay)
            .where(WellnessDay.user_id == athlete_id, WellnessDay.day >= since, WellnessDay.source.not_in(hidden))
            .order_by(WellnessDay.day)
        ).all()
    )


WARMUP_DAYS = 120  # before 10 Nov 2026 the PMC started from 0 this long before the period (data_export still)


# Daily TSS per athlete, worked out once and kept until their data changes (single API process, see
# Dockerfile): loading and de-duplicating every activity is the slow part of the PMC; the curve itself
# is a quick loop. The key is read from the data, so nothing has to remember to clear it.
_daily: dict[int, tuple[tuple, dict[date, float]]] = {}


def _data_key(db: DbSession, athlete_id: int, tz_name: str | None) -> tuple:
    """Changes whenever anything the daily TSS depends on changes: an activity added, removed, rescored,
    moved or given another sport; a source hidden or made the main one; the time zone."""
    row = db.execute(
        select(
            func.count(Activity.id),
            func.max(Activity.id),
            func.sum(Activity.tss),
            func.sum(Activity.duration_s),
            func.max(Activity.start_time),
            func.min(Activity.start_time),
            func.sum(func.length(Activity.sport)),
            func.sum(func.length(Activity.source)),
        ).where(Activity.user_id == athlete_id)
    ).one()
    hidden = tuple(sorted(hidden_sources(db, athlete_id, "activities")))
    return (*(round(v, 3) if isinstance(v, float) else v for v in row), hidden, primary_source(db, athlete_id), tz_name)


def daily_load(db: DbSession, athlete_id: int) -> dict[date, float]:
    """TSS per local day over the athlete's whole history (de-duplicated, hidden sources left out)."""
    athlete = db.get(User, athlete_id)
    tz_name = athlete.timezone if athlete else None
    key = _data_key(db, athlete_id, tz_name)
    cached = _daily.get(athlete_id)
    if cached is not None and cached[0] == key:
        return cached[1]
    acts = activities_since(db, athlete_id, datetime.min)
    by_day = daily_tss([(a.start_time, a.tss) for a in acts], localtime.zone(tz_name))
    _daily[athlete_id] = (key, by_day)
    return by_day


def history_start(by_day: dict[date, float], period_start: date) -> date:
    """Where the PMC starts: the athlete's first day with training, as TrainingPeaks does (from 0 then), so
    every period shows the same values; the period's first day when there's nothing before it."""
    first = min((d for d, tss in by_day.items() if tss), default=period_start)
    return min(first, period_start)


def load_curve(db: DbSession, athlete_id: int, days: int, today: date | None = None, with_acts: bool = False):
    """PMC for the last `days`, worked out over the athlete's whole history (from their first training
    day, as TrainingPeaks does). Each activity counts on its local date (the athlete's time zone), as in
    the calendar, not its UTC date. The activities of the period with WARMUP_DAYS before it come too when
    `with_acts` (the AI coach's facts use them); otherwise an empty list."""
    today = today or date.today()
    by_day = daily_load(db, athlete_id)
    curve = pmc(by_day, history_start(by_day, today - timedelta(days=days - 1)), today)
    warmup_start = today - timedelta(days=days + WARMUP_DAYS)
    acts = []
    if with_acts:
        # A day early: a session late on the first local day is stored as the day before in UTC.
        acts = activities_since(db, athlete_id, datetime.combine(warmup_start - timedelta(days=1), datetime.min.time()))
    return curve[-days:], acts


def load_by_day(db: DbSession, athlete_id: int, start: date, end: date, today: date) -> dict[str, dict]:
    """Fitness (CTL) and form (TSB) per day from `start` to `end` (up to today), for the plan and the
    calendar's week totals."""
    end = min(end, today)
    if end < start:
        return {}
    curve, _ = load_curve(db, athlete_id, (today - start).days + 1, today)
    return {p.day.isoformat(): {"ctl": round(p.ctl), "tsb": round(p.tsb)} for p in curve if start <= p.day <= end}


def calories(a: Activity) -> float | None:
    """Calories as recorded, else cycling kilojoules (≈ kcal burned, by the ~24% efficiency rule of thumb)."""
    if a.calories:
        return a.calories
    if a.kilojoules and is_ride(a):
        return a.kilojoules
    return None


def volume_summary(acts: list[Activity], days: int, today: date, week_start: int = 0) -> dict:
    """Totals for the last `days`, activity mix, elevation over the same period (per day up to two
    weeks, per week up to a year, per month beyond), and weekly elevation for the last 12 weeks."""
    since = datetime.combine(today - timedelta(days=days - 1), datetime.min.time())
    period = [a for a in acts if a.start_time >= since]
    cals = [c for c in (calories(a) for a in period) if c]
    efforts = [a.relative_effort for a in period if a.relative_effort and is_ride(a)]
    mix: dict[str, dict] = {}
    for a in period:
        m = mix.setdefault(category(a), {"category": category(a), "count": 0, "hours": 0.0, "km": 0.0})
        m["count"] += 1
        m["hours"] += a.duration_s / 3600
        m["km"] += a.distance_m / 1000
    this_week = week_start_of(today, week_start)
    weeks = [this_week - timedelta(weeks=i) for i in range(11, -1, -1)]
    elevation = {w: 0.0 for w in weeks}
    for a in acts:
        d = a.start_time.date()
        week = week_start_of(d, week_start)
        if week in elevation:
            elevation[week] += a.elevation_m
    if days <= 14:
        buckets = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
        bucket_of = lambda d: d  # noqa: E731
    elif days <= 366:
        buckets = [this_week - timedelta(weeks=i) for i in range(-(-days // 7) - 1, -1, -1)]
        bucket_of = lambda d: week_start_of(d, week_start)  # noqa: E731
    else:  # 2-3 years: per month, or the bars get too thin
        first = today - timedelta(days=days - 1)
        buckets, m = [], date(first.year, first.month, 1)
        while m <= today:
            buckets.append(m)
            m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
        bucket_of = lambda d: date(d.year, d.month, 1)  # noqa: E731
    series = {b: 0.0 for b in buckets}
    for a in acts:
        b = bucket_of(a.start_time.date())
        if b in series:
            series[b] += a.elevation_m
    return {
        "days": days,
        "count": len(period),
        "distance_km": round(sum(a.distance_m for a in period) / 1000, 1),
        "elevation_m": round(sum(a.elevation_m for a in period)),
        "outdoor_elevation_m": round(sum(a.elevation_m for a in period if is_outdoor(a))),
        "moving_hours": round(sum(a.duration_s for a in period) / 3600, 1),
        "calories": round(sum(cals)) if cals else None,
        "avg_relative_effort": round(sum(efforts) / len(efforts)) if efforts else None,
        "mix": sorted(
            ({**m, "hours": round(m["hours"], 1), "km": round(m["km"], 1)} for m in mix.values()),
            key=lambda m: -m["count"],
        ),
        "weekly_elevation": [{"week_start": w.isoformat(), "elevation_m": round(elevation[w])} for w in weeks],
        "elevation": {
            "by": "day" if days <= 14 else "week" if days <= 366 else "month",
            "points": [{"start": b.isoformat(), "elevation_m": round(series[b])} for b in buckets],
        },
    }


def profile_out(athlete, scopes: set[str]) -> dict:
    """The athlete's profile numbers that `scopes` allow (an athlete holds every scope on themself)."""
    out = {}
    if "profile" in scopes:
        out.update(
            ftp_watts=athlete.ftp_watts,
            run_ftp_watts=athlete.run_ftp_watts,
            lthr_bpm=athlete.lthr_bpm,
            threshold_history=athlete.threshold_history or [],
            profile_sources={
                k: v for k, v in (athlete.profile_sources or {}).items() if k != "birth_date"
            },  # who set each value
            max_hr_bpm=athlete.max_hr_bpm,
            goal=athlete.goal,
            age=profile_sync.age(athlete.birth_date),  # the age, never the birth date itself
        )
    if "weight" in scopes:
        out["weight_kg"] = athlete.weight_kg
    return out


def activity_out(a: Activity) -> dict:
    return {
        "id": a.id,
        "source": a.source,
        "name": a.name,
        "sport": a.sport,
        "start_time": a.start_time,
        "duration_s": a.duration_s,
        "distance_km": round(a.distance_m / 1000, 2),
        "elevation_m": round(a.elevation_m),
        "avg_hr": a.avg_hr,
        "avg_power": a.avg_power,
        "norm_power": a.norm_power,
        "tss": a.tss,
        "tss_method": a.tss_method,
        "category": category(a),
        "type_override": a.type_override,
        "indoor": a.indoor,
        "is_race": a.is_race or a.race_id is not None,
        "avg_speed_kmh": round(a.avg_speed_ms * 3.6, 1) if a.avg_speed_ms else None,
        "avg_cadence": round(a.avg_cadence) if a.avg_cadence else None,
        "calories": round(calories(a)) if calories(a) else None,
        "relative_effort": a.relative_effort,
        "race_id": a.race_id,
        "note_tag": a.note_tag,
        "strava_note": bool(a.strava_note),  # the plan is in its Strava description (strava_notes.py)
    }


def wellness_out(w: WellnessDay) -> dict:
    return {
        "day": w.day,
        "resting_hr": w.resting_hr,
        "hrv_ms": w.hrv_ms,
        "sleep_h": round(w.sleep_s / 3600, 1) if w.sleep_s else None,
        "sleep_score": w.sleep_score,
        "body_battery_max": w.body_battery_max,
        "stress_avg": w.stress_avg,
        "steps": w.steps,
        "weight_kg": w.weight_kg,
    }
