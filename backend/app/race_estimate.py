"""What a race's target finish time asks for, worked out in code: power and speed for rides, pace for runs.

Plain physics (gravity, rolling resistance, air) with typical bike numbers per discipline: free, and the
same answer every time. race_target.py hands it to the AI coach for the target CTL.
"""

import re

from .db import Race, User

G, RHO, DRIVETRAIN = 9.81, 1.2, 0.97
# Bike disciplines: (bike kg, rolling resistance, CdA m², variability: normalised / average power).
BIKES = {
    "Road": (8, 0.005, 0.32, 1.05),
    "Track": (8, 0.004, 0.28, 1.02),
    "Gravel": (9, 0.008, 0.36, 1.08),
    "Mountain bike": (12, 0.012, 0.45, 1.12),
}
RUNS = ("Run", "Trail run", "Ultra")
DEFAULT_WEIGHT = 75


def parse_time(text: str | None) -> int | None:
    """'4:30' or '4:30:15' (or '45' minutes) -> seconds; '' -> None."""
    if text is None or not str(text).strip():
        return None
    m = re.fullmatch(r"(\d{1,3})(?::([0-5]\d))?(?::([0-5]\d))?", str(text).strip())
    if not m:
        raise ValueError("Use h:mm or h:mm:ss, e.g. 4:30")
    h, mm, ss = m.groups()
    if mm is None:  # a bare number is minutes
        return int(h) * 60
    return int(h) * 3600 + int(mm) * 60 + int(ss or 0)


def format_time(seconds: int | None) -> str | None:
    if not seconds:
        return None
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if s else f"{h}:{m:02d}"


def estimate(race: Race, athlete: User) -> dict | None:
    """What the target time asks for, worked out in code. None when there's nothing to go on."""
    if not race.target_seconds or not race.distance_km:
        return None
    seconds, km, climb = race.target_seconds, race.distance_km, race.elevation_m or 0
    hours = seconds / 3600
    out: dict = {"hours": round(hours, 2), "avg_speed_kmh": round(km / hours, 1)}
    if race.discipline in BIKES:
        bike, crr, cda, vi = BIKES[race.discipline]
        weight = athlete.weight_kg or DEFAULT_WEIGHT
        mass, dist = weight + bike, km * 1000
        speed = dist / seconds
        work = mass * G * climb + crr * mass * G * dist + 0.5 * RHO * cda * speed**2 * dist
        power = work / seconds / DRIVETRAIN
        out.update(
            kind="ride",
            avg_power_w=round(power),
            w_per_kg=round(power / weight, 2),
            norm_power_w=round(power * vi),
            assumptions=[
                f"{weight:g} kg rider{'' if athlete.weight_kg else ' (no weight in Profile, so a guess)'}"
                f" + {bike} kg bike",
                "riding alone: in a bunch on the road it takes roughly 20-30% less",
                "the climbing is spread over the whole ride",
            ],
        )
        if athlete.ftp_watts:
            intensity = power * vi / athlete.ftp_watts
            out.update(intensity_factor=round(intensity, 2), tss=round(hours * intensity**2 * 100))
    elif race.discipline in RUNS:
        flat_km = km + climb / 100  # about 1 km on the flat for every 100 m of climbing
        out.update(
            kind="run",
            flat_km=round(flat_km, 1),
            pace_min_km=round(seconds / 60 / km, 2),
            flat_pace_min_km=round(seconds / 60 / flat_km, 2),
            assumptions=["about 1 km on the flat for every 100 m of climbing"],
        )
    else:
        out["kind"] = "other"
    return out
