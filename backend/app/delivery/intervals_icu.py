"""Intervals.icu: puts scheduled workouts on the athlete's Intervals.icu calendar.

Intervals.icu is an approved Zwift Training API partner: when the athlete has
linked Zwift in Intervals.icu, planned workouts for the coming week appear in
Zwift under Workouts > Custom > Intervals.icu. (It can also send them on to
Garmin and others from its own settings.) That makes it CoachQuest's
authorised route into Zwift until CoachQuest has its own partner approval.

Documented API used (see forum.intervals.icu "API access" and "Intervals.icu
OAuth support"):

- OAuth: authorize at https://intervals.icu/oauth/authorize, exchange the code
  at https://intervals.icu/api/oauth/token. Scope CALENDAR:WRITE. Apps must
  use OAuth; personal API keys are for one's own scripts. The app's client id
  and secret come from intervals.icu/settings/apps after applying.
- Upsert: POST /api/v1/athlete/0/events/bulk?upsert=true, keyed by our own
  `external_id`. Athlete 0 = the athlete the token belongs to.
- Delete: PUT /api/v1/athlete/0/events/bulk-delete with [{"external_id": ...}].
  Missing events are ignored, so deleting twice is safe.
- Disconnect: DELETE /api/v1/disconnect-app.

The workout goes as a .zwo file (`filename` + `file_contents`), which
Intervals.icu parses into steps, so power stays a percentage of FTP.
"""

from datetime import date
from urllib.parse import urlencode

import httpx

from .. import runtime, zwo
from ..config import settings
from .base import Adapter, AuthFailed, Delivered, Forbidden, NotSupported, RateLimited, Rejected, Transient

BASE = settings.intervals_base_url  # https://intervals.icu
# Calendar write sends workouts; activity and wellness read let the athlete import from Intervals.icu.
CALENDAR = "CALENDAR:WRITE"
SCOPE = "CALENDAR:WRITE,ACTIVITY:READ,WELLNESS:READ"
TIMEOUT = 20

# Tests swap this for an httpx.MockTransport; nothing real is called in tests.
transport: httpx.AsyncBaseTransport | None = None


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=BASE, timeout=TIMEOUT, transport=transport)


def redirect_uri() -> str:
    return f"{settings.public_base_url}/api/connections/intervals/callback"


def configured() -> bool:
    return bool(runtime.get("intervals_client_id") and runtime.get("intervals_client_secret"))


def authorize_url(state: str) -> str:
    query = {
        "client_id": runtime.get("intervals_client_id"),
        "redirect_uri": redirect_uri(),
        "scope": SCOPE,
        "state": state,
    }
    return f"{BASE}/oauth/authorize?{urlencode(query)}"


class LinkError(Exception):
    pass


async def check_app() -> dict:
    """Admin test: are the Client ID and secret right? Nobody signs in and nothing changes.

    Exchanges a made-up code. Intervals.icu answers "Client and/or secret not found" when the
    ID or secret is wrong; any other refusal means it knew the app and only rejected the code."""
    out = {"redirect_uri": redirect_uri()}
    if not configured():
        return {**out, "ok": False, "message": "Set the Client ID and Client secret first."}
    data = {
        "client_id": runtime.get("intervals_client_id"),
        "client_secret": runtime.get("intervals_client_secret"),
        "code": "coachquest-connection-test",
    }
    try:
        async with _client() as c:
            r = await c.post("/api/oauth/token", data=data)
    except httpx.HTTPError as exc:
        return {**out, "ok": False, "message": f"Could not reach intervals.icu ({type(exc).__name__})."}
    if "not found" in r.text.lower() and "client" in r.text.lower():
        return {**out, "ok": False, "message": "Intervals.icu doesn't know this Client ID and secret. Copy both again."}
    if r.status_code >= 500:
        return {**out, "ok": False, "message": f"Intervals.icu had a problem (HTTP {r.status_code}). Try later."}
    notes = []
    if not out["redirect_uri"].startswith("https://"):
        notes.append("PUBLIC_BASE_URL isn't https, so signing in will only work for local testing")
    message = (
        "Client ID and secret accepted by Intervals.icu. Make sure this Redirect URL is added to the app on "
        f"intervals.icu/settings/apps: {out['redirect_uri']}"
    )
    if notes:
        message += ". Note: " + "; ".join(notes) + "."
    return {**out, "ok": True, "message": message}


