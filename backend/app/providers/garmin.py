"""Garmin Connect link via the unofficial `garminconnect` library.

The user's Garmin password is used once to log in and is never stored. Only
the resulting session tokens are kept, encrypted. MFA is supported: the
half-finished login state is kept encrypted for 10 minutes until the user
enters the code.

Garmin has no public OAuth for individual developers. For a commercial,
multi-tenant service, apply to the Garmin Connect Developer Program
(Health/Activity API) and replace this module.
"""

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta

import garminconnect
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .. import profile_sync, sync_options
from ..db import Activity, Connection, PendingMfa, User, WellnessDay, utcnow
from ..fitness import estimate_tss
from ..security import decrypt_json, encrypt_json

log = logging.getLogger("coachquest.garmin")

INITIAL_DAYS = 30
MFA_TTL = timedelta(minutes=10)


class GarminLinkError(Exception):
    pass


def _save_tokens(db: DbSession, user: User, api: garminconnect.Garmin) -> Connection:
    conn = db.scalar(select(Connection).where(Connection.user_id == user.id, Connection.provider == "garmin"))
    if conn is None:
        # With Strava already bringing in activities, start Garmin on wellness only
        # so the same ride isn't imported twice. The user can change this.
        strava = db.scalar(select(Connection).where(Connection.user_id == user.id, Connection.provider == "strava"))
        uses_strava = strava is not None and sync_options.options(strava)["activities"]
        conn = Connection(
            user_id=user.id, provider="garmin", token_enc="", options={"activities": not uses_strava, "wellness": True}
        )
        db.add(conn)
    conn.token_enc = encrypt_json({"tokens": api.client.dumps()})
    conn.external_id = getattr(api, "display_name", None)
    conn.status = "active"
    conn.last_error = None
    db.commit()
    return conn


def _login(email: str, password: str):
    api = garminconnect.Garmin(email, password, return_on_mfa=True)
    status, state = api.login()
    return api, status, state


async def start_link(db: DbSession, user: User, email: str, password: str) -> str:
    """Returns "connected" or "needs_mfa"."""
    try:
        api, status, state = await asyncio.to_thread(_login, email, password)
    except garminconnect.GarminConnectAuthenticationError as exc:
        raise GarminLinkError("Garmin rejected the email or password.") from exc
    except (garminconnect.GarminConnectConnectionError, garminconnect.GarminConnectTooManyRequestsError) as exc:
        raise GarminLinkError("Could not reach Garmin Connect, try again later.") from exc
    if status == "needs_mfa":
        db.merge(PendingMfa(user_id=user.id, state_enc=encrypt_json({"state": state}), created_at=utcnow()))
        db.commit()
        return "needs_mfa"
    _save_tokens(db, user, api)
    return "connected"


async def finish_mfa(db: DbSession, user: User, code: str) -> None:
    pending = db.get(PendingMfa, user.id)
    if pending is None or pending.created_at < utcnow() - MFA_TTL:
        raise GarminLinkError("The Garmin login expired. Start again.")
    state = decrypt_json(pending.state_enc)["state"]

    def _resume():
        api = garminconnect.Garmin(return_on_mfa=True)
        api.resume_login(state, code)
        return api

    try:
        api = await asyncio.to_thread(_resume)
    except Exception as exc:
        raise GarminLinkError("The MFA code was not accepted.") from exc
    finally:
        db.delete(pending)
        db.commit()
    _save_tokens(db, user, api)


def _num(d: dict | None, *path):
    cur = d
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur if isinstance(cur, (int, float)) else None


def latest_weight(data) -> tuple[float, datetime] | None:
    """(kg, measured_at) from Garmin's latest-weight reply, or None.

    Garmin reports weight in grams. The reply shape varies a little between
    accounts, so look for the weigh-in in the usual places.
    """
    if isinstance(data, list):
        data = data[-1] if data else None
    if isinstance(data, dict) and isinstance(data.get("dateWeightList"), list):
        data = data["dateWeightList"][-1] if data["dateWeightList"] else None
    if not isinstance(data, dict):
        return None
    grams = data.get("weight")
    if not isinstance(grams, (int, float)) or grams <= 0:
        return None
    kg = round(grams / 1000, 1) if grams > 1000 else round(float(grams), 1)
    when = None
    for key in ("timestampGMT", "date", "samplePk"):
        if isinstance(data.get(key), (int, float)):
            when = datetime.fromtimestamp(data[key] / 1000, tz=UTC).replace(tzinfo=None)
            break
    if when is None and isinstance(data.get("calendarDate"), str):
        when = datetime.fromisoformat(data["calendarDate"])
    return (kg, when or datetime.now(UTC).replace(tzinfo=None)) if 20 <= kg <= 300 else None


