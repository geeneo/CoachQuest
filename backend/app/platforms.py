"""Training platforms: what each can do for an athlete today, and their connection state.

Capabilities are facts about the integration CoachQuest actually has, not what
the platform could do one day. Automatic workout delivery is offered only where
an authorised integration exists; none does yet (Zwift's Training API needs
partner approval, MyWhoosh has no official API, and Garmin workout delivery
needs Garmin's official developer program).
"""

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .db import Connection, User

CAPABILITIES = {
    "import_activities": "Import activities",
    "import_wellness": "Import sleep, HRV and other wellness",
    "export_files": "Download workout files to load by hand",
    "deliver_workouts": "Send workouts to the athlete's account automatically",
}

PLATFORMS = [
    {
        "id": "zwift",
        "name": "Zwift",
        "integration": "export",
        "capabilities": ["export_files"],
        "note": "Download workouts as .zwo files and copy them into Zwift. Sending them to Zwift "
        "automatically needs Zwift's official Training API, which requires partner approval.",
    },
    {
        "id": "mywhoosh",
        "name": "MyWhoosh",
        "integration": "unavailable",
        "experimental": True,
        "capabilities": [],
        "note": "MyWhoosh has no official API. A community-documented API exists; it stays switched off "
        "until its terms are checked, and is labelled experimental if it is ever turned on.",
    },
    {
        "id": "garmin",
        "name": "Garmin Connect",
        "integration": "connection",
        "capabilities": ["import_activities", "import_wellness"],
        "note": "Sending workouts to a Garmin device needs Garmin's official developer program.",
    },
    {
        "id": "strava",
        "name": "Strava",
        "integration": "connection",
        "capabilities": ["import_activities"],
        "note": "Strava doesn't take structured workouts. Rides from Zwift and MyWhoosh usually arrive "
        "through Strava or Garmin, and are matched to the scheduled workout from there.",
    },
    {
        "id": "intervals_icu",
        "name": "Intervals.icu",
        "integration": "unavailable",
        "capabilities": [],
        "note": "Not connected yet. Its API is being looked at as a way to get workouts into Zwift.",
    },
]
IDS = [p["id"] for p in PLATFORMS]


def platforms_out(db: DbSession, athlete: User, full: bool = True) -> list[dict]:
    """Every platform with this athlete's status. `full` = False hides error text from coaches."""
    conns = {c.provider: c for c in db.scalars(select(Connection).where(Connection.user_id == athlete.id))}
    prefs = athlete.platform_prefs or {}
    preferred = set(prefs.get("preferred") or [])
    auto = prefs.get("auto") or {}
    out = []
    for p in PLATFORMS:
        conn = conns.get(p["id"])
        if p["integration"] == "connection":
            status = "not_connected" if conn is None else ("error" if conn.status == "error" else "connected")
        else:
            status = {"export": "export_only", "unavailable": "not_available"}[p["integration"]]
        can_auto = "deliver_workouts" in p["capabilities"] and status == "connected"
        out.append(
            {
                "id": p["id"],
                "name": p["name"],
                "status": status,
                "experimental": p.get("experimental", False),
                "account": conn.external_id if conn else None,
                "last_sync_at": conn.last_sync_at if conn else None,
                "last_error": (conn.last_error if conn and full else None),
                "capabilities": [{"id": c, "label": CAPABILITIES[c]} for c in p["capabilities"]],
                "note": p["note"],
                "preferred": p["id"] in preferred,
                "auto_sync": bool(auto.get(p["id"])) and can_auto,
                "auto_sync_available": can_auto,
            }
        )
    return out
