"""Strava OAuth and activity sync (one connection per user).

Which Strava API app is used: the user's own app if they entered one on the
Connections page, otherwise the server-wide app from Admin settings. The
client_id that issued a connection's tokens is stored with them, because
Strava only refreshes tokens with the app that issued them.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .. import activity_delete, runtime, sync_options
from ..config import settings
from ..db import Activity, Connection, User, UserStravaApp, utcnow
from ..fitness import estimate_tss
from ..security import decrypt_json, encrypt_json

log = logging.getLogger("coachquest.strava")

AUTH_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"
API = "https://www.strava.com/api/v3"
# read_all: the athlete's private routes too (Strava saves routes private by default).
SCOPE = "read,read_all,activity:read_all"
INITIAL_DAYS = 180


@dataclass(frozen=True)
class StravaApp:
    client_id: str
    client_secret: str
    own: bool  # the user's own app, not the server-wide one


class StravaLinkError(Exception):
    """Linking failed. `reason` is a short code the Connections page explains."""

    def __init__(self, reason: str, detail: str = "", public: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.public = public  # Strava's own error text, safe to show the user


def _token_error(resp: httpx.Response) -> StravaLinkError:
    """Turn Strava's token endpoint error into a reason the user can act on."""
    try:
        body = resp.json()
        errors = body.get("errors", []) if isinstance(body, dict) else []
        fields = {e.get("field") for e in errors}
        public = f"Strava said: {body.get('message', '')} " + ", ".join(
            f"{e.get('field')} {e.get('code')}" for e in errors
        )
    except ValueError:
        fields, public = set(), f"Strava answered HTTP {resp.status_code}"
    detail = f"HTTP {resp.status_code}: {resp.text[:300]}"
    # A wrong secret (or one from a different app) comes back as 401 with an empty field.
    if "client_secret" in fields or resp.status_code == 401:
        return StravaLinkError("secret", detail)
    if "client_id" in fields:
        return StravaLinkError("client_id", detail)
    if "code" in fields:
        return StravaLinkError("code", detail)
    return StravaLinkError("strava", detail, public.strip())


class StravaAppChanged(Exception):
    """The app that issued this connection's tokens is no longer configured."""


def server_app() -> StravaApp | None:
    cid, secret = runtime.get("strava_client_id"), runtime.get("strava_client_secret")
    return StravaApp(cid, secret, own=False) if cid and secret else None


def own_app(db: DbSession, user_id: int) -> StravaApp | None:
    row = db.get(UserStravaApp, user_id)
    return StravaApp(row.client_id, decrypt_json(row.secret_enc)["v"], own=True) if row else None


def app_for(db: DbSession, user_id: int) -> StravaApp | None:
    return own_app(db, user_id) or server_app()


def _app_by_client_id(db: DbSession, user_id: int, client_id: str | None) -> StravaApp:
    for app in (own_app(db, user_id), server_app()):
        # Tokens saved before client_id was recorded came from the server app.
        if app and (app.client_id == client_id or (client_id is None and not app.own)):
            return app
    raise StravaAppChanged(
        "The Strava API app this connection was made with has changed. Disconnect and connect again."
    )


def issuing_app(conn: Connection, own_client_id: str | None, shared_client_id: str | None) -> str | None:
    """Which app holds this connection: "own", "shared", "old" (no longer configured), or None if unreadable."""
    try:
        client_id = decrypt_json(conn.token_enc).get("client_id")
    except Exception:
        return None
    if own_client_id and client_id == own_client_id:
        return "own"
    # Same rule as _app_by_client_id: tokens without a client_id came from the server app.
    if client_id is None or client_id == shared_client_id:
        return "shared"
    return "old"


def redirect_uri() -> str:
    return f"{settings.public_base_url}/api/connections/strava/callback"


def authorize_url(state: str, app: StravaApp, write: bool = False) -> str:
    """`write`: also ask to change activities (activity:write), for plan notes (strava_notes.py)."""
    return (
        AUTH_URL
        + "?"
        + urlencode(
            {
                "client_id": app.client_id,
                "redirect_uri": redirect_uri(),
                "response_type": "code",
                "approval_prompt": "auto",
                "scope": SCOPE + (",activity:write" if write else ""),
                "state": state,
            }
        )
    )