async def exchange_code(code: str) -> dict:
    """Swap the one-time code for a token. Returns {access_token, scope, athlete_id, athlete_name}."""
    data = {
        "client_id": runtime.get("intervals_client_id"),
        "client_secret": runtime.get("intervals_client_secret"),
        "code": code,
    }
    try:
        async with _client() as c:
            r = await c.post("/api/oauth/token", data=data)
    except httpx.HTTPError as exc:
        raise LinkError(f"Could not reach intervals.icu ({type(exc).__name__})") from exc
    if r.status_code != 200:
        raise LinkError(f"Intervals.icu refused the link (HTTP {r.status_code})")
    body = r.json()
    if not body.get("access_token"):
        raise LinkError("Intervals.icu returned no access token")
    granted = set((body.get("scope") or "").split(","))
    if not granted & set(SCOPE.split(",")):
        raise LinkError("No access was granted. Connect again and allow access.")
    athlete = body.get("athlete") or {}
    return {
        "access_token": body["access_token"],
        "scope": body.get("scope"),
        "athlete_id": str(athlete.get("id") or ""),
        "athlete_name": athlete.get("name"),
    }


def _raise_for(r: httpx.Response) -> None:
    if r.status_code < 400:
        return
    detail = r.text[:200].strip()
    if r.status_code == 429:
        try:
            wait = int(r.headers.get("Retry-After", "60"))
        except ValueError:
            wait = 60
        raise RateLimited("Intervals.icu asked us to slow down", retry_after=wait)
    if r.status_code == 401:
        raise AuthFailed("Intervals.icu no longer accepts CoachQuest's access. Reconnect Intervals.icu.")
    if r.status_code == 403:
        raise Forbidden(
            "Intervals.icu refused access to the calendar. Reconnect Intervals.icu and allow calendar access."
        )
    if r.status_code >= 500:
        raise Transient(f"Intervals.icu had a problem (HTTP {r.status_code})")
    raise Rejected(f"Intervals.icu rejected the workout (HTTP {r.status_code}): {detail}")


def can_send(token: dict) -> bool:
    """Was calendar access granted (needed to send workouts)?"""
    return CALENDAR in set((token.get("scope") or "").split(","))


class IntervalsIcu(Adapter):
    id = "intervals_icu"
    name = "Intervals.icu"
    operations = ("upsert", "delete")

    def available(self) -> bool:
        return configured()

    async def _call(self, token: dict, method: str, path: str, **kw) -> httpx.Response:
        if not token.get("access_token"):
            raise AuthFailed("No Intervals.icu access token. Reconnect Intervals.icu.")
        headers = {"Authorization": f"Bearer {token['access_token']}"}
        try:
            async with _client() as c:
                r = await c.request(method, path, headers=headers, **kw)
        except httpx.HTTPError as exc:
            raise Transient(f"Could not reach intervals.icu ({type(exc).__name__})") from exc
        _raise_for(r)
        return r

    async def upsert(self, token: dict, external_id: str, workout: dict, day: date) -> Delivered:
        if workout.get("sport", "bike") != "bike":
            raise NotSupported("Only bike workouts can be sent")
        event = {
            "category": "WORKOUT",
            "start_date_local": f"{day.isoformat()}T00:00:00",
            "type": "Ride",
            "name": workout["name"],
            "filename": zwo.filename(workout["name"]),
            "file_contents": zwo.zwo(workout),
            "external_id": external_id,
        }
        r = await self._call(token, "POST", "/api/v1/athlete/0/events/bulk", params={"upsert": "true"}, json=[event])
        try:
            created = r.json()
            remote = str(created[0]["id"]) if created and created[0].get("id") is not None else None
        except (ValueError, LookupError, TypeError, AttributeError):
            remote = None
        return Delivered(remote_id=remote)

    async def delete(self, token: dict, external_id: str) -> None:
        await self._call(token, "PUT", "/api/v1/athlete/0/events/bulk-delete", json=[{"external_id": external_id}])

    async def revoke(self, token: dict) -> None:
        try:
            await self._call(token, "DELETE", "/api/v1/disconnect-app")
        except Exception:  # noqa: BLE001 - best effort; the token is deleted here either way
            pass
