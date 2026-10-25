"""Structured workouts: CoachQuest's own format, independent of Zwift or MyWhoosh.

A workout is a list of steps. Power is a fraction of FTP (0.75 = 75% FTP), so
the same workout fits any athlete; watts are worked out from their FTP only
for display. Exports (ZWO today, platform APIs later) are made from this model
and never stored instead of it.

    {"kind": "warmup",    "duration_s": 600, "power_start": 0.5, "power_end": 0.75}
    {"kind": "steady",    "duration_s": 1200, "power": 0.9, "cadence": 90}
    {"kind": "recovery",  "duration_s": 300, "power": 0.5}
    {"kind": "intervals", "repeat": 5, "on_s": 60, "on_power": 1.2, "off_s": 60, "off_power": 0.5}
    {"kind": "ramp",      "duration_s": 300, "power_start": 0.6, "power_end": 1.0}
    {"kind": "cooldown",  "duration_s": 600, "power_start": 0.7, "power_end": 0.45}
    {"kind": "free",      "duration_s": 600}  # free ride, no power target

Every step can have `text`, a short on-screen cue.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter

Power = Annotated[float, Field(ge=0.2, le=3.0)]
Seconds = Annotated[int, Field(ge=5, le=6 * 3600)]
Cadence = Annotated[int, Field(ge=30, le=150)]
Text = Annotated[str, Field(max_length=200)]
MAX_SECONDS = 8 * 3600


class _Step(BaseModel):
    model_config = {"extra": "forbid"}
    text: Text | None = None


class RampStep(_Step):
    kind: Literal["warmup", "cooldown", "ramp"]
    duration_s: Seconds
    power_start: Power
    power_end: Power
    cadence: Cadence | None = None


class SteadyStep(_Step):
    kind: Literal["steady", "recovery"]
    duration_s: Seconds
    power: Power
    cadence: Cadence | None = None


class IntervalsStep(_Step):
    kind: Literal["intervals"]
    repeat: Annotated[int, Field(ge=1, le=50)]
    on_s: Seconds
    on_power: Power
    off_s: Seconds
    off_power: Power
    cadence: Cadence | None = None
    off_cadence: Cadence | None = None


class FreeStep(_Step):
    kind: Literal["free"]
    duration_s: Seconds


Step = Annotated[RampStep | SteadyStep | IntervalsStep | FreeStep, Field(discriminator="kind")]
Steps = Annotated[list[Step], Field(min_length=1, max_length=100)]
_steps = TypeAdapter(Steps)


def validate_steps(raw: list) -> list[dict]:
    """Check steps and return them as plain dicts (for JSON storage). Raises ValueError."""
    steps = [s.model_dump(exclude_none=True) for s in _steps.validate_python(raw)]
    if duration(steps) > MAX_SECONDS:
        raise ValueError("A workout can be at most 8 hours long")
    return steps


def step_seconds(step: dict) -> int:
    if step["kind"] == "intervals":
        return step["repeat"] * (step["on_s"] + step["off_s"])
    return step["duration_s"]


def duration(steps: list[dict]) -> int:
    return sum(step_seconds(s) for s in steps)


def blocks(steps: list[dict]) -> list[dict]:
    """Steps laid out on a timeline, intervals expanded, for charts and estimates.

    Each block: start_s, duration_s, power_start, power_end (None for free ride),
    cadence, kind, step (index of the step it came from)."""
    out, t = [], 0

    def add(i, kind, secs, p0, p1, cadence):
        nonlocal t
        out.append(
            {
                "step": i,
                "kind": kind,
                "start_s": t,
                "duration_s": secs,
                "power_start": p0,
                "power_end": p1,
                "cadence": cadence,
            }
        )
        t += secs

    for i, s in enumerate(steps):
        k = s["kind"]
        if k == "intervals":
            for _ in range(s["repeat"]):
                add(i, "on", s["on_s"], s["on_power"], s["on_power"], s.get("cadence"))
                add(i, "off", s["off_s"], s["off_power"], s["off_power"], s.get("off_cadence"))
        elif k in ("steady", "recovery"):
            add(i, k, s["duration_s"], s["power"], s["power"], s.get("cadence"))
        elif k == "free":
            add(i, k, s["duration_s"], None, None, None)
        else:
            add(i, k, s["duration_s"], s["power_start"], s["power_end"], s.get("cadence"))
    return out


def _per_second(bl: list[dict]) -> list[float]:
    """Target power each second (fraction of FTP), free-ride time left out."""
    out = []
    for b in bl:
        if b["power_start"] is None:
            continue
        n, p0, p1 = b["duration_s"], b["power_start"], b["power_end"]
        out.extend(p0 + (p1 - p0) * (j + 0.5) / n for j in range(n))
    return out


def estimate(steps: list[dict], ftp: int | None = None) -> dict:
    """Duration, intensity factor and TSS of riding the workout exactly as written.

    IF is the normalised power of the target profile (30 s rolling average,
    fourth-power mean) as a fraction of FTP; TSS = hours x IF² x 100. Free-ride
    time has no target, so it is left out of IF and TSS and reported apart."""
    bl = blocks(steps)
    total = sum(b["duration_s"] for b in bl)
    power = _per_second(bl)
    free = total - len(power)
    if not power:
        return {"duration_s": total, "free_ride_s": free, "intensity_factor": None, "tss": None, "avg_power": None}
    window = min(30, len(power))
    rolling, acc = [], 0.0
    for i, p in enumerate(power):
        acc += p
        if i >= window:
            acc -= power[i - window]
        if i >= window - 1:
            rolling.append(acc / window)
    np_fraction = (sum(r**4 for r in rolling) / len(rolling)) ** 0.25
    avg = sum(power) / len(power)
    out = {
        "duration_s": total,
        "free_ride_s": free,
        "intensity_factor": round(np_fraction, 2),
        "tss": round(len(power) / 3600 * np_fraction**2 * 100),
        "avg_power": round(avg, 3),
    }
    if ftp:
        out.update(avg_watts=to_watts(avg, ftp), np_watts=to_watts(np_fraction, ftp))
    return out


def to_watts(fraction: float, ftp: int) -> int:
    """75% of a 260 W FTP -> 195 W."""
    return round(fraction * ftp)


def to_fraction(watts: float, ftp: int) -> float:
    """195 W at a 260 W FTP -> 0.75."""
    if not ftp:
        raise ValueError("FTP is needed to convert watts")
    return round(watts / ftp, 3)


# Power zones (fraction of FTP, upper bound) as used by Zwift and most trainers.
ZONES = [(0.60, "Z1"), (0.76, "Z2"), (0.90, "Z3"), (1.05, "Z4"), (1.19, "Z5")]


def zone(fraction: float) -> str:
    for upper, name in ZONES:
        if fraction < upper:
            return name
    return "Z6"
