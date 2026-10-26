"""Import activities and wellness from Intervals.icu (optional; see sync_options.py).

Uses the same OAuth token as workout delivery (delivery/intervals_icu.py), with
the ACTIVITY:READ and WELLNESS:READ scopes. Field names are from the official
OpenAPI document at https://intervals.icu/api/v1/docs.

Both imports are off by default: most athletes' Intervals.icu data comes from
Strava or Garmin, which CoachQuest already imports. Turn them on to use
Intervals.icu as a source instead (for example if Garmin access stops working).

- Activities that Intervals.icu got from Strava (source "STRAVA") are skipped:
  Strava doesn't allow Intervals.icu to pass them on, and the Strava connection
  imports them anyway.
- A ride that also came from Strava or Garmin is shown once (fitness.dedupe).
- Wellness fills one row per day. Garmin's values win; Intervals.icu fills what
  Garmin left empty, or the whole day when Garmin has nothing.
"""

import logging
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .. import activity_delete, sync_options
from ..db import Activity, Connection, User, WellnessDay, utcnow
from ..delivery import intervals_icu as api
from ..delivery.base import AuthFailed, DeliveryError, Forbidden
from ..fitness import estimate_tss
from ..security import decrypt_json

log = logging.getLogger("coachquest.intervals")

INITIAL_DAYS = 30
RECENT_DAYS = 7  # every sync looks back this far, so late edits and uploads come in
SOURCE = "intervals_icu"
WELLNESS_FIELDS = {
    "restingHR": "resting_hr",
    "hrv": "hrv_ms",
    "sleepSecs": "sleep_s",
    "sleepScore": "sleep_score",
    "steps": "steps",
}


def _utc(item: dict) -> datetime | None:
    raw = item.get("start_date")
    if not raw:
        return None
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))  # start_date is UTC; stored as naive UTC
    return dt.astimezone(UTC).replace(tzinfo=None) if dt.tzinfo else dt


def upsert_activity(db: DbSession, user: User, item: dict) -> Activity | None:
    if (item.get("source") or "").upper() == "STRAVA" or not item.get("id"):
        return None
    start = _utc(item)
    if start is None:
        return None
    ext_id = str(item["id"])
    if activity_delete.is_deleted(db, user.id, SOURCE, ext_id):
        return None  # the athlete deleted it in CoachQuest
    act = db.scalar(
        select(Activity).where(Activity.user_id == user.id, Activity.source == SOURCE, Activity.external_id == ext_id)
    )
    if act is None:
        act = Activity(user_id=user.id, source=SOURCE, external_id=ext_id)
        db.add(act)
    act.name = (item.get("name") or "")[:255]
    act.sport = (item.get("type") or "Other")[:40]  # same names as Strava's sport_type
    act.start_time = start
    act.duration_s = int(item.get("moving_time") or item.get("elapsed_time") or 0)
    act.distance_m = float(item.get("distance") or 0)
    act.elevation_m = float(item.get("total_elevation_gain") or 0)
    act.avg_hr = item.get("average_heartrate")
    act.max_hr = item.get("max_heartrate")
    act.avg_power = item.get("icu_average_watts")
    act.norm_power = item.get("icu_weighted_avg_watts")
    act.avg_cadence = item.get("average_cadence")
    act.avg_speed_ms = item.get("average_speed")
    act.calories = item.get("calories")
    act.kilojoules = round(item["icu_joules"] / 1000, 1) if item.get("icu_joules") else None
    act.indoor = bool(item.get("trainer")) or act.sport.startswith("Virtual")
    act.is_race = bool(item.get("race"))
    if item.get("icu_training_load") is not None:
        act.tss, act.tss_method = float(item["icu_training_load"]), SOURCE
    else:
        act.tss, act.tss_method = estimate_tss(
            act.duration_s, act.norm_power, act.avg_power, act.avg_hr, None, user.ftp_watts, user.lthr_bpm
        )
    return act


def store_wellness(db: DbSession, user: User, row: dict) -> None:
    try:
        day = date.fromisoformat(row["id"])
    except (KeyError, ValueError):
        return
    values = {ours: row.get(theirs) for theirs, ours in WELLNESS_FIELDS.items() if row.get(theirs) is not None}
    if not values:
        return
    w = db.scalar(select(WellnessDay).where(WellnessDay.user_id == user.id, WellnessDay.day == day))
    if w is None:
        w = WellnessDay(user_id=user.id, day=day, source=SOURCE)
        db.add(w)
    for key, value in values.items():
        if w.source == SOURCE or getattr(w, key) is None:  # Garmin's own values win
            setattr(w, key, value)


async def _get(token: dict, path: str, params: dict) -> list:
    r = await api.IntervalsIcu()._call(token, "GET", path, params=params)
    data = r.json()
    return data if isinstance(data, list) else []


async def sync(db: DbSession, conn: Connection) -> int:
    """Import what the athlete chose. Never touches workout delivery."""
    opts = sync_options.options(conn)
    if not (opts["activities"] or opts["wellness"]):
        return 0
    user = db.get(User, conn.user_id)
    today = date.today()
    first = (conn.options or {}).get("imported_at") is None
    oldest = today - timedelta(days=INITIAL_DAYS if first else RECENT_DAYS)
    params = {"oldest": oldest.isoformat(), "newest": (today + timedelta(days=1)).isoformat()}
    count = 0
    try:
        token = decrypt_json(conn.token_enc)
        if opts["activities"]:
            for item in await _get(token, "/api/v1/athlete/0/activities", params):
                count += upsert_activity(db, user, item) is not None
        if opts["wellness"]:
            for row in await _get(token, "/api/v1/athlete/0/wellness", params):
                store_wellness(db, user, row)
                count += 1
    except (AuthFailed, Forbidden) as exc:
        conn.status, conn.last_error = "error", exc.message
        db.commit()
        return 0
    except DeliveryError as exc:
        conn.last_error = f"Import: {exc.message}"[:500]
        db.commit()
        log.warning("Intervals.icu import failed for user %s: %s", conn.user_id, exc.message)
        return 0
    conn.options = {**(conn.options or {}), "imported_at": utcnow().isoformat()}
    conn.last_sync_at = utcnow()
    conn.last_error = None
    db.commit()
    return count
