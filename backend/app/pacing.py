"""A pacing plan for a race on its route, and the course files for a Garmin Edge (Virtual Partner).

From the race's route (Races → Route: a saved Strava route with its line), the target finish time and the
athlete's weight and FTP, worked out in code:

1. The route every SPACING_M metres, with the height of each point (Open-Meteo's elevation service, the
   same provider as the weather), smoothed so GPS noise doesn't read as climbs.
2. A pacing that spends the effort where it pays: a little more power on the climbs (up to CLIMB_MAX
   times the base), less on descents, a speed cap on fast descents. The speed on each stretch comes from
   the power (gravity, rolling resistance, air: race_estimate's numbers). The base power is found so the
   moving time plus the planned stops makes the target time.
3. Checkpoints every CHECKPOINT_KM with the elapsed time and the time of day from the start time, and each
   climb with its length, gradient, target power and time.
4. A FIT course file with a timestamp on every point: on an Edge the Virtual Partner rides this plan, so
   the athlete sees whether they're ahead or behind it; the checkpoints are course points. And a GPX copy
   (with times) for Garmin Connect and other apps.

Rules of thumb, not a prescription: wind, the bunch and the day decide the rest.
"""

import io
import logging
import math
from datetime import UTC, datetime, timedelta

import httpx

from . import geo
from .race_estimate import BIKES, DEFAULT_WEIGHT, DRIVETRAIN, RHO, G, format_time

log = logging.getLogger("coachquest.pacing")

ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
SPACING_M = 200
MAX_POINTS = 2000  # 400 km at 200 m
CHECKPOINT_KM = 25
CLIMB_MAX = 1.15  # at most 15% over the base power on climbs
DESCENT_MIN = 0.4
MAX_DESCENT_KMH = 60
CLIMB_MIN_GRADE, CLIMB_MIN_M = 0.03, 600  # a climb: at least 600 m at 3% or more
GROUPS = {"alone": 1.0, "team": 0.75, "bunch": 0.65}  # CdA share: in a rotating team, sitting in a bunch
_elevations: dict[str, list[float]] = {}


class PacingError(Exception):
    pass


async def elevations(points: list[geo.Point]) -> list[float]:
    """Height (m) of each point, 100 per request (cached per route)."""
    key = geo.encode(points)
    if key in _elevations:
        return _elevations[key]
    out: list[float] = []
    async with httpx.AsyncClient(timeout=20) as client:
        for i in range(0, len(points), 100):
            chunk = points[i : i + 100]
            params = {
                "latitude": ",".join(f"{p[0]:.5f}" for p in chunk),
                "longitude": ",".join(f"{p[1]:.5f}" for p in chunk),
            }
            try:
                r = await client.get(ELEVATION_URL, params=params)
                r.raise_for_status()
                out += [float(h) for h in r.json()["elevation"]]
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                raise PacingError("The elevation service didn't answer; try again in a minute") from exc
    _elevations[key] = out
    return out


def smooth(values: list[float], window: int = 5) -> list[float]:
    half = window // 2
    return [
        sum(values[max(0, i - half) : i + half + 1]) / len(values[max(0, i - half) : i + half + 1])
        for i in range(len(values))
    ]


def speed_for(power: float, grade: float, mass: float, crr: float, cda: float) -> float:
    """Steady speed (m/s) for a power on a gradient: power at the wheel = resistance x speed."""
    theta = math.atan(grade)
    resist = mass * G * (math.sin(theta) + crr * math.cos(theta))
    wheel = power * DRIVETRAIN
    lo, hi = 0.5, 30.0
    for _ in range(60):
        v = (lo + hi) / 2
        if v * resist + 0.5 * RHO * cda * v**3 > wheel:
            hi = v
        else:
            lo = v
    return min(lo, MAX_DESCENT_KMH / 3.6)


def factor(grade: float) -> float:
    """Power on a gradient against the base: more on climbs, less on descents."""
    if grade >= 0:
        return min(CLIMB_MAX, 1 + 3 * grade)
    return max(DESCENT_MIN, 1 + 8 * grade)


def ride(stretches: list[tuple[float, float]], base: float, mass: float, crr: float, cda: float) -> list[tuple]:
    """(seconds, power) for each (metres, grade) stretch at a base power."""
    out = []
    for metres, grade in stretches:
        power = base * factor(grade)
        out.append((metres / speed_for(power, grade, mass, crr, cda), power))
    return out