def _store_tokens(conn: Connection, payload: dict, client_id: str, scope: str | None = None) -> None:
    """Keep the tokens; the scope granted is kept across refreshes (Strava only sends it on linking)."""
    if scope is None and conn.token_enc:
        scope = decrypt_json(conn.token_enc).get("scope")
    conn.token_enc = encrypt_json(
        {
            "access_token": payload["access_token"],
            "refresh_token": payload["refresh_token"],
            "client_id": client_id,
            "scope": scope,
        }
    )
    conn.expires_at = datetime.fromtimestamp(payload["expires_at"], tz=UTC).replace(tzinfo=None)


async def exchange_code(db: DbSession, user: User, code: str, granted_scope: str) -> Connection:
    if "activity:read" not in granted_scope:
        raise StravaLinkError("scope", f"granted scope was {granted_scope!r}")
    app = app_for(db, user.id)
    if app is None:
        raise StravaLinkError("no_app")
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                TOKEN_URL,
                data={
                    "client_id": app.client_id,
                    "client_secret": app.client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                },
            )
    except httpx.RequestError as exc:
        raise StravaLinkError("network", repr(exc)) from exc
    if resp.is_error:
        raise _token_error(resp)
    payload = resp.json()
    conn = db.scalar(select(Connection).where(Connection.user_id == user.id, Connection.provider == "strava"))
    if conn is None:
        # Another source already brings in activities: the user switches over under Activity source.
        options = None if sync_options.first_activities(db, user.id, "strava") else {"activities": False}
        conn = Connection(user_id=user.id, provider="strava", token_enc="", options=options)
        db.add(conn)
    conn.external_id = str(payload.get("athlete", {}).get("id", ""))
    conn.status = "active"
    conn.last_error = None
    _store_tokens(conn, payload, app.client_id, granted_scope)
    db.commit()
    return conn


async def _access_token(db: DbSession, conn: Connection, client: httpx.AsyncClient) -> str:
    tokens = decrypt_json(conn.token_enc)
    if conn.expires_at and conn.expires_at > utcnow() + timedelta(minutes=5):
        return tokens["access_token"]
    app = _app_by_client_id(db, conn.user_id, tokens.get("client_id"))
    resp = await client.post(
        TOKEN_URL,
        data={
            "client_id": app.client_id,
            "client_secret": app.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
        },
    )
    resp.raise_for_status()
    _store_tokens(conn, resp.json(), app.client_id)
    db.commit()
    return decrypt_json(conn.token_enc)["access_token"]


def _upsert(db: DbSession, user: User, item: dict) -> None:
    ext_id = str(item["id"])
    if activity_delete.is_deleted(db, user.id, "strava", ext_id):
        return  # the athlete deleted it in CoachQuest
    act = db.scalar(
        select(Activity).where(Activity.user_id == user.id, Activity.source == "strava", Activity.external_id == ext_id)
    )
    if act is None:
        act = Activity(user_id=user.id, source="strava", external_id=ext_id)
        db.add(act)
    act.name = (item.get("name") or "")[:255]
    act.sport = item.get("sport_type") or item.get("type") or "Other"
    act.start_time = _start(item)
    act.duration_s = int(item.get("moving_time") or 0)
    act.distance_m = float(item.get("distance") or 0)
    act.elevation_m = float(item.get("total_elevation_gain") or 0)
    act.avg_hr = item.get("average_heartrate")
    act.max_hr = item.get("max_heartrate")
    act.avg_power = item.get("average_watts") if item.get("device_watts") else None
    act.norm_power = item.get("weighted_average_watts") if item.get("device_watts") else None
    act.relative_effort = item.get("suffer_score")
    act.avg_cadence = item.get("average_cadence")
    act.avg_speed_ms = item.get("average_speed")
    act.kilojoules = item.get("kilojoules")
    act.calories = item.get("calories")  # only on detailed activities; usually empty here
    act.indoor = bool(item.get("trainer")) or act.sport in ("VirtualRide", "VirtualRun")
    # Strava's workout_type: 1 = race (runs), 11 = race (rides)
    act.is_race = item.get("workout_type") in (1, 11)
    act.polyline = (item.get("map") or {}).get("summary_polyline") or act.polyline
    act.tss, act.tss_method = estimate_tss(
        act.duration_s,
        act.norm_power,
        act.avg_power,
        act.avg_hr,
        act.relative_effort,
        user.ftp_watts,
        user.lthr_bpm,
    )


