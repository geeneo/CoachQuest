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


# ---- "Where your data comes from" (Connections): one source per kind, confirmed by the user ----

# The kinds a user picks one source for, so the same ride or night isn't imported twice.
CHOOSE = ("activities", "wellness")
LINKED = ("strava", "garmin", "intervals_icu")


def summary(user, conns: list[Connection]) -> dict:
    """Which linked app supplies each kind today, and whether the user still has to confirm it.

    Asked again whenever an app is linked that wasn't there when they last confirmed."""
    conns = sorted((c for c in conns if c.provider in LINKED), key=lambda c: LINKED.index(c.provider))
    linked = [c.provider for c in conns]
    by_kind = {kind: [c.provider for c in conns if kind in KINDS[c.provider] and options(c)[kind]] for kind in CHOOSE}
    choices = {kind: [p for p in linked if kind in KINDS[p]] for kind in CHOOSE}
    new = set(linked) - set(user.sources_confirmed or [])
    return {
        "linked": linked,
        "from": by_kind,
        "choices": choices,
        "needs_confirm": len(linked) >= 2 and bool(new),
        "confirmed": bool(user.sources_confirmed),
    }


def choose(conns: list[Connection], picks: dict[str, str | None]) -> list[Connection]:
    """Turn each kind on for the picked app only (None: from none). Returns connections that got data turned on."""
    turned_on = []
    for c in conns:
        current = options(c) if c.provider in KINDS else {}
        changes = {k: c.provider == picks[k] for k in picks if k in current}
        if not changes:
            continue
        if any(v and not current[k] for k, v in changes.items()):
            turned_on.append(c)
        c.options = {**(c.options or {}), **current, **changes}
    return turned_on