def _first_number(*candidates):
    for value in candidates:
        if isinstance(value, (int, float)) and value > 0:
            return int(round(value))
    return None


def _by_sport(zones, *sports) -> dict:
    """Pick the zone settings for the first matching sport (Garmin uses e.g. CYCLING, DEFAULT)."""
    if not isinstance(zones, list):
        return {}
    for sport in sports:
        for z in zones:
            if isinstance(z, dict) and str(z.get("sport", "")).upper() == sport:
                return z
    return next((z for z in zones if isinstance(z, dict)), {})


def parse_thresholds(ftp_reply, power_zones, hr_zones) -> dict:
    """FTP, LTHR and max HR from Garmin's replies. Missing values come back as None."""
    if isinstance(ftp_reply, list):
        ftp_reply = ftp_reply[0] if ftp_reply else {}
    ftp_reply = ftp_reply if isinstance(ftp_reply, dict) else {}
    power = _by_sport(power_zones, "CYCLING")
    hr = _by_sport(hr_zones, "CYCLING", "DEFAULT")
    ftp = _first_number(ftp_reply.get("functionalThresholdPower"), power.get("functionalThresholdPower"))
    return {
        "ftp_watts": ftp if ftp and 50 <= ftp <= 600 else None,
        "lthr_bpm": _first_number(hr.get("lactateThresholdHeartRateUsed")),
        "max_hr_bpm": _first_number(hr.get("maxHeartRateUsed")),
    }


def _thresholds(api) -> dict:
    replies = []
    for call in (api.get_cycling_ftp, api.get_power_zones, api.get_heart_rate_zones_v2):
        try:
            replies.append(call())
        except Exception as exc:
            log.debug("%s failed: %s", call.__name__, exc)
            replies.append(None)
    return parse_thresholds(*replies)


def _fetch(
    tokens: str,
    wellness_days: list[date],
    activity_range: tuple[date, date] | None,
    want_weight: bool,
    want_thresholds: bool = False,
):
    """Blocking Garmin calls; runs in a thread.

    Returns (tokens, wellness rows, activities, weight, thresholds).
    """
    api = garminconnect.Garmin()
    api.login(tokenstore=tokens)
    wellness = []
    for d in wellness_days:
        iso = d.isoformat()
        row = {"day": d}
        try:
            s = api.get_user_summary(iso)
            row.update(
                resting_hr=_num(s, "restingHeartRate"),
                steps=_num(s, "totalSteps"),
                stress_avg=_num(s, "averageStressLevel"),
                body_battery_max=_num(s, "bodyBatteryHighestValue"),
            )
        except Exception as exc:
            log.debug("summary %s failed: %s", iso, exc)
        try:
            sl = api.get_sleep_data(iso)
            row.update(
                sleep_s=_num(sl, "dailySleepDTO", "sleepTimeSeconds"),
                sleep_score=_num(sl, "dailySleepDTO", "sleepScores", "overall", "value"),
            )
        except Exception as exc:
            log.debug("sleep %s failed: %s", iso, exc)
        try:
            row["hrv_ms"] = _num(api.get_hrv_data(iso), "hrvSummary", "lastNightAvg")
        except Exception as exc:
            log.debug("hrv %s failed: %s", iso, exc)
        wellness.append(row)
    weight = None
    if want_weight:
        try:
            weight = latest_weight(api.get_latest_weight())
        except Exception as exc:
            log.debug("latest weight failed: %s", exc)
    thresholds = _thresholds(api) if want_thresholds else None
    activities = []
    if activity_range:
        activities = api.get_activities_by_date(activity_range[0].isoformat(), activity_range[1].isoformat())
    return api.client.dumps(), wellness, activities, weight, thresholds


