"""Pure training-load math. No database access, so it is easy to test.

TSS per activity, then the classic Banister/PMC model:
  CTL (fitness) = 42-day exponentially weighted average of daily TSS
  ATL (fatigue) = 7-day exponentially weighted average of daily TSS
  TSB (form)    = yesterday's CTL - yesterday's ATL
"""

from bisect import bisect_left, insort
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
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


RUNS = {"Run", "Trail run", "Treadmill run"}
LIGHT = {"Walk", "Hike"}  # scored light, as TrainingPeaks does
NOT_SCORED = {"Strength", "Workout", "Yoga", "Climbing"}  # no training stress, as on TrainingPeaks
LIGHT_MAX_PER_H = 15
LIGHT_PER_H = 10
TSS_VERSION = 2  # 2: sport-aware (runs by run threshold power, walks light, strength 0)


def score(a, user) -> tuple[float, str]:
    """An activity's TSS by its sport, the way TrainingPeaks counts it:

    - rides: power against FTP, else heart rate against LTHR, else Strava's Relative Effort, else duration;
    - runs: power against the *run* threshold power (running power isn't comparable to cycling FTP),
      else heart rate, else Relative Effort, else duration;
    - walks and hikes: light, from heart rate but at most LIGHT_MAX_PER_H an hour (LIGHT_PER_H without);
    - strength, yoga, other workouts and climbing: 0;
    - everything else (swimming, rowing, skiing...): heart rate, else Relative Effort, else duration."""
    c = category(a)
    duration = a.duration_s or 0
    if c in NOT_SCORED:
        return 0.0, "not scored"
    if c in LIGHT:
        hours = duration / 3600
        if a.avg_hr and user.lthr_bpm:
            tss, _ = estimate_tss(duration, None, None, a.avg_hr, None, None, user.lthr_bpm)
            return round(min(tss, LIGHT_MAX_PER_H * hours), 1), "light"
        return round(LIGHT_PER_H * hours, 1), "light"
    if c in RIDES:
        ftp = user.ftp_watts
    elif c in RUNS:
        ftp = getattr(user, "run_ftp_watts", None)
    else:
        ftp = None  # power on other sports isn't on the cycling scale
    return estimate_tss(
        duration,
        a.norm_power if ftp else None,
        a.avg_power if ftp else None,
        a.avg_hr,
        a.relative_effort,
        ftp,
        user.lthr_bpm,
    )


def rescore(a, user) -> None:
    """Score an activity again (thresholds changed, or the scoring did). An Intervals.icu training load
    stays for rides and runs, as it came from the provider."""
    if a.tss_method == "intervals_icu" and category(a) not in NOT_SCORED | LIGHT:
        return
    a.tss, a.tss_method = score(a, user)


@dataclass
class DayLoad:
    day: date
    tss: float
    ctl: float
    atl: float
    tsb: float


def daily_tss(activities: list[tuple[datetime, float]], tz=None) -> dict[date, float]:
    """TSS per day; with `tz` (the athlete's time zone) by local date, as start times are stored in UTC."""
    totals: dict[date, float] = defaultdict(float)
    for start, tss in activities:
        day = start.replace(tzinfo=UTC).astimezone(tz).date() if tz else start.date()
        totals[day] += tss or 0
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


def _keep_first(primary: str | None):
    """Which copy to show: the athlete's main activity source, then Strava, Garmin, Intervals.icu; within one
    source the copy with power, then elevation, then the longer one."""

    def key(a) -> tuple:
        rank = -1 if a.source == primary else SOURCE_RANK.get(a.source, 9)
        has_power = getattr(a, "avg_power", None) is not None or getattr(a, "norm_power", None) is not None
        return (rank, not has_power, not getattr(a, "elevation_m", 0), -(a.duration_s or 0))

    return key


def dedupe(activities: list, primary: str | None = None) -> list:
    """Show a session once when it was recorded or imported more than once (see same_session).

    That covers one ride from Strava and Garmin, and also two copies from the same source, e.g. Zwift and a
    Garmin head unit both uploading the same ride to Strava. `primary` is the athlete's main activity source
    (sync_options.primary_source), whose copy wins. Keeps the input order.
    """
    kept: list = []  # sorted by start time
    for a in sorted(activities, key=_keep_first(primary)):
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