async def sync(db: DbSession, conn: Connection) -> int:
    """Pull activities since the last sync. Returns the number fetched."""
    if not sync_options.options(conn)["activities"]:
        return 0
    user = db.get(User, conn.user_id)
    since = conn.last_sync_at - timedelta(days=2) if conn.last_sync_at else utcnow() - timedelta(days=INITIAL_DAYS)
    after = int(since.replace(tzinfo=UTC).timestamp())
    count = 0
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            token = await _access_token(db, conn, client)
            page = 1
            while True:
                resp = await client.get(
                    f"{API}/athlete/activities",
                    params={"after": after, "per_page": 100, "page": page},
                    headers={"Authorization": f"Bearer {token}"},
                )
                resp.raise_for_status()
                items = resp.json()
                if not items:
                    break
                for item in items:
                    _upsert(db, user, item)
                count += len(items)
                page += 1
        conn.last_sync_at = utcnow()
        conn.status = "active"
        conn.last_error = None
    except StravaAppChanged as exc:
        conn.status = "error"
        conn.last_error = str(exc)
    except httpx.HTTPError as exc:
        conn.status = "error"
        conn.last_error = f"{type(exc).__name__}: {exc}"[:500]
        log.warning("Strava sync failed for user %s: %s", conn.user_id, exc)
    db.commit()
    if conn.status == "active":
        from .. import strava_notes  # here, not at the top: strava_notes imports this module

        await strava_notes.auto(db, conn)
    return count


# Leave this much of each Strava limit for regular syncs and other apps that share the API app.
HEADROOM_15MIN = 30
HEADROOM_DAILY = 300


def _resume_time(resp: httpx.Response, now: datetime) -> datetime | None:
    """When the backfill should pause, judging by Strava's rate-limit headers. None means carry on."""

    def pair(name: str) -> tuple[int, int] | None:
        try:
            a, b = resp.headers[name].split(",")[:2]
            return int(a), int(b)
        except (KeyError, ValueError):
            return None

    # Reads have their own (lower) limit on newer apps; fall back to the overall one.
    limit = pair("X-ReadRateLimit-Limit") or pair("X-RateLimit-Limit")
    usage = pair("X-ReadRateLimit-Usage") or pair("X-RateLimit-Usage")
    next_quarter = now.replace(minute=now.minute - now.minute % 15, second=0, microsecond=0) + timedelta(minutes=15)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
    if resp.status_code == 429:
        return tomorrow if usage and limit and usage[1] >= limit[1] else next_quarter
    if not (limit and usage):
        return None
    if usage[1] >= limit[1] - HEADROOM_DAILY:
        return tomorrow
    if usage[0] >= limit[0] - HEADROOM_15MIN:
        return next_quarter
    return None


