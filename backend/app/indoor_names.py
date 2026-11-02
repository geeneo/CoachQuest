"""Indoor sessions don't name outdoor places.

The AI coach is told that indoor days ("Zwift / indoor", "Treadmill run") ride no route or segment,
yet it sometimes names a workout after a favourite ("Kendal A 5x2" from the segment "Kendal climb A").
On a trainer that reads as if the athlete should be on the climb, and Zwift / Intervals.icu show the
name. So whatever the AI writes, an indoor session that mentions a favourite route or segment gets a
plain name from its own steps ("Intervals 5×2 min"), and the sentences naming the place go.

A favourite is mentioned when its whole name, or one of its distinctive words (a place name such as
"Kendal" or "Helshoogte", not "climb", "loop" or "easy"), appears in the text.
"""

import re

from .plan_tracker import extras
from .workouts import duration

INDOOR = {"Zwift / indoor", "Treadmill run"}
# Words in favourite names that aren't places: training words, days, kinds of road.
COMMON = set(
    """
about after around back big climb climbs coffee cool down easy efforts endurance evening fast flat from gravel
group hard hill hills home interval intervals lap laps long loop lunch main monday morning north over pass recovery
repeat repeats ride river road roads route run saturday segment short south spin sprint sprints steep sunday tempo
thursday trail trails tuesday valley wednesday friday with east west this that the and via out top
""".split()
)


def _words(name: str) -> set[str]:
    return {w for w in re.findall(r"[A-Za-zÀ-ÿ'’-]+", name) if len(w) >= 4 and w.lower() not in COMMON}


# Around a mention: "as on", "up the", "like"... before it, and the rest of a segment's name after it
# ("Kendal" + " climb A").
_BEFORE = r"(?:,?\s*(?:as|like|just like)?\s*(?:on|up|at|over|via|along|of|from|to|in)?\s*(?:the\s+)?)"
_AFTER = r"(?:\s+(?:climb|segment|loop|route|hill|[A-Z0-9]{1,3}(?!\w)))*"


def patterns(names: list[str]) -> list[re.Pattern]:
    """One pattern per favourite: its whole name, or any of its distinctive words, with the words around
    it that only make sense with the place."""
    out = []
    for name in names:
        if not name.strip():
            continue
        parts = [re.escape(name.strip())] + [re.escape(w) for w in sorted(_words(name), key=len, reverse=True)]
        out.append(re.compile(_BEFORE + r"(?<!\w)(?:" + "|".join(parts) + r")(?!\w)" + _AFTER, re.I))
    return out


def _mentions(text: str, pats: list[re.Pattern]) -> bool:
    return any(p.search(text or "") for p in pats)


def _span(seconds: int) -> str:
    return f"{seconds // 60} min" if seconds % 60 == 0 else f"{seconds} s"


def plain_name(steps: list[dict]) -> str:
    """A name from the workout itself: its main interval set, else its steady effort."""
    reps = [s for s in steps if s["kind"] == "intervals"]
    if reps:
        main = max(reps, key=lambda s: s["repeat"] * s["on_s"])
        return f"Intervals {main['repeat']}×{_span(main['on_s'])}"
    total = round(duration(steps) / 60)
    top = max((s.get("power") or s.get("power_end") or 0 for s in steps), default=0)
    kind = "Threshold" if top >= 0.91 else "Sweet spot" if top >= 0.84 else "Tempo" if top >= 0.76 else "Endurance"
    return f"{kind} {total} min"


def _clean_text(text: str, pats: list[re.Pattern], fallback: str) -> str:
    """The text without the places; a sentence left with nothing much to say goes."""
    out = []
    for sentence in re.split(r"(?<=[.!?])\s+", (text or "").strip()):
        for p in pats:
            sentence = p.sub("", sentence)
        sentence = re.sub(r"\s+([.,!?;:])", r"\1", re.sub(r"\s{2,}", " ", sentence)).strip(" ,;:-")
        if len(re.findall(r"\w+", sentence)) >= 3:
            out.append(sentence)
    return tidy(" ".join(out)) or fallback


# A climb's details in brackets, e.g. "(0.72 km at 6.2%, 45 m climb, about 2 min each)": a distance and a
# gradient mean nothing on a trainer.
_CLIMB_DETAILS = re.compile(r"[ \t]*\((?=[^)]*\d\s*km)(?=[^)]*\d\s*%)[^)]*\)")


def tidy(text: str) -> str:
    """An indoor description without a climb's details, starting with a capital letter."""
    text = _CLIMB_DETAILS.sub("", text or "")
    text = re.sub(r"[ \t]+([.,!?;:])", r"\1", re.sub(r"[ \t]{2,}", " ", text)).strip(" ,;:-")
    return text[:1].upper() + text[1:]


def scrub_session(session: dict, pats: list[re.Pattern]) -> bool:
    """Take favourite names out of one indoor session; True when it changed."""
    if session.get("type") not in INDOOR:
        return False
    changed = False
    w = session.get("workout")
    if w and _mentions(w.get("name", ""), pats):
        w["name"] = plain_name(w["steps"])
        changed = True
    if _mentions(session.get("description", ""), pats):
        session["description"] = _clean_text(
            session["description"], pats, f"Indoor: {w['name'] if w else session['type']}."
        )
        changed = True
    tidied = tidy(session.get("description", ""))
    if tidied and tidied != session.get("description"):
        session["description"] = tidied  # also plans cleaned before tidy() existed
        changed = True
    return changed


def scrub_day(day: dict, pats: list[re.Pattern]) -> bool:
    return any([scrub_session(s, pats) for s in (day, *extras(day))])


def scrub_weeks(weeks: list[dict], names: list[str], from_date: str = "") -> bool:
    """Every indoor session from `from_date` on (all when empty); True when any changed."""
    pats = patterns(names)
    return any([scrub_day(d, pats) for w in weeks for d in w["days"] if d["date"] >= from_date])