def plan(points: list[geo.Point], heights: list[float], race, athlete, group: str, stops_min: int) -> dict:
    """The pacing plan for the target time (race.target_seconds, minus the stops) on these points."""
    bike, crr, cda, _ = BIKES.get(race.discipline or "Road", BIKES["Road"])
    cda *= GROUPS.get(group, 1.0)
    weight = athlete.weight_kg or DEFAULT_WEIGHT
    mass = weight + bike
    heights = smooth(heights)
    dists = [0.0]
    for i in range(1, len(points)):
        dists.append(dists[-1] + geo.distance_m(points[i - 1], points[i]))
    stretches = []
    for i in range(1, len(points)):
        metres = max(dists[i] - dists[i - 1], 1.0)
        stretches.append((metres, max(-0.2, min(0.2, (heights[i] - heights[i - 1]) / metres))))
    moving = race.target_seconds - stops_min * 60
    if moving <= 0:
        raise PacingError("The stops take longer than the target time")
    lo, hi = 20.0, 800.0  # base power: find the one whose moving time is the target
    for _ in range(50):
        mid = (lo + hi) / 2
        total = sum(s for s, _ in ride(stretches, mid, mass, crr, cda))
        if total > moving:
            lo = mid
        else:
            hi = mid
    base = (lo + hi) / 2
    if base > 790:
        raise PacingError("That target time isn't reachable on this route: set a slower target on the Races page")
    done = ride(stretches, base, mass, crr, cda)
    times = [0.0]
    for s, _ in done:
        times.append(times[-1] + s)
    # Average and normalised power over the ride (by time).
    total_t = times[-1]
    avg_power = sum(s * p for s, p in done) / total_t
    norm_power = (sum(s * p**4 for s, p in done) / total_t) ** 0.25
    start = race.start_time or "06:00"
    h, m = (int(x) for x in start.split(":"))
    clock = datetime(2000, 1, 1, h, m)
    # Checkpoints: the stops spread over the ride by time, so the clock times include them.
    stops_s = stops_min * 60
    checkpoints = []
    climbed, next_km = 0.0, CHECKPOINT_KM
    for j in range(1, len(points)):
        climbed += max(0.0, heights[j] - heights[j - 1])
        if dists[j] / 1000 >= next_km or j == len(points) - 1:
            at = times[j] + stops_s * times[j] / total_t
            checkpoints.append(
                {
                    "km": round(dists[j] / 1000, 1),
                    "elapsed": format_time(round(at)) or "0:00",
                    "clock": (clock + timedelta(seconds=at)).strftime("%H:%M"),
                    "climbed_m": round(climbed),
                    "point": j,
                }
            )
            while next_km <= dists[j] / 1000:
                next_km += CHECKPOINT_KM
    climbs = _climbs(dists, heights, done, times)
    out = {
        "race": race.name,
        "distance_km": round(dists[-1] / 1000, 1),
        "climbing_m": round(sum(max(0.0, heights[j] - heights[j - 1]) for j in range(1, len(heights)))),
        "target_time": format_time(race.target_seconds),
        "moving_time": format_time(round(moving)),
        "stops_min": stops_min,
        "start": start,
        "finish": (clock + timedelta(seconds=race.target_seconds)).strftime("%H:%M"),
        "avg_speed_kmh": round(dists[-1] / moving * 3.6, 1),
        "base_power_w": round(base),
        "avg_power_w": round(avg_power),
        "norm_power_w": round(norm_power),
        "w_per_kg": round(avg_power / weight, 2),
        "group": group,
        "weight_kg": weight,
        "checkpoints": checkpoints,
        "climbs": climbs,
        "notes": [
            f"{weight:g} kg rider{'' if athlete.weight_kg else ' (no weight in Profile, so a guess)'} + {bike} kg bike",
            {
                "alone": "riding alone",
                "team": "riding in a team that shares the work (about 25% less drag)",
                "bunch": "sitting in a bunch (about 35% less drag)",
            }[group],
            "no wind: a head wind costs time, a tail wind gives it back",
        ],
    }
    if athlete.ftp_watts:
        intensity = norm_power / athlete.ftp_watts
        out["intensity_factor"] = round(intensity, 2)
        out["ftp_w"] = athlete.ftp_watts
        hours = moving / 3600
        if intensity > 0.85 and hours > 4 or intensity > 0.95 and hours > 2:
            out["warning"] = (
                f"This target asks for {round(intensity * 100)}% of your FTP for {hours:.1f} hours: very hard to "
                "hold. A slower target, or more help from the bunch, is more realistic."
            )
    out["_times"], out["_heights"], out["_dists"] = times, heights, dists
    return out


def _climbs(dists, heights, done, times) -> list[dict]:
    out = []
    i, n = 1, len(heights)
    while i < n:
        if (heights[i] - heights[i - 1]) / max(dists[i] - dists[i - 1], 1) >= CLIMB_MIN_GRADE:
            j = i
            while j + 1 < n and (heights[j + 1] - heights[j]) / max(dists[j + 1] - dists[j], 1) >= 0.01:
                j += 1
            length = dists[j] - dists[i - 1]
            gain = heights[j] - heights[i - 1]
            if length >= CLIMB_MIN_M and gain / length >= CLIMB_MIN_GRADE:
                secs = times[j] - times[i - 1]
                power = sum(done[k][0] * done[k][1] for k in range(i - 1, j)) / max(secs, 1)
                out.append(
                    {
                        "start_km": round(dists[i - 1] / 1000, 1),
                        "length_km": round(length / 1000, 1),
                        "gain_m": round(gain),
                        "grade_pct": round(gain / length * 100, 1),
                        "power_w": round(power),
                        "time": format_time(round(secs)) or "0:00",
                    }
                )
            i = j + 1
        else:
            i += 1
    return out


