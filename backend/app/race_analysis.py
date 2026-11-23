"""After a race, worked out in code: the pacing plan against the race as ridden, and what the wind cost.

- The track: the race ride's Strava streams (distance, time, moving, power, heart rate; one request), kept
  every TRACK_STEP_M metres: the time (elapsed and moving) at that point, and the power and heart rate over
  the step before it. Kept with the ride's Strava detail (Activity.detail["track"]).
- Plan against race: the pacing plan (pacing.py) on the race's route for its target time, with the stops
  the race really had (so the plan ends on the target time, stops included), set beside the track: at each
  checkpoint the planned and the actual elapsed time, and on each climb the target and actual power and
  time.
- Wind: the headwind along each stretch of the line (weather.ride_weather, at the hour it was ridden there,
  lowered to rider height), and the riding physics of the pacing plan on flat ground: the steady power
  that rides the moving time in that wind, and the time the same power would take without it. A rule of
  thumb for comparing years, not a measurement: climbs, drafting and gusts all change it.
"""

import logging
import math

from .db import Activity, Connection
from .pacing import GROUPS, group_of, speed_for
from .race_estimate import BIKES, DEFAULT_WEIGHT, DRIVETRAIN, RHO, G, parse_time

log = logging.getLogger("coachquest.race_analysis")

TRACK_STEP_M = 250
STREAM_KEYS = "time,distance,moving,watts,heartrate"
# Wind is measured 10 m up; a rider is about 1 m up, where (open country, log profile) it is ~60% of it.
RIDER_HEIGHT_WIND = 0.6


# ---- the track ----


def compact_track(streams: dict) -> list[list] | None:
    """[[km, elapsed_s, moving_s, watts, hr], ...] every TRACK_STEP_M from Strava's streams (key_by_type)."""

    def data(key):
        return ((streams or {}).get(key) or {}).get("data") or []

    times, dists = data("time"), data("distance")
    if len(times) < 2 or len(dists) != len(times):
        return None
    moving, watts, hrs = data("moving"), data("watts"), data("heartrate")
    out = [[0.0, 0, 0, None, None]]
    moved = 0.0
    next_m = TRACK_STEP_M
    w_sum = w_n = h_sum = h_n = 0
    for i in range(1, len(times)):
        dt = max(0, times[i] - times[i - 1])
        if not moving or (i < len(moving) and moving[i]):
            moved += dt
        if i < len(watts) and watts[i] is not None:
            w_sum, w_n = w_sum + watts[i] * dt, w_n + dt
        if i < len(hrs) and hrs[i]:
            h_sum, h_n = h_sum + hrs[i] * dt, h_n + dt
        if dists[i] >= next_m or i == len(times) - 1:
            out.append(
                [
                    round(dists[i] / 1000, 3),
                    int(times[i]),
                    int(moved),
                    round(w_sum / w_n) if w_n else None,
                    round(h_sum / h_n) if h_n else None,
                ]
            )
            w_sum = w_n = h_sum = h_n = 0
            while next_m <= dists[i]:
                next_m += TRACK_STEP_M
    return out


async def fill_track(db, athlete_id: int, copy: Activity | None) -> str | None:
    """Fetch the track of a race ride's Strava copy once (kept in its detail). Returns a note on failure."""
    from sqlalchemy import select

    from .db import utcnow
    from .providers import strava

    if copy is None or (copy.detail or {}).get("track") or (copy.detail or {}).get("track_tried"):
        return None
    conn = db.scalar(
        select(Connection).where(
            Connection.user_id == athlete_id, Connection.provider == "strava", Connection.status == "active"
        )
    )
    if conn is None:
        return None
    try:
        streams = await strava._get(
            db, conn, f"/activities/{copy.external_id}/streams", {"keys": STREAM_KEYS, "key_by_type": "true"}
        )
        track = compact_track(streams)
    except Exception as exc:  # rate limit, token, network: try again on a later look
        log.warning("Strava streams for activity %s failed: %r", copy.id, exc)
        return "Strava didn't answer for the race's power and timing; it's tried again later."
    copy.detail = {**(copy.detail or {}), "track": track, "track_tried": utcnow().isoformat()}
    db.commit()
    return None


