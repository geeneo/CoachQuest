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
from datetime import date, datetime, timedelta

import garminconnect
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

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
        conn = Connection(user_id=user.id, provider="garmin", token_enc="")
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


def _fetch(tokens: str, days: list[date]):
    """Blocking Garmin calls; runs in a thread."""
    api = garminconnect.Garmin()
    api.login(tokenstore=tokens)
    wellness = []
    for d in days:
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
    activities = api.get_activities_by_date(days[0].isoformat(), days[-1].isoformat())
    return api.client.dumps(), wellness, activities


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
        new_tokens, wellness, activities = await asyncio.to_thread(_fetch, tokens, days)
    except Exception as exc:
        conn.status = "error"
        conn.last_error = f"{type(exc).__name__}: {exc}"[:500]
        db.commit()
        log.warning("Garmin sync failed for user %s: %s", conn.user_id, exc)
        return 0
    conn.token_enc = encrypt_json({"tokens": new_tokens})
    for row in wellness:
        day = db.scalar(select(WellnessDay).where(WellnessDay.user_id == user.id, WellnessDay.day == row["day"]))
        if day is None:
            day = WellnessDay(user_id=user.id, day=row["day"])
            db.add(day)
        for key, value in row.items():
            if key != "day" and value is not None:
                setattr(day, key, value)
    for item in activities or []:
        if item.get("activityId") and item.get("startTimeGMT"):
            _upsert_activity(db, user, item)
    conn.last_sync_at = utcnow()
    conn.status = "active"
    conn.last_error = None
    db.commit()
    return len(wellness) + len(activities or [])
