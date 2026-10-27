"""Pure training-load math. No database access, so it is easy to test.

TSS per activity, then the classic Banister/PMC model:
  CTL (fitness) = 42-day exponentially weighted average of daily TSS
  ATL (fatigue) = 7-day exponentially weighted average of daily TSS
  TSB (form)    = yesterday's CTL - yesterday's ATL
"""

from bisect import bisect_left, insort
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import islice

from .activity_types import RIDES, category

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


SOURCE_RANK = {"strava": 0, "garmin": 1, "intervals_icu": 2}
SAME_SESSION_S = 600  # copies starting this close together are one session
SAME_SESSION_OVERLAP = 0.5  # or when they overlap this share of the shorter one
LONGEST_S = 86400  # no session runs longer than this (bounds the search below)


def _kind(a) -> str:
    """Rides (road, virtual, MTB, ...) are one kind, so a ride saved as Road on one source and Virtual on another
    still matches; everything else by its category (a walk and a strength session at the same time are two)."""
    if not hasattr(a, "sport"):
        return "?"
    c = category(a)
    return "ride" if c in RIDES else c


def same_session(a, b) -> bool:
    """Two records of one session: same kind, and starting within SAME_SESSION_S of each other or overlapping
    for at least half of the shorter one. One person can't do two rides at the same time."""
    if _kind(a) != _kind(b):
        return False
    if abs((a.start_time - b.start_time).total_seconds()) <= SAME_SESSION_S:
        return True
    a_s, b_s = a.duration_s or 0, b.duration_s or 0
    shorter = min(a_s, b_s)
    if shorter <= 0:
        return False
    start = max(a.start_time, b.start_time)
    end = min(a.start_time + timedelta(seconds=a_s), b.start_time + timedelta(seconds=b_s))
    return (end - start).total_seconds() >= SAME_SESSION_OVERLAP * shorter


def _keep_first(a) -> tuple:
    """Which copy to show: Strava first, then Garmin, then Intervals.icu; within one source the copy with power,
    then elevation, then the longer one."""
    has_power = getattr(a, "avg_power", None) is not None or getattr(a, "norm_power", None) is not None
    return (SOURCE_RANK.get(a.source, 9), not has_power, not getattr(a, "elevation_m", 0), -(a.duration_s or 0))


def dedupe(activities: list) -> list:
    """Show a session once when it was recorded or imported more than once (see same_session).

    That covers one ride from Strava and Garmin, and also two copies from the same source, e.g. Zwift and a
    Garmin head unit both uploading the same ride to Strava. Keeps the input order.
    """
    kept: list = []  # sorted by start time
    for a in sorted(activities, key=_keep_first):
        i = bisect_left(kept, a.start_time - timedelta(seconds=LONGEST_S), key=lambda k: k.start_time)
        end = a.start_time + timedelta(seconds=max(a.duration_s or 0, SAME_SESSION_S))
        duplicate = False
        for k in islice(kept, i, None):
            if k.start_time > end:
                break
            if same_session(a, k):
                duplicate = True
                break
        if not duplicate:
            insort(kept, a, key=lambda k: k.start_time)
    keep = {id(a) for a in kept}
    return [a for a in activities if id(a) in keep]


def week_start_of(d: date, week_start: int = 0) -> date:
    """First day of the week containing `d`. week_start: 0 = Monday ... 6 = Sunday."""
    return d - timedelta(days=(d.weekday() - week_start) % 7)


def weekly_volume(activities: list, weeks: int, today: date, week_start: int = 0) -> list[dict]:
    """Hours, distance and TSS per week (starting on the athlete's chosen day), oldest first."""
    this_week = week_start_of(today, week_start)
    starts = [this_week - timedelta(weeks=i) for i in range(weeks - 1, -1, -1)]
    buckets = {s: {"week_start": s.isoformat(), "hours": 0.0, "km": 0.0, "tss": 0.0, "sessions": 0} for s in starts}
    for a in activities:
        d = a.start_time.date()
        wk = week_start_of(d, week_start)
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