def at_km(track: list[list], km: float) -> list | None:
    """The track's [km, elapsed, moving, ...] at `km`, interpolating the times; None past its end."""
    if not track or km > track[-1][0] + 0.05:
        return None
    for a, b in zip(track, track[1:], strict=False):
        if b[0] >= km:
            f = 0 if b[0] == a[0] else (km - a[0]) / (b[0] - a[0])
            return [km, a[1] + f * (b[1] - a[1]), a[2] + f * (b[2] - a[2])]
    return [km, track[-1][1], track[-1][2]]


def between(track: list[list], km0: float, km1: float) -> dict:
    """Elapsed time, average power and heart rate from km0 to km1 on the track."""
    a, b = at_km(track, km0), at_km(track, km1)
    if a is None or b is None:
        return {}
    # Each step's power and heart rate weighed by its time; a step counts when it ends inside the stretch.
    steps = [(r, r[1] - p[1]) for p, r in zip(track, track[1:], strict=False) if km0 < r[0] <= km1 + 1e-9]

    def avg(i):
        pairs = [(r[i], dt) for r, dt in steps if r[i] is not None and dt > 0]
        total = sum(dt for _, dt in pairs)
        return round(sum(v * dt for v, dt in pairs) / total) if total else None

    return {"elapsed_s": round(b[1] - a[1]), "watts": avg(3), "hr": avg(4)}


# ---- the plan against the race ----


BASES = ("official", "moving", "elapsed")


def km_at_elapsed(track: list[list], secs: float) -> float | None:
    """Where on the track the ride's clock read `secs` (the first point it got there)."""
    if not track or secs < 0 or secs > track[-1][1]:
        return None
    for a, b in zip(track, track[1:], strict=False):
        if b[1] >= secs:
            f = 0 if b[1] == a[1] else (secs - a[1]) / (b[1] - a[1])
            return round(a[0] + f * (b[0] - a[0]), 1)
    return track[-1][0]


def _plan_at(points: list[tuple[float, float]], km: float) -> float:
    """The plan's time at `km`, between its checkpoints (from 0 at the start)."""
    for (k0, t0), (k1, t1) in zip(points, points[1:], strict=False):
        if k1 >= km:
            return t0 + (0 if k1 == k0 else (km - k0) / (k1 - k0) * (t1 - t0))
    return points[-1][1]


def plan_vs_race(
    plan: dict, track: list[list], basis: str = "elapsed", start: dict | None = None, target_s: int | None = None
) -> dict:
    """The pacing plan's checkpoints and climbs beside the race as ridden (the track), by one of three clocks:

    - elapsed: the ride's own clock from its start, stops included (the plan has the stops made);
    - moving: moving time only (the plan has no stops): stops and a neutral zone don't count;
    - official: the race's clock, from where timing started (`start`: its km and the ride's elapsed and
      moving time there, e.g. after a neutral zone) to the finish; the plan from there is scaled so its
      finish is the target time."""
    marks = [(c["km"], parse_time(c["elapsed"]) or 0) for c in plan.get("checkpoints") or []]
    points = [(0.0, 0.0), *marks]
    scale, p0 = 1.0, 0.0
    if basis == "official" and start and target_s and points[-1][1]:
        p0 = _plan_at(points, start["km"])
        scale = target_s / max(1.0, points[-1][1] - p0)
    checkpoints = []
    for km, planned in marks:
        actual = at_km(track, km)
        if basis == "official" and start:
            if km <= start["km"]:
                continue  # before timing started: the neutral zone
            planned = round((planned - p0) * scale)
            real = actual[1] - start["elapsed"] if actual else None
        else:
            real = (actual[2] if basis == "moving" else actual[1]) if actual else None
        checkpoints.append(
            {
                "km": km,
                "planned_s": planned,
                "actual_s": round(real) if real is not None else None,
                "gap_s": round(real) - planned if real is not None else None,  # positive: behind the plan
            }
        )
    climbs = []
    for c in plan.get("climbs") or []:
        real = between(track, c["start_km"], c["start_km"] + c["length_km"])
        planned = parse_time(c["time"])
        climbs.append(
            {
                "start_km": c["start_km"],
                "length_km": c["length_km"],
                "grade_pct": c["grade_pct"],
                "target_w": c["power_w"],
                "planned_s": planned,
                "actual_w": real.get("watts"),
                "actual_hr": real.get("hr"),
                "actual_s": real.get("elapsed_s"),
                "gap_s": real["elapsed_s"] - planned if real.get("elapsed_s") and planned else None,
                "neutral": bool(basis == "official" and start and c["start_km"] < start["km"]),
            }
        )
    last = next((c for c in reversed(checkpoints) if c["gap_s"] is not None), None)
    # Where the race fell behind the plan: the first checkpoint more than 2 minutes and 3% behind it.
    behind = next(
        (c for c in checkpoints if c["gap_s"] is not None and c["gap_s"] > max(120, 0.03 * c["planned_s"])),
        None,
    )
    return {
        "basis": basis,
        "start_km": start["km"] if basis == "official" and start else None,
        "target_time": plan.get("target_time"),
        "base_power_w": plan.get("base_power_w"),
        "norm_power_w": plan.get("norm_power_w"),
        "stops_min": plan.get("stops_min"),
        "group": plan.get("group"),
        "checkpoints": checkpoints,
        "climbs": climbs,
        "final_gap_s": last["gap_s"] if last else None,
        "behind_from_km": behind["km"] if behind else None,
    }


