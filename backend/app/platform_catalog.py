"""Zwift and MyWhoosh workouts that match a plan's indoor days.

Neither platform lets another app search its workouts, so admins upload the
platform's workouts as .zwo files (Zwift's format; MyWhoosh workouts download
in it too) into one shared catalog. Each indoor plan day is compared with the
catalog for the athlete's platforms (Connections → preferred platforms), and
the closest workout is shown with a match score. The athlete or a coach can
swap the day's workout for it, and swap back.

Only the workout's name is shown to athletes; the uploaded files stay on the
server. A super admin can switch the whole thing off (Admin → Settings →
"Match plan workouts to Zwift / MyWhoosh").
"""

import re
import xml.etree.ElementTree as ET

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import runtime, workouts
from .db import PlatformWorkout, User

PLATFORMS = {"zwift": "Zwift", "mywhoosh": "MyWhoosh"}
MAX_FILE_BYTES = 200_000
# Below this the workouts are too different to call a match.
MIN_SCORE = 65
# Efforts at or above this fraction of FTP are the "work" of a workout (sweet spot and up).
WORK_POWER = 0.84


class ZwoError(ValueError):
    pass


def enabled() -> bool:
    return runtime.get("platform_matching") == "on"


def athlete_platforms(athlete: User) -> list[str]:
    """The athlete's preferred platforms that have a catalog, in catalog order."""
    preferred = set((athlete.platform_prefs or {}).get("preferred") or [])
    return [p for p in PLATFORMS if p in preferred]


# ---- Reading .zwo files ----


def _f(el: ET.Element, *names: str) -> float | None:
    for n in names:
        v = el.get(n)
        if v not in (None, ""):
            try:
                return float(v)
            except ValueError:
                raise ZwoError(f"{el.tag}: {n} is not a number") from None
    return None


def _secs(el: ET.Element, name: str = "Duration") -> int:
    v = _f(el, name)
    if v is None:
        raise ZwoError(f"{el.tag} has no {name}")
    return max(5, min(6 * 3600, round(v)))


def _power(v: float | None, default: float) -> float:
    return round(max(0.2, min(3.0, default if v is None else v)), 3)


def _cadence(el: ET.Element, name: str = "Cadence") -> int | None:
    v = _f(el, name)
    return max(30, min(150, round(v))) if v else None


def parse_zwo(text: str) -> dict:
    """{name, description, steps} from a .zwo file. Raises ZwoError."""
    if len(text.encode()) > MAX_FILE_BYTES:
        raise ZwoError("File is too big for a workout")
    if re.search(r"<!(DOCTYPE|ENTITY)", text, re.I):
        raise ZwoError("Not a workout file")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ZwoError(f"Not valid XML ({exc})") from None
    if root.tag != "workout_file":
        raise ZwoError("Not a Zwift workout file (.zwo)")
    sport = (root.findtext("sportType") or "bike").strip().lower()
    if sport != "bike":
        raise ZwoError(f"Only bike workouts can be matched (this one is {sport})")
    body = root.find("workout")
    if body is None or not len(body):
        raise ZwoError("The file has no workout steps")
    steps = []
    for el in body:
        tag = el.tag.lower()
        text_cue = next((t.get("message") for t in el.findall("textevent") if t.get("message")), None)
        if tag in ("warmup", "cooldown", "ramp"):
            lo, hi = _f(el, "PowerLow"), _f(el, "PowerHigh")
            step = {
                "kind": tag,
                "duration_s": _secs(el),
                "power_start": _power(lo, 0.5),
                "power_end": _power(hi, 0.75),
            }
        elif tag in ("steadystate", "solidstate"):
            p = _f(el, "Power")
            if p is None:  # some files give a range instead
                lo, hi = _f(el, "PowerLow"), _f(el, "PowerHigh")
                p = (lo + hi) / 2 if lo is not None and hi is not None else lo or hi
            step = {"kind": "steady", "duration_s": _secs(el), "power": _power(p, 0.6)}
        elif tag == "intervalst":
            on = _f(el, "OnPower", "PowerOnHigh", "PowerOnLow")
            off = _f(el, "OffPower", "PowerOffLow", "PowerOffHigh")
            step = {
                "kind": "intervals",
                "repeat": max(1, min(50, round(_f(el, "Repeat") or 1))),
                "on_s": _secs(el, "OnDuration"),
                "on_power": _power(on, 1.0),
                "off_s": _secs(el, "OffDuration"),
                "off_power": _power(off, 0.5),
            }
            if c := _cadence(el, "CadenceResting"):
                step["off_cadence"] = c
        elif tag == "freeride":
            step = {"kind": "free", "duration_s": _secs(el)}
        elif tag == "maxeffort":
            step = {"kind": "steady", "duration_s": _secs(el), "power": 1.5}
        else:
            continue  # text-only or unknown elements carry no training
        if tag != "freeride" and (c := _cadence(el)):
            step["cadence"] = c
        if text_cue:
            step["text"] = text_cue[:200]
        steps.append(step)
    if not steps:
        raise ZwoError("The file has no workout steps CoachQuest can read")
    name = (root.findtext("name") or "").strip()[:120]
    if not name:
        raise ZwoError("The workout has no name")
    try:
        steps = workouts.validate_steps(steps[:100])
    except ValueError as exc:
        raise ZwoError(str(exc).splitlines()[0]) from None
    return {"name": name, "description": (root.findtext("description") or "").strip()[:2000], "steps": steps}