def course_fit(points: list[geo.Point], p: dict, name: str) -> bytes:
    """A FIT course: every point with the time the plan reaches it (the Edge's Virtual Partner rides it),
    the checkpoints as course points."""
    from fit_tool.fit_file_builder import FitFileBuilder
    from fit_tool.profile.messages.course_message import CourseMessage
    from fit_tool.profile.messages.course_point_message import CoursePointMessage
    from fit_tool.profile.messages.event_message import EventMessage
    from fit_tool.profile.messages.file_id_message import FileIdMessage
    from fit_tool.profile.messages.lap_message import LapMessage
    from fit_tool.profile.messages.record_message import RecordMessage
    from fit_tool.profile.profile_type import CoursePoint, Event, EventType, FileType, Manufacturer, Sport

    times, heights, dists = p["_times"], p["_heights"], p["_dists"]
    start = round(datetime.now(UTC).timestamp() * 1000)
    b = FitFileBuilder(auto_define=True, min_string_size=50)
    m = FileIdMessage()
    m.type = FileType.COURSE
    m.manufacturer = Manufacturer.DEVELOPMENT.value
    m.product = 0
    m.time_created = start
    m.serial_number = 0x12345678
    b.add(m)
    m = CourseMessage()
    m.course_name = name[:15]
    m.sport = Sport.CYCLING
    b.add(m)
    m = EventMessage()
    m.event = Event.TIMER
    m.event_type = EventType.START
    m.timestamp = start
    b.add(m)
    records = []
    for (lat, lng), t, h, d in zip(points, times, heights, dists, strict=True):
        r = RecordMessage()
        r.position_lat = lat
        r.position_long = lng
        r.altitude = h
        r.distance = d
        r.timestamp = start + round(t * 1000)
        records.append(r)
    b.add_all(records)
    for c in p["checkpoints"]:
        r = records[c["point"]]
        m = CoursePointMessage()
        m.timestamp = r.timestamp
        m.position_lat = r.position_lat
        m.position_long = r.position_long
        m.distance = r.distance
        m.type = CoursePoint.GENERIC
        m.course_point_name = f"{round(c['km'])}k {c['clock']}"
        b.add(m)
    end = records[-1].timestamp
    m = EventMessage()
    m.event = Event.TIMER
    m.event_type = EventType.STOP_ALL
    m.timestamp = end
    b.add(m)
    m = LapMessage()
    m.timestamp = end
    m.start_time = start
    m.total_elapsed_time = (end - start) / 1000
    m.total_timer_time = (end - start) / 1000
    m.start_position_lat = records[0].position_lat
    m.start_position_long = records[0].position_long
    m.end_position_lat = records[-1].position_lat
    m.end_position_long = records[-1].position_long
    m.total_distance = records[-1].distance
    b.add(m)
    return b.build().to_bytes()


def course_gpx(points: list[geo.Point], p: dict, name: str) -> str:
    """The same course as GPX, with heights and the planned time at every point, and the checkpoints."""
    from xml.sax.saxutils import escape

    start = datetime(2000, 1, 1, tzinfo=UTC)
    buf = io.StringIO()
    buf.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    buf.write('<gpx version="1.1" creator="CoachQuest" xmlns="http://www.topografix.com/GPX/1/1">\n')
    for c in p["checkpoints"]:
        lat, lng = points[c["point"]]
        buf.write(
            f'  <wpt lat="{lat:.6f}" lon="{lng:.6f}"><name>{escape(f"{round(c['km'])} km {c['clock']}")}</name></wpt>\n'
        )
    buf.write(f"  <trk><name>{escape(name)}</name><trkseg>\n")
    for (lat, lng), t, h in zip(points, p["_times"], p["_heights"], strict=True):
        when = (start + timedelta(seconds=t)).strftime("%Y-%m-%dT%H:%M:%SZ")
        buf.write(f'    <trkpt lat="{lat:.6f}" lon="{lng:.6f}"><ele>{h:.1f}</ele><time>{when}</time></trkpt>\n')
    buf.write("  </trkseg></trk>\n</gpx>\n")
    return buf.getvalue()


def route_points(encoded: str | None) -> list[geo.Point]:
    """The route every SPACING_M metres."""
    line = geo.decode(encoded)
    if len(line) < 2:
        raise PacingError("The race's route has no line on the map: pick a Strava route on the Races page")
    n = min(MAX_POINTS, max(2, int(geo.length_m(line) / SPACING_M) + 1))
    return geo.resample(line, n)


def public(p: dict) -> dict:
    return {
        k: ([{kk: vv for kk, vv in c.items() if kk != "point"} for c in v] if k == "checkpoints" else v)
        for k, v in p.items()
        if not k.startswith("_")
    }