# ---- the wind ----


def _speed_in_wind(power: float, head_ms: float, mass: float, crr: float, cda: float) -> float:
    """Steady ground speed (m/s) on the flat for a power, against a headwind (negative: tailwind)."""
    wheel = power * DRIVETRAIN
    resist = mass * G * crr
    lo, hi = 0.5, 30.0
    for _ in range(50):
        v = (lo + hi) / 2
        air = v + head_ms
        drag = 0.5 * RHO * cda * air * abs(air) * v
        if v * resist + drag > wheel:
            hi = v
        else:
            lo = v
    return lo


def wind_effect(distance_m: float, moving_s: float, head_kmh: list[float], race, athlete) -> dict | None:
    """What the wind did to a ride: seconds it cost (positive) or gave (negative), and the moving time
    without it, for the steady power that rides `moving_s` in that wind on flat ground."""
    if not head_kmh or not distance_m or not moving_s:
        return None
    if race.discipline not in BIKES and race.discipline is not None:
        return None  # runs and the rest: the wind is a small part of it
    bike, crr, cda, _ = BIKES.get(race.discipline or "Road", BIKES["Road"])
    cda *= GROUPS.get(group_of(race), 1.0)
    mass = (getattr(athlete, "weight_kg", None) or DEFAULT_WEIGHT) + bike
    piece = distance_m / len(head_kmh)
    heads = [h / 3.6 * RIDER_HEIGHT_WIND for h in head_kmh]

    def total(power, wind=True):
        return sum(piece / _speed_in_wind(power, h if wind else 0.0, mass, crr, cda) for h in heads)

    lo, hi = 20.0, 1500.0
    for _ in range(50):
        mid = (lo + hi) / 2
        if total(mid) > moving_s:
            lo = mid
        else:
            hi = mid
    power = (lo + hi) / 2
    calm = total(power, wind=False)
    return {
        "power_w": round(power),
        "calm_moving_s": round(calm),
        "wind_s": round(moving_s - calm),
    }


def flat_speed(power: float, race, athlete) -> float:
    """km/h on the flat without wind for a power (the plan's physics), for notes."""
    bike, crr, cda, _ = BIKES.get(race.discipline or "Road", BIKES["Road"])
    mass = (getattr(athlete, "weight_kg", None) or DEFAULT_WEIGHT) + bike
    return round(speed_for(power, 0.0, mass, crr, cda * GROUPS.get(group_of(race), 1.0)) * 3.6, 1)


def heading_component(speed: float, wind_from: float, heading: float) -> float:
    """The part of a wind (from `wind_from` degrees) blowing against a rider going `heading`: positive is a
    headwind, negative a tailwind."""
    return speed * math.cos(math.radians(wind_from - heading))
