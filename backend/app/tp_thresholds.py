"""The thresholds TrainingPeaks used, worked out from its Workout Summary export (Settings → Export Data).

The export has no zones, but every workout's IF (intensity factor) and TSS come from them:

- power: IF = normalized power ÷ threshold power, so threshold ≈ average power ÷ IF. Average power is at
  most the normalized power, so steady sessions give the truest value: the 80th percentile is taken
  (bike workouts for FTP, runs for the run threshold power);
- threshold heart rate: TSS = hours × (HR ÷ LTHR)² × 100 for sessions scored by heart rate (no power;
  walks are left out, TrainingPeaks scores them by pace), so LTHR = HR ÷ √(TSS ÷ (100 × hours)); median;
- max HR: the highest workout max that another one comes close to (a single spike is a sensor glitch).

Only the most recent sessions count (thresholds change), and a value needs a few sessions behind it.
"""

import csv
import io
import math
import statistics
from datetime import date

RIDES = {"bike", "mtb", "cycling", "road bike", "mountain bike"}
RUNS = {"run", "running"}
RECENT = 30  # sessions per value, the latest
MIN_SESSIONS = 3


def _num(v) -> float | None:
    try:
        x = float(str(v).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _pct(values: list[float], p: float) -> float:
    v = sorted(values)
    return v[min(len(v) - 1, int(round(p * (len(v) - 1))))]


def _rows(text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    cols = {(c or "").strip().lower(): c for c in reader.fieldnames or []}
    need = ("workoutday", "workouttype", "if", "tss", "timetotalinhours")
    if not all(n in cols for n in need):
        raise ValueError(
            "This isn't a TrainingPeaks Workout Summary export (it needs WorkoutDay, WorkoutType, IF, TSS and "
            "TimeTotalInHours columns)"
        )
    out = []
    for r in reader:
        get = lambda n, r=r: r.get(cols.get(n, ""), "")  # noqa: E731
        day = (get("workoutday") or "").strip()[:10]
        try:
            date.fromisoformat(day)
        except ValueError:
            continue
        out.append(
            {
                "day": day,
                "type": (get("workouttype") or "").strip().lower(),
                "hours": _num(get("timetotalinhours")),
                "power": _num(get("poweraverage")),
                "hr": _num(get("heartrateaverage")),
                "hr_max": _num(get("heartratemax")),
                "if": _num(get("if")),
                "tss": _num(get("tss")),
            }
        )
    return sorted(out, key=lambda x: x["day"])


def _value(samples: list[tuple[str, float]], how: str, pick) -> dict | None:
    samples = samples[-RECENT:]
    if len(samples) < MIN_SESSIONS:
        return None
    return {
        "value": round(pick([v for _, v in samples])),
        "sessions": len(samples),
        "from": samples[0][0],
        "to": samples[-1][0],
        "how": how,
    }


def estimate(text: str) -> dict:
    rows = _rows(text)
    power = {"ftp_watts": [], "run_ftp_watts": []}
    lthr = []
    for r in rows:
        if r["power"] and r["if"] and r["if"] > 0.3:
            key = "ftp_watts" if r["type"] in RIDES else "run_ftp_watts" if r["type"] in RUNS else None
            if key:
                power[key].append((r["day"], r["power"] / r["if"]))
        elif r["hr"] and r["tss"] and r["hours"] and r["hours"] >= 0.3 and r["type"] not in {"walk", "hike"}:
            lthr.append((r["day"], r["hr"] / math.sqrt(r["tss"] / (100 * r["hours"]))))
    out = {
        "ftp_watts": _value(
            power["ftp_watts"], "bike workouts: average power ÷ IF (steady ones)", lambda v: _pct(v, 0.8)
        ),
        "run_ftp_watts": _value(
            power["run_ftp_watts"], "runs: average power ÷ IF (steady ones)", lambda v: _pct(v, 0.8)
        ),
        "lthr_bpm": _value(lthr, "sessions scored by heart rate: from their TSS", statistics.median),
    }
    maxes = sorted((r["hr_max"] for r in rows if r["hr_max"] and 100 <= r["hr_max"] <= 240), reverse=True)
    top = next((a for a, b in zip(maxes, maxes[1:], strict=False) if a - b <= 10), None)
    out["max_hr_bpm"] = (
        {"value": round(top), "sessions": len(maxes), "how": "highest heart rate in a workout (spikes left out)"}
        if top
        else None
    )
    days = [r["day"] for r in rows]
    return {
        "workouts": len(rows),
        "from": days[0] if days else None,
        "to": days[-1] if days else None,
        "values": {k: v for k, v in out.items() if v},
    }
