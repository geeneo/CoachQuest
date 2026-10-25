"""Read helpers shared by the data endpoints and the AI coach."""

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .db import Activity, WellnessDay
from .fitness import daily_tss, dedupe, pmc


def activities_since(db: DbSession, athlete_id: int, since: datetime) -> list[Activity]:
    rows = db.scalars(
        select(Activity)
        .where(Activity.user_id == athlete_id, Activity.start_time >= since)
        .order_by(Activity.start_time)
    ).all()
    return dedupe(list(rows))


def wellness_since(db: DbSession, athlete_id: int, since: date) -> list[WellnessDay]:
    return list(
        db.scalars(
            select(WellnessDay)
            .where(WellnessDay.user_id == athlete_id, WellnessDay.day >= since)
            .order_by(WellnessDay.day)
        ).all()
    )


def load_curve(db: DbSession, athlete_id: int, days: int, today: date | None = None):
    """PMC for the last `days`, warmed up over 120 extra days so CTL is meaningful."""
    today = today or date.today()
    warmup_start = today - timedelta(days=days + 120)
    acts = activities_since(db, athlete_id, datetime.combine(warmup_start, datetime.min.time()))
    curve = pmc(daily_tss([(a.start_time, a.tss) for a in acts]), warmup_start, today)
    return curve[-days:], acts


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
    }