def _upsert_activity(db: DbSession, user: User, item: dict) -> None:
    ext_id = str(item.get("activityId"))
    act = db.scalar(
        select(Activity).where(Activity.user_id == user.id, Activity.source == "garmin", Activity.external_id == ext_id)
    )
    if act is None:
        act = Activity(user_id=user.id, source="garmin", external_id=ext_id)
        db.add(act)
    act.name = (item.get("activityName") or "")[:255]
    act.sport = (item.get("activityType") or {}).get("typeKey", "other")
    act.start_time = datetime.fromisoformat(item["startTimeGMT"].replace(" ", "T"))
    act.duration_s = int(item.get("movingDuration") or item.get("duration") or 0)
    act.distance_m = float(item.get("distance") or 0)
    act.elevation_m = float(item.get("elevationGain") or 0)
    act.avg_hr = item.get("averageHR")
    act.max_hr = item.get("maxHR")
    act.avg_power = item.get("avgPower")
    act.norm_power = item.get("normPower")
    act.avg_cadence = item.get("averageBikingCadenceInRevPerMinute") or item.get(
        "averageRunningCadenceInStepsPerMinute"
    )
    act.avg_speed_ms = item.get("averageSpeed")
    act.calories = item.get("calories")
    act.indoor = act.sport in ("virtual_ride", "indoor_cycling", "treadmill_running", "indoor_running")
    act.tss, act.tss_method = estimate_tss(
        act.duration_s, act.norm_power, act.avg_power, act.avg_hr, None, user.ftp_watts, user.lthr_bpm
    )


async def sync(db: DbSession, conn: Connection) -> int:
    user = db.get(User, conn.user_id)
    today = date.today()
    start = conn.last_sync_at.date() - timedelta(days=1) if conn.last_sync_at else today - timedelta(days=INITIAL_DAYS)
    days = [start + timedelta(days=i) for i in range((today - start).days + 1)]
    try:
        tokens = decrypt_json(conn.token_enc)["tokens"]
        opts = sync_options.options(conn)
        new_tokens, wellness, activities, weight, thresholds = await asyncio.to_thread(
            _fetch,
            tokens,
            days if opts["wellness"] else [],
            (days[0], days[-1]) if opts["activities"] else None,
            opts["weight"],
            opts["thresholds"],
        )

    except Exception as exc:
        conn.status = "error"
        conn.last_error = f"{type(exc).__name__}: {exc}"[:500]
        db.commit()
        log.warning("Garmin sync failed for user %s: %s", conn.user_id, exc)
        return 0
    conn.token_enc = encrypt_json({"tokens": new_tokens})
    _store(db, user, wellness, activities, weight)
    if thresholds:
        profile_sync.apply_from_provider(db, user, "garmin", thresholds)
    conn.last_sync_at = utcnow()
    conn.status = "active"
    conn.last_error = None
    db.commit()
    return len(wellness) + len(activities or [])


def _store(db: DbSession, user: User, wellness: list, activities: list | None, weight=None) -> None:
    for row in wellness:
        day = db.scalar(select(WellnessDay).where(WellnessDay.user_id == user.id, WellnessDay.day == row["day"]))
        if day is None:
            day = WellnessDay(user_id=user.id, day=row["day"])
            db.add(day)
        for key, value in row.items():
            if key != "day" and value is not None:
                setattr(day, key, value)
    if weight:
        kg, measured_at = weight
        if user.weight_updated_at is None or measured_at > user.weight_updated_at:
            user.weight_kg, user.weight_source, user.weight_updated_at = kg, "garmin", measured_at
    for item in activities or []:
        if item.get("activityId") and item.get("startTimeGMT"):
            _upsert_activity(db, user, item)


# Wellness needs ~3 requests per day of history, so the backfill stops at a year.
BACKFILL_WELLNESS_DAYS = 365
BACKFILL_CHUNK_DAYS = 14


async def backfill_step(db: DbSession, conn: Connection, target: date, cursor: date) -> tuple[date, int]:
    """Import the chunk of days just before `cursor` (not before `target`).

    Returns the new cursor (the oldest day now covered) and how many items were stored.
    """
    user = db.get(User, conn.user_id)
    end = cursor - timedelta(days=1)
    start = max(target, end - timedelta(days=BACKFILL_CHUNK_DAYS - 1))
    if end < start:
        return cursor, 0
    opts = sync_options.options(conn)
    oldest_wellness = date.today() - timedelta(days=BACKFILL_WELLNESS_DAYS)
    wellness_days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    wellness_days = [d for d in wellness_days if d >= oldest_wellness] if opts["wellness"] else []
    tokens = decrypt_json(conn.token_enc)["tokens"]
    new_tokens, wellness, activities, _, _ = await asyncio.to_thread(
        _fetch, tokens, wellness_days, (start, end) if opts["activities"] else None, False
    )
    conn.token_enc = encrypt_json({"tokens": new_tokens})
    _store(db, user, wellness, activities)
    db.commit()
    return start, len(wellness) + len(activities or [])
