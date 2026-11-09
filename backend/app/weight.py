"""Weight from occasional weigh-ins: a trend, and a weekly weigh-in reminder.

Weigh-ins swing a kilo or two with water, food and the time of day, and most athletes don't weigh every
day. The trend is an exponentially smoothed average that allows for the gaps: each weigh-in moves it by
1 - DAILY_KEEP ** days since the last one (a weigh-in after a week counts for more than one after a day),
so it follows real changes and ignores the swings.

The reminder: the athlete picks a weigh-in day (ai_settings["weigh_day"], 0 = Monday); that morning's note
says so, the evening preview says so the night before, and when it was missed the next morning's note
asks again.
"""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .db import User, WellnessDay
from .sync_options import hidden_sources

DAILY_KEEP = 0.9  # each day without a weigh-in, the trend keeps 90% of its weight
WARMUP_DAYS = 180  # weigh-ins this far before a period shown, so the trend has settled
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def weigh_ins(db: DbSession, athlete_id: int, since: date) -> list[tuple[date, float]]:
    hidden = hidden_sources(db, athlete_id, "wellness")
    rows = db.execute(
        select(WellnessDay.day, WellnessDay.weight_kg)
        .where(
            WellnessDay.user_id == athlete_id,
            WellnessDay.day >= since,
            WellnessDay.weight_kg.is_not(None),
            WellnessDay.source.not_in(hidden),
        )
        .order_by(WellnessDay.day)
    ).all()
    return [(d, kg) for d, kg in rows]


def trend(points: list[tuple[date, float]]) -> dict[date, float]:
    """The trend on each weigh-in day."""
    out: dict[date, float] = {}
    value, last = None, None
    for day, kg in points:
        if value is None:
            value = kg
        else:
            value += (1 - DAILY_KEEP ** max((day - last).days, 1)) * (kg - value)
        last = day
        out[day] = round(value, 1)
    return out


def trend_at(trends: dict[date, float], day: date) -> float | None:
    """The trend as it stood on `day` (the latest weigh-in on or before it)."""
    before = [d for d in trends if d <= day]
    return trends[max(before)] if before else None


def add_trend(db: DbSession, athlete_id: int, rows: list[dict]) -> None:
    """Put `weight_trend` on the wellness rows: on weigh-in days, and on the first and last day shown (as it
    stood then), so the line spans the period."""
    if not rows:
        return
    first = date.fromisoformat(str(rows[0]["day"]))
    trends = trend(weigh_ins(db, athlete_id, first - timedelta(days=WARMUP_DAYS)))
    if not trends:
        return
    for i, r in enumerate(rows):
        day = date.fromisoformat(str(r["day"]))
        if day in trends:
            r["weight_trend"] = trends[day]
        elif i in (0, len(rows) - 1):
            r["weight_trend"] = trend_at(trends, day)


def summary(db: DbSession, athlete_id: int, today: date) -> dict | None:
    """For the Weight tile: the latest weigh-in, the trend now and its change over 30 days."""
    points = weigh_ins(db, athlete_id, today - timedelta(days=WARMUP_DAYS + 30))
    if not points:
        return None
    trends = trend(points)
    now, before = trend_at(trends, today), trend_at(trends, today - timedelta(days=30))
    last_day, last_kg = points[-1]
    return {
        "latest_kg": last_kg,
        "latest_day": last_day,
        "days_since": (today - last_day).days,
        "trend_kg": now,
        "change_30d": round(now - before, 1) if before is not None else None,
        "weigh_ins_30d": sum(1 for d, _ in points if d > today - timedelta(days=30)),
    }


def weigh_day(user: User) -> int | None:
    v = (user.ai_settings or {}).get("weigh_day")
    return v if isinstance(v, int) and 0 <= v <= 6 else None


def reminder(db: DbSession, user: User, day: date) -> str | None:
    """The weigh-in reminder for `day`'s morning note: on weigh-in day, and the day after when it was missed
    (so at most twice a week)."""
    wd = weigh_day(user)
    if wd is None:
        return None
    points = weigh_ins(db, user.id, day - timedelta(days=1))
    if day.weekday() == wd and not points:
        return "Weigh-in day: step on the scale after the toilet and before breakfast or drinking."
    if (day - timedelta(days=1)).weekday() == wd and not points:
        return "Yesterday's weigh-in was missed: step on the scale this morning, before breakfast."
    return None
