"""Favourite Strava routes and segments an athlete trains on.

A segment is a climb or stretch for efforts (hill repeats, intervals); a route
is a whole ride (the Saturday long-ride loop, the easy recovery spin), also
saved from a ride the athlete did (kind "ride", planned like a route). They
are saved by pasting a Strava link, or picked from the athlete's starred
segments and routes on Strava. With Strava linked, the details (length, gradient,
climbing, estimated time) come from Strava. Each gets "uses" (what it's for).

The AI coach gets them (`favourites`) and plans rides on them: it puts the
favourite's id in a session's `segment_id` (the field predates routes) and the
plan shows it as a link that opens in Strava.
"""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .db import Segment

# A "ride" is a past Strava activity saved as a route: the course the athlete rode.
KINDS = ("segment", "route", "ride")
PATHS = {"segments": "segment", "routes": "route", "activities": "ride"}
# What a favourite is for; the AI coach matches them to sessions.
USES = (
    "hill repeats",
    "intervals",
    "sprints",
    "tempo",
    "endurance",
    "long ride",
    "recovery",
    "race simulation",
)
LINK = re.compile(r"strava\.com/(segments|routes|activities)/(\d{3,20})(?:[/?#]|$)")
BARE = re.compile(r"^\d{3,20}$")


def parse_link(text: str) -> tuple[str, int] | None:
    """("segment" | "route" | "ride", id) from a Strava link. A bare number is taken as a segment id."""
    text = text.strip()
    m = LINK.search(text)
    if m:
        return PATHS[m.group(1)], int(m.group(2))
    if BARE.match(text):
        return "segment", int(text)
    return None


def strava_id(text: str) -> int | None:
    """A segment id from a link or number (routes are not segments)."""
    parsed = parse_link(text)
    return parsed[1] if parsed and parsed[0] == "segment" else None


def clean_uses(uses: list[str] | None) -> list[str]:
    return [u for u in USES if u in set(uses or [])]


def url(s: Segment) -> str:
    path = {v: k for k, v in PATHS.items()}[s.kind]
    return f"https://www.strava.com/{path}/{s.strava_id}"


def segment_out(s: Segment) -> dict:
    return {
        "id": s.id,
        "kind": s.kind,
        "strava_id": s.strava_id,
        "name": s.name,
        "url": url(s),
        "distance_m": s.distance_m,
        "avg_grade": s.avg_grade,
        "elevation_m": s.elevation_m,
        "est_minutes": s.est_minutes,
        "sport": s.sport,
        "city": s.city,
        "uses": s.uses or [],
        "notes": s.notes,
    }


def for_athlete(db: DbSession, athlete_id: int) -> list[Segment]:
    return list(
        db.scalars(select(Segment).where(Segment.athlete_id == athlete_id).order_by(Segment.kind, Segment.name))
    )


def for_ai(db: DbSession, athlete_id: int) -> list[dict]:
    """What the AI coach needs to plan on a favourite: id (for `segment_id`), kind, size, uses and notes."""
    out = []
    for s in for_athlete(db, athlete_id):
        # A saved ride is planned like a route; the AI only needs to know it's a course they rode.
        item = {"id": s.id, "kind": "route" if s.kind == "ride" else s.kind, "name": s.name}
        if s.kind == "ride":
            item["from_a_ride"] = True
        if s.kind != "segment" and s.sport != "ride":
            item["sport"] = s.sport
        if s.distance_m:
            item["distance_km"] = round(s.distance_m / 1000, 2 if s.kind == "segment" else 1)
        if s.avg_grade is not None:
            item["avg_grade_pct"] = s.avg_grade
        if s.elevation_m:
            item["climb_m"] = s.elevation_m
        if s.est_minutes:
            item["est_minutes"] = s.est_minutes
        if s.uses:
            item["uses"] = s.uses
        if s.notes:
            item["notes"] = s.notes
        out.append(item)
    return out
