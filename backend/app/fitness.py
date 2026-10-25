"""Pure training-load math. No database access, so it is easy to test.

TSS per activity, then the classic Banister/PMC model:
  CTL (fitness) = 42-day exponentially weighted average of daily TSS
  ATL (fatigue) = 7-day exponentially weighted average of daily TSS
  TSB (form)    = yesterday's CTL - yesterday's ATL
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

CTL_DAYS = 42
ATL_DAYS = 7


def estimate_tss(
    duration_s: int,
    norm_power: float | None = None,
    avg_power: float | None = None,
    avg_hr: float | None = None,
    relative_effort: float | None = None,
    ftp: int | None = None,
    lthr: int | None = None,
) -> tuple[float, str]:
    """Return (tss, method). Prefers power, then heart rate, then Strava effort, then duration."""
    hours = max(duration_s, 0) / 3600
    if hours == 0:
        return 0.0, "none"
    power = norm_power or avg_power
    if power and ftp:
        intensity = power / ftp
        return round(hours * intensity * intensity * 100, 1), "power"
    if avg_hr and lthr:
        intensity = avg_hr / lthr
        return round(hours * intensity * intensity * 100, 1), "hr"
    if relative_effort:
        # Strava relative effort runs roughly on the same scale as TSS.
        return round(float(relative_effort), 1), "effort"
    return round(hours * 50, 1), "duration"


@dataclass
class DayLoad:
    day: date
    tss: float
    ctl: float
    atl: float
    tsb: float


def daily_tss(activities: list[tuple[datetime, float]]) -> dict[date, float]:
    totals: dict[date, float] = defaultdict(float)
    for start, tss in activities:
        totals[start.date()] += tss
    return dict(totals)


def pmc(tss_by_day: dict[date, float], start: date, end: date) -> list[DayLoad]:
    """Performance management chart from `start` to `end` inclusive."""
    ctl = atl = 0.0
    out: list[DayLoad] = []
    day = start
    while day <= end:
        tss = tss_by_day.get(day, 0.0)
        tsb = ctl - atl
        ctl += (tss - ctl) / CTL_DAYS
        atl += (tss - atl) / ATL_DAYS
        out.append(DayLoad(day, round(tss, 1), round(ctl, 1), round(atl, 1), round(tsb, 1)))
        day += timedelta(days=1)
    return out


def dedupe(activities: list, window_s: int = 600) -> list:
    """Drop Garmin copies of activities that also came from Strava.

    Two activities are the same session when they start within `window_s` of
    each other. Strava wins because it is the primary activity source.
    """
    strava_starts = sorted(a.start_time for a in activities if a.source == "strava")
    kept = []
    for a in activities:
        if a.source != "strava" and any(abs((a.start_time - s).total_seconds()) <= window_s for s in strava_starts):
            continue
        kept.append(a)
    return kept


def weekly_volume(activities: list, weeks: int, today: date) -> list[dict]:
    """Hours, distance and TSS per ISO week (Monday start), oldest first."""
    monday = today - timedelta(days=today.weekday())
    starts = [monday - timedelta(weeks=i) for i in range(weeks - 1, -1, -1)]
    buckets = {s: {"week_start": s.isoformat(), "hours": 0.0, "km": 0.0, "tss": 0.0, "sessions": 0} for s in starts}
    for a in activities:
        d = a.start_time.date()
        wk = d - timedelta(days=d.weekday())
        if wk in buckets:
            b = buckets[wk]
            b["hours"] += a.duration_s / 3600
            b["km"] += a.distance_m / 1000
            b["tss"] += a.tss
            b["sessions"] += 1
    for b in buckets.values():
        b["hours"] = round(b["hours"], 1)
        b["km"] = round(b["km"], 1)
        b["tss"] = round(b["tss"])
    return [buckets[s] for s in starts]


def avg(values: list) -> float | None:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def readiness_flags(load: list[DayLoad], wellness: list, weekly: list[dict]) -> list[str]:
    """Deterministic warnings handed to the AI coach as facts, not left to the model."""
    flags: list[str] = []
    if load:
        today = load[-1]
        if today.tsb < -30:
            flags.append(f"High fatigue: TSB is {today.tsb} (below -30).")
        elif today.tsb > 15:
            flags.append(f"Very fresh: TSB is {today.tsb}; fitness may be declining.")
        if len(load) >= 8:
            ramp = round(today.ctl - load[-8].ctl, 1)
            if ramp > 7:
                flags.append(f"Fast CTL ramp: +{ramp} in 7 days (above +7 is an injury/illness risk).")
    if len(weekly) >= 2 and weekly[-2]["tss"] and weekly[-1]["tss"] > 1.3 * weekly[-2]["tss"]:
        flags.append("This week's TSS is more than 30% above last week's.")
    if wellness:
        recent = wellness[-7:]
        base = wellness[-30:]
        hrv7, hrv30 = avg([w.hrv_ms for w in recent]), avg([w.hrv_ms for w in base])
        if hrv7 and hrv30 and hrv7 < 0.9 * hrv30:
            flags.append(f"HRV suppressed: 7-day avg {hrv7} ms vs 30-day {hrv30} ms.")
        rhr7, rhr30 = avg([w.resting_hr for w in recent]), avg([w.resting_hr for w in base])
        if rhr7 and rhr30 and rhr7 > rhr30 + 5:
            flags.append(f"Resting HR elevated: 7-day avg {rhr7} vs 30-day {rhr30} bpm.")
        sleep7 = avg([w.sleep_s for w in recent])
        if sleep7 and sleep7 < 6.5 * 3600:
            flags.append(f"Short sleep: 7-day avg {round(sleep7 / 3600, 1)} h.")
    return flags
