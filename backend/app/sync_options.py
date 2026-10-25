"""Which data a user imports from which provider.

Typical setup to avoid duplicate activities: activities from Strava, wellness
only from Garmin. Turning a data type off stops importing it and hides what was
already imported from that provider, so the change shows up at once.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .db import Connection

# "weight" copies the latest Garmin weigh-in into the Profile; "thresholds" does the same for FTP, LTHR and max HR.
KINDS = {
    "strava": ("activities",),
    "garmin": ("activities", "wellness", "weight", "thresholds"),
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