async def backfill_step(
    db: DbSession, conn: Connection, target: datetime, cursor: datetime
) -> tuple[datetime, int, datetime | None]:
    """Import one page (up to 200) of activities older than `cursor` and newer than `target`.

    Returns (new cursor, number stored, pause until). The new cursor equals
    `target` when there is nothing older left. "Pause until" is set when
    Strava's rate-limit headers say to stop for now.
    """
    user = db.get(User, conn.user_id)
    async with httpx.AsyncClient(timeout=30) as client:
        token = await _access_token(db, conn, client)
        resp = await client.get(
            f"{API}/athlete/activities",
            params={
                "before": int(cursor.replace(tzinfo=UTC).timestamp()),
                "after": int(target.replace(tzinfo=UTC).timestamp()),
                "per_page": 200,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    pause = _resume_time(resp, utcnow())
    if resp.status_code == 429:
        return cursor, 0, pause
    resp.raise_for_status()
    items = resp.json()
    for item in items:
        _upsert(db, user, item)
    db.commit()
    if not items:
        return target, 0, None
    oldest = min(_start(item) for item in items)
    return oldest, len(items), pause


def _start(item: dict) -> datetime:
    return datetime.fromisoformat(item["start_date"].replace("Z", "+00:00")).replace(tzinfo=None)


async def deauthorize(conn: Connection) -> None:
    try:
        token = decrypt_json(conn.token_enc)["access_token"]
        async with httpx.AsyncClient(timeout=15) as client:
            await client.post("https://www.strava.com/oauth/deauthorize", data={"access_token": token})
    except Exception as exc:  # best effort; the local tokens are deleted anyway
        log.info("Strava deauthorize failed: %s", exc)


async def _get(db: DbSession, conn: Connection, path: str, params: dict | None = None):
    async with httpx.AsyncClient(timeout=20) as client:
        token = await _access_token(db, conn, client)
        resp = await client.get(f"{API}{path}", params=params, headers={"Authorization": f"Bearer {token}"})
    if resp.status_code == 404:
        raise LookupError("Strava doesn't know that one (or it's private)")
    resp.raise_for_status()
    return resp.json()


def _segment_out(s: dict) -> dict:
    return {
        "kind": "segment",
        "strava_id": s["id"],
        "name": (s.get("name") or "").strip()[:120],
        "distance_m": round(s.get("distance") or 0),
        "avg_grade": s.get("average_grade"),
        "elevation_m": round((s.get("elevation_high") or 0) - (s.get("elevation_low") or 0)) or None,
        "city": (s.get("city") or "")[:80],
        "polyline": _line(s),
    }


def _line(item: dict) -> str | None:
    """The encoded line on the map: full when Strava gives it, else the summary."""
    m = item.get("map") or {}
    return m.get("polyline") or m.get("summary_polyline") or None


def _route_out(r: dict) -> dict:
    secs = r.get("estimated_moving_time")
    return {
        "kind": "route",
        "strava_id": int(r.get("id_str") or r["id"]),
        "name": (r.get("name") or "").strip()[:120],
        "distance_m": round(r.get("distance") or 0),
        "elevation_m": round(r.get("elevation_gain") or 0) or None,
        "est_minutes": round(secs / 60) if secs else None,
        "sport": "run" if r.get("type") == 2 else "ride",
        "polyline": _line(r),
    }


async def segment(db: DbSession, conn: Connection, segment_id: int) -> dict:
    """A segment's public details (name, length, gradient) from Strava, read with the athlete's own link."""
    return _segment_out(await _get(db, conn, f"/segments/{segment_id}"))


async def route(db: DbSession, conn: Connection, route_id: int) -> dict:
    """A route's details (name, length, climbing, estimated time) from Strava."""
    return _route_out(await _get(db, conn, f"/routes/{route_id}"))


async def activity(db: DbSession, conn: Connection, activity_id: int) -> dict:
    """One of the athlete's own rides, to save as a route (when it isn't imported yet)."""
    a = await _get(db, conn, f"/activities/{activity_id}")
    secs = a.get("moving_time") or a.get("elapsed_time")
    return {
        "name": (a.get("name") or "").strip()[:120],
        "distance_m": round(a.get("distance") or 0),
        "elevation_m": round(a.get("total_elevation_gain") or 0) or None,
        "est_minutes": round(secs / 60) if secs else None,
        "sport": "run" if "Run" in (a.get("sport_type") or a.get("type") or "") else "ride",
        "polyline": _line(a),
    }


def can_write(conn: Connection) -> bool:
    """Whether the athlete let CoachQuest change their activities (linked with activity:write)."""
    return "activity:write" in (decrypt_json(conn.token_enc).get("scope") or "").split(",")


async def get_activity(db: DbSession, conn: Connection, activity_id: str) -> dict:
    return await _get(db, conn, f"/activities/{activity_id}")


async def update_activity(db: DbSession, conn: Connection, activity_id: str, changes: dict) -> dict:
    """PUT /activities/{id} (needs activity:write)."""
    async with httpx.AsyncClient(timeout=20) as client:
        token = await _access_token(db, conn, client)
        resp = await client.put(
            f"{API}/activities/{activity_id}", json=changes, headers={"Authorization": f"Bearer {token}"}
        )
        if resp.status_code == 404:
            raise LookupError("Not on Strava (deleted, or not yours)")
        resp.raise_for_status()
        return resp.json()


def sees_private_routes(conn: Connection) -> bool:
    """Whether the athlete let us read private routes (linked with read_all; earlier links weren't)."""
    return "read_all" in (decrypt_json(conn.token_enc).get("scope") or "").split(",")


async def favourites(db: DbSession, conn: Connection) -> list[dict]:
    """The athlete's starred segments and their own routes on Strava, to pick favourites from."""
    starred = await _get(db, conn, "/segments/starred", {"per_page": 100})
    routes = await _get(db, conn, f"/athletes/{conn.external_id}/routes", {"per_page": 100}) if conn.external_id else []
    return [_segment_out(s) for s in starred] + [_route_out(r) for r in routes]
