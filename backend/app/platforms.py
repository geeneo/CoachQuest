"""Training platforms: what each can do for an athlete today, and their connection state.

Capabilities are facts about the integration CoachQuest actually has, not what
the platform could do one day. Automatic workout delivery is offered only where
an authorised integration exists: today that is Intervals.icu (OAuth), which
forwards planned workouts to Zwift. Zwift's own Training API needs partner
approval, MyWhoosh has no official API, and Garmin workout delivery needs
Garmin's official developer program.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .db import Connection, User
from .delivery import adapter, intervals_icu
from .security import decrypt_json

CAPABILITIES = {
    "import_activities": "Import activities",
    "import_wellness": "Import sleep, HRV and other wellness",
    "export_files": "Download workout files to load by hand",
    "deliver_workouts": "Send workouts to the athlete's account automatically",
    "update_workouts": "Update and remove workouts it was sent",
}

PLATFORMS = [
    {
        "id": "zwift",
        "name": "Zwift",
        "integration": "export",
        "capabilities": ["export_files"],
        "note": "Download workouts as .zwo files and copy them into Zwift, or connect Intervals.icu (below) and "
        "link Zwift there: Intervals.icu forwards planned workouts to Zwift. A direct link needs Zwift's "
        "official Training API, which requires partner approval.",
    },
    {
        "id": "mywhoosh",
        "name": "MyWhoosh",
        "integration": "unavailable",
        "experimental": True,
        "capabilities": [],
        "note": "No official API. Intervals.icu users report it puts the coming week's planned workouts into "
        "MyWhoosh when MyWhoosh is linked in Intervals.icu (ramps in ERG mode and cadence targets don't carry "
        "over). A community API exists but signs in with your MyWhoosh password, which CoachQuest never asks "
        "for, so it stays off.",
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
        "integration": "connection",
        "requires_setup": True,
        "capabilities": ["deliver_workouts", "update_workouts"],
        "note": "Scheduled workouts go onto your Intervals.icu calendar. Link Zwift in Intervals.icu "
        "(Settings > Zwift) and the coming week's workouts appear in Zwift under Workouts > Custom > "
        "Intervals.icu; users report the same for MyWhoosh. Power is % of FTP, so keep FTP the same everywhere.",
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
        delivery = adapter(p["id"])
        if p.get("requires_setup") and not (delivery and delivery.available()):
            status = "not_configured"  # the admin hasn't added the platform's app keys
        elif p["integration"] == "connection":
            status = "not_connected" if conn is None else ("error" if conn.status == "error" else "connected")
        else:
            status = {"export": "export_only", "unavailable": "not_available"}[p["integration"]]
        can_auto = "deliver_workouts" in p["capabilities"] and status == "connected"
        if can_auto and p["id"] == "intervals_icu" and not intervals_icu.can_send(decrypt_json(conn.token_enc)):
            can_auto = False  # connected without calendar access
        # The athlete's choice stays on while a connection needs fixing; nothing is sent meanwhile.
        auto_on = (
            bool(auto.get(p["id"])) and "deliver_workouts" in p["capabilities"] and status in ("connected", "error")
        )
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
                "auto_sync": auto_on,
                "auto_sync_available": can_auto,
            }
        )
    return out