# ---- Matching ----


def features(steps: list[dict]) -> dict:
    """What a workout is about: length, load, and its work efforts (sweet spot and harder)."""
    est = workouts.estimate(steps)
    efforts, work_s, work_power = 0, 0, 0.0
    in_effort = False
    for b in workouts.blocks(steps):
        p = None if b["power_start"] is None else (b["power_start"] + b["power_end"]) / 2
        if p is not None and p >= WORK_POWER:
            efforts += 0 if in_effort else 1
            in_effort = True
            work_s += b["duration_s"]
            work_power += p * b["duration_s"]
        else:
            in_effort = False
    return {
        "duration_s": est["duration_s"],
        "intensity_factor": est["intensity_factor"] or 0.0,
        "tss": est["tss"] or 0,
        "efforts": efforts,
        "work_s": work_s,
        "work_power": round(work_power / work_s, 3) if work_s else 0.0,
    }


def _rel(a: float, b: float) -> float:
    return abs(a - b) / max(a, b) if max(a, b) else 0.0


def score(want: dict, have: dict) -> int:
    """0-100: how well `have` could stand in for `want` (both from features())."""
    penalty = 30 * _rel(want["duration_s"], have["duration_s"])
    penalty += 250 * abs(want["intensity_factor"] - have["intensity_factor"])
    if want["work_s"] or have["work_s"]:
        penalty += 25 * _rel(want["work_s"], have["work_s"])
        penalty += 200 * abs(want["work_power"] - have["work_power"])
        penalty += 15 * _rel(want["efforts"], have["efforts"])
    return max(0, min(100, round(100 - penalty)))


def best_matches(db: DbSession, steps: list[dict], platforms: list[str], catalog: list | None = None) -> list[dict]:
    """The closest catalog workout per platform, when it is close enough."""
    if not platforms:
        return []
    if catalog is None:
        catalog = load(db, platforms)
    want = features(steps)
    out = []
    for platform in platforms:
        scored = [(score(want, w.features), w) for w in catalog if w.platform == platform]
        if not scored:
            continue
        s, w = max(scored, key=lambda x: x[0])
        if s >= MIN_SCORE:
            out.append(match_out(w, s))
    return out


def load(db: DbSession, platforms: list[str]) -> list[PlatformWorkout]:
    return list(db.scalars(select(PlatformWorkout).where(PlatformWorkout.platform.in_(platforms))))


def match_out(w: PlatformWorkout, s: int) -> dict:
    f = w.features
    return {
        "id": w.id,
        "platform": w.platform,
        "platform_name": PLATFORMS[w.platform],
        "name": w.name,
        "score": s,
        "duration_s": f["duration_s"],
        "tss": f["tss"],
        "intensity_factor": f["intensity_factor"],
    }


def catalog_out(w: PlatformWorkout) -> dict:
    return {
        "id": w.id,
        "platform": w.platform,
        "name": w.name,
        "description": w.description,
        "steps": len(w.steps),
        "duration_s": w.features["duration_s"],
        "tss": w.features["tss"],
        "intensity_factor": w.features["intensity_factor"],
        "created_at": w.created_at,
    }


def add(db: DbSession, platform: str, parsed: dict, admin_id: int) -> str:
    """Add a parsed workout, or replace the one with the same name. Returns "added" or "updated"."""
    w = db.scalar(
        select(PlatformWorkout).where(PlatformWorkout.platform == platform, PlatformWorkout.name == parsed["name"])
    )
    result = "updated" if w else "added"
    if w is None:
        w = PlatformWorkout(platform=platform, name=parsed["name"], added_by=admin_id)
        db.add(w)
    w.description = parsed["description"]
    w.steps = parsed["steps"]
    w.features = features(parsed["steps"])
    return result
