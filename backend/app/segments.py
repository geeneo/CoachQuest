"""Strava segments an athlete trains on, e.g. the local climb for hill repeats.

Saved by pasting the segment's Strava link. When the athlete's Strava is
linked, its name, length and gradient come from Strava. The AI coach gets
them (`saved_segments`) and can put one on a plan day (`segment_id`); the
plan shows it as a link that opens in Strava.
"""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .db import Segment

LINK = re.compile(r"(?:strava\.com/segments/|^)(\d{3,12})(?:[/?#]|$)")


def strava_id(text: str) -> int | None:
    """The segment id in a Strava link (https://www.strava.com/segments/1234567) or a bare number."""
    m = LINK.search(text.strip())
    return int(m.group(1)) if m else None


def url(s: Segment) -> str:
    return f"https://www.strava.com/segments/{s.strava_id}"


def segment_out(s: Segment) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "url": url(s),
        "distance_m": s.distance_m,
        "avg_grade": s.avg_grade,
        "elevation_m": s.elevation_m,
        "city": s.city,
        "notes": s.notes,
    }


def for_athlete(db: DbSession, athlete_id: int) -> list[Segment]:
    return list(db.scalars(select(Segment).where(Segment.athlete_id == athlete_id).order_by(Segment.name)))


def for_ai(db: DbSession, athlete_id: int) -> list[dict]:
    """What the AI coach needs to pick a segment: id (for `segment_id`), name, size and how it's used."""
    out = []
    for s in for_athlete(db, athlete_id):
        item = {"id": s.id, "name": s.name}
        if s.distance_m:
            item["distance_km"] = round(s.distance_m / 1000, 2)
        if s.avg_grade is not None:
            item["avg_grade_pct"] = s.avg_grade
        if s.elevation_m:
            item["climb_m"] = s.elevation_m
        if s.notes:
            item["notes"] = s.notes
        out.append(item)
    return out
