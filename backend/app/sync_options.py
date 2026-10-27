"""Which data a user imports from which provider.

Activities: the athlete picks a main activity source (Strava, Garmin or
Intervals.icu). Other sources can also import activities, for sessions that are
only there (e.g. walks recorded on Garmin only); when a session is on several,
the main source's copy is the one shown (fitness.dedupe). A new connection only
imports activities when no other source does yet, so the athlete chooses.

Turning a data type off stops importing it and hides what was already imported
from that provider, so the change shows up at once.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .db import Connection

# "weight" copies the latest Garmin weigh-in into the Profile; "thresholds" does the same for FTP, LTHR and max HR.
KINDS = {
    "strava": ("activities",),
    "garmin": ("activities", "wellness", "weight", "thresholds", "birth_date"),
    # Intervals.icu mostly holds copies of Strava/Garmin data, so its imports start off.
    # Sending workouts there is a separate switch (platform_prefs, see platforms.py).
    "intervals_icu": ("activities", "wellness"),
}
DEFAULT_OFF = {("intervals_icu", "activities"), ("intervals_icu", "wellness")}


def options(conn: Connection) -> dict[str, bool]:
    saved = conn.options or {}
    return {kind: bool(saved.get(kind, (conn.provider, kind) not in DEFAULT_OFF)) for kind in KINDS[conn.provider]}


def hidden_sources(db: DbSession, user_id: int, kind: str) -> set[str]:
    """Providers whose `kind` data the user switched off."""
    conns = db.scalars(select(Connection).where(Connection.user_id == user_id)).all()
    return {c.provider for c in conns if kind in KINDS.get(c.provider, ()) and not options(c)[kind]}


def activity_sources(db: DbSession, user_id: int) -> list[str]:
    """Connected providers importing activities (normally one)."""
    conns = db.scalars(select(Connection).where(Connection.user_id == user_id)).all()
    return [c.provider for c in conns if "activities" in KINDS.get(c.provider, ()) and options(c)["activities"]]


def first_activities(db: DbSession, user_id: int, provider: str) -> bool:
    """For a new connection: import activities only when no other source does yet."""
    return not [p for p in activity_sources(db, user_id) if p != provider]


def primary_source(db: DbSession, user_id: int) -> str | None:
    """The main activity source the athlete picked (Connections → Activity source), or None if not picked."""
    conns = db.scalars(select(Connection).where(Connection.user_id == user_id)).all()
    return next((c.provider for c in conns if (c.options or {}).get("primary") and options(c)["activities"]), None)


def set_primary(db: DbSession, conn: Connection) -> None:
    """Make `conn` the main activity source (activities on); the flag moves off the user's other connections."""
    for other in db.scalars(select(Connection).where(Connection.user_id == conn.user_id)).all():
        if other.id != conn.id and (other.options or {}).get("primary"):
            other.options = {k: v for k, v in other.options.items() if k != "primary"}
    conn.options = {**(conn.options or {}), "activities": True, "primary": True}
