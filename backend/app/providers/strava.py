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

from .. import runtime, sync_options
from ..config import settings
from ..db import Activity, Connection, User, UserStravaApp, utcnow
from ..fitness import estimate_tss
from ..security import decrypt_json, encrypt_json

log = logging.getLogger("coachquest.strava")

AUTH_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"
API = "https://www.strava.com/api/v3"
SCOPE = "read,activity:read_all"
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


def redirect_uri() -> str:
    return f"{settings.public_base_url}/api/connections/strava/callback"


def authorize_url(state: str, app: StravaApp) -> str:
    return (
        AUTH_URL
        + "?"
        + urlencode(
            {
                "client_id": app.client_id,
                "redirect_uri": redirect_uri(),
                "response_type": "code",
                "approval_prompt": "auto",
                "scope": SCOPE,
                "state": state,
            }
        )
    )


def _store_tokens(conn: Connection, payload: dict, client_id: str) -> None:
    conn.token_enc = encrypt_json(
        {"access_token": payload["access_token"], "refresh_token": payload["refresh_token"], "client_id": client_id}
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
        conn = Connection(user_id=user.id, provider="strava", token_enc="")
        db.add(conn)
    conn.external_id = str(payload.get("athlete", {}).get("id", ""))
    conn.status = "active"
    conn.last_error = None
    _store_tokens(conn, payload, app.client_id)
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
    act = db.scalar(
        select(Activity).where(Activity.user_id == user.id, Activity.source == "strava", Activity.external_id == ext_id)
    )
    if act is None:
        act = Activity(user_id=user.id, source="strava", external_id=ext_id)
        db.add(act)
    act.name = (item.get("name") or "")[:255]
    act.sport = item.get("sport_type") or item.get("type") or "Other"
    act.start_time = datetime.fromisoformat(item["start_date"].replace("Z", "+00:00")).replace(tzinfo=None)
    act.duration_s = int(item.get("moving_time") or 0)
    act.distance_m = float(item.get("distance") or 0)
    act.elevation_m = float(item.get("total_elevation_gain") or 0)
    act.avg_hr = item.get("average_heartrate")
    act.max_hr = item.get("max_heartrate")
    act.avg_power = item.get("average_watts") if item.get("device_watts") else None
    act.norm_power = item.get("weighted_average_watts") if item.get("device_watts") else None
    act.relative_effort = item.get("suffer_score")
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
    return count


async def deauthorize(conn: Connection) -> None:
    try:
        token = decrypt_json(conn.token_enc)["access_token"]
        async with httpx.AsyncClient(timeout=15) as client:
            await client.post("https://www.strava.com/oauth/deauthorize", data={"access_token": token})
    except Exception as exc:  # best effort; the local tokens are deleted anyway
        log.info("Strava deauthorize failed: %s", exc)
