"""Multi-day events (stage races): each day its own line, with totals.

A race can have stages (Race.stages, a list): day of the event (1 = the race's date), kind, name,
distance, climbing, terrain, start time, notes, and optionally a favourite route. Rest days are a
stage of kind "rest". With stages, the race's own distance, climbing and number of days are their
totals, so everything that used the race before (countdown, plan length, target CTL) still works.

The AI coach gets each stage and the totals, with the longest and the hardest day; "hardest" weighs
distance and climbing together (100 m of climbing counts like 1 km more), a rule of thumb to point
at the day that will hurt, not a prediction. After the event, each stage shows what was logged that
day.
"""

from datetime import date, timedelta

KINDS = ("prologue", "stage", "time trial", "marathon", "rest")
TERRAINS = ("road", "gravel", "mtb", "mixed", "trail", "")
MAX_STAGES = 30
CLIMB_PER_KM = 100  # metres of climbing that count like one more km


def _num(v, top: float) -> float | None:
    if v in (None, ""):
        return None
    v = float(v)
    if not 0 <= v <= top:
        raise ValueError(f"{v} is out of range")
    return round(v, 1)


def clean(raw: list[dict]) -> list[dict]:
    """Check stages from the Races page; sorted by day, one stage per day. Raises ValueError."""
    if len(raw) > MAX_STAGES:
        raise ValueError(f"At most {MAX_STAGES} days")
    out, seen = [], set()
    for s in raw:
        day = int(s.get("day") or 0)
        if not 1 <= day <= 60:
            raise ValueError("Each stage needs a day of the event, 1 to 60")
        if day in seen:
            raise ValueError(f"Day {day} is there twice")
        seen.add(day)
        kind = s.get("kind") or "stage"
        if kind not in KINDS:
            raise ValueError(f"Kind must be one of: {', '.join(KINDS)}")
        terrain = s.get("terrain") or ""
        if terrain not in TERRAINS:
            raise ValueError(f"Terrain must be one of: {', '.join(t for t in TERRAINS if t)}")
        start = (s.get("start_time") or "").strip()
        if start and not (len(start) == 5 and start[2] == ":" and start.replace(":", "").isdigit()):
            raise ValueError("Start time as hh:mm, e.g. 07:00")
        rest = kind == "rest"
        out.append(
            {
                "day": day,
                "kind": kind,
                "name": (s.get("name") or "").strip()[:80],
                "distance_km": None if rest else _num(s.get("distance_km"), 1000),
                "elevation_m": None if rest else _num(s.get("elevation_m"), 20000),
                "terrain": "" if rest else terrain,
                "start_time": "" if rest else start,
                "notes": (s.get("notes") or "").strip()[:300],
                "segment_id": None if rest else (int(s["segment_id"]) if s.get("segment_id") else None),
            }
        )
    return sorted(out, key=lambda s: s["day"])


def effort(s: dict) -> float:
    return (s.get("distance_km") or 0) + (s.get("elevation_m") or 0) / CLIMB_PER_KM


def totals(stages: list[dict]) -> dict | None:
    """Days, km and climbing for the whole event, and its longest and hardest day."""
    riding = [s for s in stages if s["kind"] != "rest"]
    if not riding:
        return None
    longest = max(riding, key=lambda s: s.get("distance_km") or 0)
    hardest = max(riding, key=effort)
    return {
        "days": max(s["day"] for s in stages),
        "race_days": len(riding),
        "rest_days": len(stages) - len(riding),
        "distance_km": round(sum(s.get("distance_km") or 0 for s in riding), 1),
        "elevation_m": round(sum(s.get("elevation_m") or 0 for s in riding)),
        "longest_day": longest["day"],
        "hardest_day": hardest["day"],
    }


def with_dates(stages: list[dict] | None, first: date | None) -> list[dict]:
    """Each stage with its date (day 1 is the race's date)."""
    return [{**s, "date": (first + timedelta(days=s["day"] - 1)).isoformat() if first else None} for s in stages or []]


def last_day(race) -> date | None:
    """The event's last day (its date for a one-day race)."""
    if race.target_date is None:
        return None
    return race.target_date + timedelta(days=max(1, race.days or 1) - 1)


PROMPT_RULE = """- An upcoming race with `stages` is a multi-day event (stage race): each stage has its day, date, \
kind, distance, climbing and terrain; `stage_totals` gives the whole event, with its longest and hardest \
day (hardest weighs distance and climbing). Plan for riding hard on consecutive days:
  - Build phase: back-to-back long rides at weekends, and 2-3 day blocks shaped like the event's \
hardest days (from about 10 weeks out), with a dress-rehearsal block 3-4 weeks out that copies the \
first 2-3 stages. A recovery week after each block; 3-week build blocks.
  - Taper: short (about a week), focused on freshness; fitness can't be added in race week.
  - The event's days: each stage is a "Race" day with its own description: pacing (hold back on day 1 \
and the prologue, ride the hardest stage by effort, not ego), fuelling per hour from the stage's \
expected time, and recovery for the next day (carbohydrate and protein straight after, easy spin, \
sleep). Rest days in the event: an easy 30-45 min spin.
  - The target CTL for a stage race is higher than for one day of the same length, and the week after \
the event is recovery."""
