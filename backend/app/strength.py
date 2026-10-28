"""Strength training for cyclists and runners: the exercise library and AI-written strength sessions.

The library is the public-domain Free Exercise DB (see scripts/import_exercises.py), in
data/exercises.json, with its photos shrunk in data/exercise-images/
(scripts/import_exercise_images.py; the super admin can hide them, `exercise_photos`). Each athlete sets their
strength options in Profile (equipment, level, sports, sessions per week,
minutes, limits). The AI coach gets a shortlist of fitting exercises
(`strength.exercises`) and writes Strength sessions as exercises with sets,
reps, effort and rest; `clean` checks them against the library.
"""

import json
from functools import lru_cache
from pathlib import Path

from . import runtime

DATA = Path(__file__).resolve().parent / "data" / "exercises.json"
# Start (0) and end (1) photos per exercise, 400 px WebP (scripts/import_exercise_images.py).
PHOTOS = DATA.parent / "exercise-images"

# What an athlete can pick in Profile, and the library's equipment values each one unlocks.
EQUIPMENT = {
    "bodyweight": {"body only"},
    "bands": {"bands"},
    "dumbbells": {"dumbbell"},
    "kettlebells": {"kettlebells"},
    "barbell": {"barbell", "e-z curl bar"},
    "gym machines": {"machine", "cable", "other"},
    "medicine ball": {"medicine ball"},
    "exercise ball": {"exercise ball"},
    "foam roller": {"foam roll"},
}
LEVELS = ("beginner", "intermediate", "expert")
SPORTS = ("cycling", "running")
# Muscles that matter for riding and running (legs, hips, trunk, and the back that holds the position).
MUSCLES = {
    "quadriceps",
    "hamstrings",
    "glutes",
    "calves",
    "adductors",
    "abductors",
    "abdominals",
    "lower back",
    "middle back",
    "lats",
}
DEFAULTS = {
    "equipment": ["bodyweight"],
    "level": "beginner",
    "sports": ["cycling"],
    "sessions_per_week": 2,
    "minutes": 45,
    "limits": "",
}
# How many of each group the AI gets, so a full gym doesn't crowd out plyometrics with crunches.
SHARES = {"legs": 60, "trunk": 25, "back": 12, "plyometrics": 18, "stretching": 15}
LEGS = {"quadriceps", "hamstrings", "glutes", "calves", "adductors", "abductors"}
MAX_EXERCISES = 12


@lru_cache(maxsize=1)
def library() -> dict[str, dict]:
    return {e["id"]: e for e in json.loads(DATA.read_text())}


def prefs(user) -> dict:
    """The athlete's strength options, filled in with defaults."""
    saved = getattr(user, "strength_prefs", None) or {}
    return {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}}


def clean_prefs(raw: dict) -> dict:
    """Check strength options from Profile. Raises ValueError."""
    out = dict(DEFAULTS)
    equipment = [e for e in raw.get("equipment") or [] if e in EQUIPMENT]
    out["equipment"] = equipment or ["bodyweight"]
    if raw.get("level") not in LEVELS:
        raise ValueError(f"Level must be one of: {', '.join(LEVELS)}")
    out["level"] = raw["level"]
    sports = [s for s in raw.get("sports") or [] if s in SPORTS]
    if not sports:
        raise ValueError("Pick cycling, running or both")
    out["sports"] = sports
    out["sessions_per_week"] = max(0, min(4, int(raw.get("sessions_per_week") or 0)))
    out["minutes"] = max(15, min(120, int(raw.get("minutes") or 45)))
    out["limits"] = str(raw.get("limits") or "").strip()[:300]
    return out


def _group(e: dict) -> str:
    if e["category"] in ("plyometrics", "stretching"):
        return e["category"]
    muscles = set(e["primaryMuscles"])
    if muscles & LEGS:
        return "legs"
    return "trunk" if muscles & {"abdominals", "lower back"} else "back"


def shortlist(p: dict) -> list[dict]:
    """Exercises that fit the athlete's equipment and level and work the muscles that matter, for the AI.

    Compact: id, name, kind, equipment and main muscles; a share per group (SHARES), multi-joint
    exercises first. Plyometrics only for runners (and riders past beginner)."""
    allowed = set().union(*(EQUIPMENT[e] for e in p["equipment"])) | {"body only"}
    top = LEVELS.index(p["level"])
    want_plyo = "running" in p["sports"] or top >= 1
    groups: dict[str, list[dict]] = {g: [] for g in SHARES}
    for e in library().values():
        if e["equipment"] not in allowed or LEVELS.index(e["level"]) > top:
            continue
        if e["category"] == "plyometrics" and not want_plyo:
            continue
        if not set(e["primaryMuscles"]) & MUSCLES:
            continue
        groups[_group(e)].append(e)
    out = []
    for group, share in SHARES.items():
        picked = sorted(groups[group], key=lambda e: (e["mechanic"] != "compound", e["name"]))[:share]
        out += [
            {
                "id": e["id"],
                "name": e["name"],
                "kind": e["category"],
                "equipment": e["equipment"],
                "muscles": e["primaryMuscles"],
            }
            for e in picked
        ]
    return out


def for_ai(user) -> dict:
    p = prefs(user)
    return {"options": p, "exercises": shortlist(p)}


def _text(raw, limit: int) -> str:
    return str(raw or "").strip()[:limit]


def clean(raw) -> dict | None:
    """A strength session as the AI (or a person) wrote it: only library exercises, sane numbers.

    {"focus": "...", "exercises": [{"id", "name", "sets", "reps", "effort", "rest_s", "note"}]}"""
    if not isinstance(raw, dict):
        return None
    lib = library()
    exercises = []
    for x in raw.get("exercises") or []:
        if not isinstance(x, dict) or x.get("id") not in lib:
            continue
        try:
            sets = max(1, min(10, int(x.get("sets") or 1)))
            rest = max(0, min(600, int(x.get("rest_s") or 0)))
        except (TypeError, ValueError):
            continue
        exercises.append(
            {
                "id": x["id"],
                "name": lib[x["id"]]["name"],
                "sets": sets,
                "reps": _text(x.get("reps"), 20) or "8",
                "effort": _text(x.get("effort"), 40),
                "rest_s": rest,
                "note": _text(x.get("note"), 200),
            }
        )
        if len(exercises) >= MAX_EXERCISES:
            break
    if not exercises:
        return None
    return {"focus": _text(raw.get("focus"), 120), "exercises": exercises}


def photos_on() -> bool:
    """Admin → Settings → "Exercise photos" (super admin): off hides them everywhere."""
    return runtime.get("exercise_photos") != "off"


def photo(exercise_id: str, n: int) -> Path | None:
    """The photo file, if photos are on and it exists. Only library ids, so no path tricks."""
    if not photos_on() or exercise_id not in library() or n not in (0, 1):
        return None
    path = PHOTOS / exercise_id / f"{n}.webp"
    return path if path.is_file() else None


def exercise_out(e: dict) -> dict:
    return {
        "id": e["id"],
        "name": e["name"],
        "category": e["category"],
        "equipment": e["equipment"],
        "level": e["level"],
        "muscles": e["primaryMuscles"],
        "secondary_muscles": e["secondaryMuscles"],
        "instructions": e["instructions"],
        "photos": sum(photo(e["id"], n) is not None for n in (0, 1)),
    }
