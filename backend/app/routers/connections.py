"""Link and unlink Strava and Garmin (data sources) and Intervals.icu (workout delivery)."""

import logging
import secrets
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from .. import backfill, profile_sync, runtime, sync_engine, sync_options
from ..db import Activity, Connection, OAuthState, SessionLocal, User, UserStravaApp, WellnessDay, get_db, utcnow
from ..delivery import intervals_icu
from ..deps import current_user
from ..providers import garmin, strava
from ..providers import intervals_icu as intervals_import
from ..security import decrypt_json, encrypt_json

log = logging.getLogger("coachquest.connections")

router = APIRouter(prefix="/api/connections", tags=["connections"])

PROVIDERS = ("strava", "garmin")
# Data sources with import choices; Intervals.icu also receives workouts (see /intervals routes).
SOURCES = (*PROVIDERS, "intervals_icu")
SYNC = {"strava": strava.sync, "garmin": garmin.sync, "intervals_icu": intervals_import.sync}


def conn_out(conn: Connection) -> dict:
    return {
        "provider": conn.provider,
        "status": conn.status,
        "external_id": conn.external_id,
        "last_sync_at": conn.last_sync_at,
        "last_error": conn.last_error,
        "options": sync_options.options(conn),
        "backfill": backfill.state(conn),
        "created_at": conn.created_at,
        # What the athlete allowed on Intervals.icu (scope names only, never the token).
        **(
            {"scopes": (decrypt_json(conn.token_enc).get("scope") or "").split(",")}
            if conn.provider == "intervals_icu"
            else {}
        ),
    }


async def run_sync(conn_id: int) -> None:
    db = SessionLocal()
    try:
        conn = db.get(Connection, conn_id)
        if conn:
            await SYNC[conn.provider](db, conn)
    finally:
        db.close()


@router.get("")
def list_connections(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    conns = db.scalars(select(Connection).where(Connection.user_id == user.id, Connection.provider.in_(SOURCES))).all()
    own = strava.own_app(db, user.id)
    return {
        "connections": [conn_out(c) for c in conns],
        # The main activity source the athlete picked; None until they pick one.
        "activity_primary": sync_options.primary_source(db, user.id),
        "sources": sync_options.overview(conns, sync_options.primary_source(db, user.id)),
        "strava_configured": strava.app_for(db, user.id) is not None,
        "strava_app": {
            "own": own is not None,
            "client_id": own.client_id if own else None,
            "secret_hint": f"…{own.client_secret[-4:]}" if own else None,
            "server_available": strava.server_app() is not None,
            "callback_domain": strava.redirect_uri().split("://")[-1].split("/")[0],
        },
    }


class StravaAppIn(BaseModel):
    client_id: str
    client_secret: str


@router.put("/strava/app")
def set_strava_app(body: StravaAppIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """Use the user's own Strava API app instead of the server-wide one."""
    try:
        client_id = runtime.validate("strava_client_id", body.client_id)
        secret = runtime.validate("strava_client_secret", body.client_secret)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    row = db.get(UserStravaApp, user.id) or UserStravaApp(user_id=user.id)
    row.client_id, row.secret_enc, row.updated_at = client_id, encrypt_json({"v": secret}), utcnow()
    db.add(row)
    db.commit()
    return {"ok": True}


@router.delete("/strava/app")
def remove_strava_app(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    db.execute(delete(UserStravaApp).where(UserStravaApp.user_id == user.id))
    db.commit()
    return {"ok": True}


@router.post("/strava/authorize")
def strava_authorize(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    app = strava.app_for(db, user.id)
    if app is None:
        raise HTTPException(status_code=503, detail="Add your Strava API app first")
    db.execute(delete(OAuthState).where(OAuthState.created_at < utcnow() - timedelta(minutes=15)))
    state = secrets.token_urlsafe(24)
    db.add(OAuthState(state=state, user_id=user.id, provider="strava"))
    db.commit()
    return {"url": strava.authorize_url(state, app)}


@router.get("/strava/callback")
async def strava_callback(
    background: BackgroundTasks,
    state: str = "",
    code: str = "",
    scope: str = "",
    error: str = "",
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    saved = db.get(OAuthState, state) if state else None
    if (
        saved is None
        or saved.user_id != user.id
        or saved.provider != "strava"
        or saved.created_at < utcnow() - timedelta(minutes=15)
    ):
        return RedirectResponse("/connections?error=state", status_code=303)
    db.delete(saved)
    db.commit()
    if error or not code:
        return RedirectResponse("/connections?error=denied", status_code=303)
    try:
        conn = await strava.exchange_code(db, user, code, scope)
    except strava.StravaLinkError as exc:
        log.warning("Strava link failed for user %s: %s", user.id, exc)
        query = {"error": exc.reason, **({"detail": exc.public[:200]} if exc.public else {})}
        return RedirectResponse(f"/connections?{urlencode(query)}", status_code=303)
    except Exception as exc:
        log.exception("Strava link failed for user %s", user.id)
        query = {"error": "strava", "detail": f"Server error: {type(exc).__name__}: {str(exc)[:150]}"}
        return RedirectResponse(f"/connections?{urlencode(query)}", status_code=303)
    background.add_task(run_sync, conn.id)
    return RedirectResponse("/connections?connected=strava", status_code=303)


# ---- Intervals.icu (workout delivery, see delivery/intervals_icu.py) ----


@router.post("/intervals/authorize")
def intervals_authorize(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    if not intervals_icu.configured():
        raise HTTPException(status_code=503, detail="Intervals.icu isn't set up on this server yet (Admin > Settings)")
    db.execute(delete(OAuthState).where(OAuthState.created_at < utcnow() - timedelta(minutes=15)))
    state = secrets.token_urlsafe(24)
    db.add(OAuthState(state=state, user_id=user.id, provider="intervals_icu"))
    db.commit()
    return {"url": intervals_icu.authorize_url(state)}


@router.get("/intervals/callback")
async def intervals_callback(
    background: BackgroundTasks,
    state: str = "",
    code: str = "",
    error: str = "",
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    saved = db.get(OAuthState, state) if state else None
    if (
        saved is None
        or saved.user_id != user.id
        or saved.provider != "intervals_icu"
        or saved.created_at < utcnow() - timedelta(minutes=15)
    ):
        return RedirectResponse("/connections?error=state#platforms", status_code=303)
    db.delete(saved)
    db.commit()
    if error or not code:
        return RedirectResponse("/connections?error=intervals_denied#platforms", status_code=303)
    try:
        token = await intervals_icu.exchange_code(code)
    except intervals_icu.LinkError as exc:
        log.warning("Intervals.icu link failed for user %s: %s", user.id, exc)
        query = {"error": "intervals", "detail": str(exc)[:200]}
        return RedirectResponse(f"/connections?{urlencode(query)}#platforms", status_code=303)
    conn = db.scalar(select(Connection).where(Connection.user_id == user.id, Connection.provider == "intervals_icu"))
    if conn is None:
        conn = Connection(user_id=user.id, provider="intervals_icu", token_enc="")
        db.add(conn)
    if conn.external_id and token["athlete_id"] and conn.external_id != token["athlete_id"]:
        sync_engine.forget_sent(db, user.id, "intervals_icu")  # a different Intervals.icu account
    conn.external_id = token["athlete_id"] or None
    conn.token_enc = encrypt_json({"access_token": token["access_token"], "scope": token["scope"]})
    conn.status, conn.last_error = "active", None
    db.commit()
    if "intervals_icu" in sync_engine.auto_providers(db, user):
        sync_engine.send_upcoming(db, user, "intervals_icu", "reconnected")
        background.add_task(sync_engine.run_due)
    return RedirectResponse("/connections?connected=intervals#platforms", status_code=303)


@router.delete("/intervals")
async def intervals_unlink(purge: bool = False, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """Stop sending and importing. Workouts already on the Intervals.icu calendar stay there.
    With purge, activities and wellness imported from Intervals.icu are deleted here too."""
    conn = db.scalar(select(Connection).where(Connection.user_id == user.id, Connection.provider == "intervals_icu"))
    if conn is None:
        raise HTTPException(status_code=404, detail="Not connected")
    await intervals_icu.IntervalsIcu().revoke(decrypt_json(conn.token_enc))
    db.delete(conn)
    db.commit()
    sync_engine.disconnected(db, user.id, "intervals_icu")
    if purge:
        db.execute(delete(Activity).where(Activity.user_id == user.id, Activity.source == "intervals_icu"))
        db.execute(delete(WellnessDay).where(WellnessDay.user_id == user.id, WellnessDay.source == "intervals_icu"))
    prefs = dict(user.platform_prefs or {})
    prefs["auto"] = {**(prefs.get("auto") or {}), "intervals_icu": False}
    user.platform_prefs = prefs
    db.commit()
    return {"ok": True}


class GarminLogin(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=256)


class GarminMfa(BaseModel):
    code: str = Field(min_length=4, max_length=12)


async def _garmin_connected(background: BackgroundTasks, user: User, db: DbSession):
    conn = db.scalar(select(Connection).where(Connection.user_id == user.id, Connection.provider == "garmin"))
    background.add_task(run_sync, conn.id)
    return {"status": "connected"}


@router.post("/garmin")
async def garmin_link(
    body: GarminLogin,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    try:
        status = await garmin.start_link(db, user, body.email, body.password)
    except garmin.GarminLinkError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if status == "needs_mfa":
        return {"status": "needs_mfa"}
    return await _garmin_connected(background, user, db)


@router.post("/garmin/mfa")
async def garmin_mfa(
    body: GarminMfa,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    try:
        await garmin.finish_mfa(db, user, body.code.strip())
    except garmin.GarminLinkError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await _garmin_connected(background, user, db)


@router.post("/{provider}/sync")
async def sync_now(provider: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    return await sync_for(provider, user, db)


async def sync_for(provider: str, user: User, db: DbSession, force: bool = False) -> dict:
    """Import from a provider now. `force` (admins only) skips the 5-minute limit."""
    conn = _conn(db, user, provider, SOURCES)
    if provider == "intervals_icu":
        return await _intervals_sync_now(db, user, conn, force)
    last = conn.last_sync_at
    if not force and last and last > utcnow() - timedelta(minutes=5):
        raise HTTPException(
            status_code=429,
            detail="Already synced in the last 5 minutes. New activities will come in on the next sync.",
        )
    count = await SYNC[provider](db, conn)
    return {"fetched": count, "connection": conn_out(conn)}


async def _intervals_sync_now(db: DbSession, user: User, conn: Connection, force: bool = False) -> dict:
    """Send every workout from today on again (so Intervals.icu tells MyWhoosh / Zwift), then import."""
    pressed = (conn.options or {}).get("sync_now_at")
    if not force and pressed and datetime.fromisoformat(pressed) > utcnow() - timedelta(minutes=5):
        raise HTTPException(status_code=429, detail="Synced in the last 5 minutes. Try again in a few minutes.")
    conn.options = {**(conn.options or {}), "sync_now_at": utcnow().isoformat()}
    db.commit()
    workouts = None
    if "intervals_icu" in sync_engine.auto_providers(db, user):
        workouts = await sync_engine.resend_now(db, user, "intervals_icu")
    count = await SYNC["intervals_icu"](db, conn)
    db.refresh(conn)
    return {"fetched": count, "workouts": workouts, "connection": conn_out(conn)}


class SyncOptions(BaseModel):
    activities: bool | None = None
    wellness: bool | None = None
    weight: bool | None = None
    thresholds: bool | None = None
    birth_date: bool | None = None


def _conn(db: DbSession, user: User, provider: str, allowed: tuple = PROVIDERS) -> Connection:
    """The user's connection to a provider. Backfill and data tools exist for Strava and Garmin only."""
    conn = None
    if provider in allowed:
        conn = db.scalar(select(Connection).where(Connection.user_id == user.id, Connection.provider == provider))
    if conn is None:
        raise HTTPException(status_code=404, detail="Not connected")
    return conn


@router.patch("/{provider}/options")
def set_options(
    provider: str,
    body: SyncOptions,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """Choose what to import from this provider."""
    conn = _conn(db, user, provider, SOURCES)
    current = sync_options.options(conn)
    changes = {k: v for k, v in body.model_dump(exclude_none=True).items() if k in current}
    if not changes:
        raise HTTPException(status_code=422, detail=f"{provider} supports: {', '.join(current)}")
    turned_on = any(v and not current[k] for k, v in changes.items())
    conn.options = {**(conn.options or {}), **current, **changes}
    if turned_on:
        # Start the next sync from scratch so the newly enabled data is backfilled.
        conn.last_sync_at = None
    db.commit()
    if turned_on:
        background.add_task(run_sync, conn.id)
    return conn_out(conn)


class ActivitySource(BaseModel):
    provider: str


@router.put("/activity-source")
def set_activity_source(
    body: ActivitySource,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """Choose the main activity source. Other sources keep their own "also import activities" choice."""
    conn = _conn(db, user, body.provider, SOURCES)
    if conn.provider == "intervals_icu" and "ACTIVITY:READ" not in (decrypt_json(conn.token_enc).get("scope") or ""):
        raise HTTPException(
            status_code=409, detail="Intervals.icu wasn't allowed to share activities. Reconnect it and allow that."
        )
    was_on = sync_options.options(conn)["activities"]
    sync_options.set_primary(db, conn)
    if not was_on:
        conn.last_sync_at = None  # backfill its activities on the next sync
    db.commit()
    if not was_on:
        background.add_task(run_sync, conn.id)
    return {"activity_primary": conn.provider}


class WellnessSource(BaseModel):
    provider: str | None  # None: from none of them


@router.put("/wellness-source")
def set_wellness_source(
    body: WellnessSource,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """Sleep, HRV and resting heart rate from one app, so the same night isn't counted twice."""
    conns = db.scalars(select(Connection).where(Connection.user_id == user.id, Connection.provider.in_(SOURCES))).all()
    if body.provider is not None and body.provider not in sync_options.overview(conns, None)["wellness"]["choices"]:
        raise HTTPException(status_code=422, detail="Sleep and HRV can't come from that app (is it linked?)")
    for conn in sync_options.set_wellness(conns, body.provider):
        conn.last_sync_at = None  # import its wellness on the next sync
        background.add_task(run_sync, conn.id)
    db.commit()
    return sync_options.overview(conns, sync_options.primary_source(db, user.id))


class BackfillIn(BaseModel):
    since: date


@router.post("/{provider}/backfill")
def start_backfill(
    provider: str,
    body: BackfillIn,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """Import data older than what the first sync brought in."""
    return begin_backfill(db, _conn(db, user, provider), body.since, background)


def begin_backfill(db: DbSession, conn: Connection, since: date, background: BackgroundTasks) -> dict:
    """Shared with Admin → Users, which starts imports for a user."""
    if conn.backfill and conn.backfill.get("status") in ("running", "waiting"):
        raise HTTPException(status_code=409, detail="An import is already running for this connection")
    try:
        backfill.start(db, conn, since)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    background.add_task(backfill.run, conn.id)
    return conn_out(conn)


@router.post("/{provider}/refresh")
def refresh_activities(
    provider: str, background: BackgroundTasks, user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    """Re-download stored activities to fill in fields added since they were imported."""
    return begin_refresh(db, _conn(db, user, provider), background)


def begin_refresh(db: DbSession, conn: Connection, background: BackgroundTasks) -> dict:
    try:
        backfill.refresh(db, conn)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    background.add_task(backfill.run, conn.id)
    return conn_out(conn)


@router.delete("/{provider}/backfill")
def cancel_backfill(provider: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    conn = _conn(db, user, provider)
    backfill.cancel(db, conn)
    return conn_out(conn)


@router.delete("/{provider}/data/{kind}")
def delete_data(provider: str, kind: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """Delete already-imported data of one type from one provider."""
    if kind not in sync_options.KINDS.get(provider, ()):
        raise HTTPException(status_code=404, detail="Unknown data type")
    if kind == "birth_date":
        if (user.profile_sources or {}).get("birth_date", {}).get("source") == provider:
            user.birth_date = None
            db.commit()
            return {"deleted": 1}
        return {"deleted": 0}
    if kind == "weight":
        # Weight lives on the profile; clear it only if it came from this provider.
        if user.weight_source == provider:
            user.weight_kg = user.weight_source = user.weight_updated_at = None
            db.commit()
            return {"deleted": 1}
        return {"deleted": 0}
    if kind == "thresholds":
        # FTP, LTHR and max HR this provider filled in; values typed in by hand stay.
        sources = user.profile_sources or {}
        cleared = [f for f in profile_sync.THRESHOLDS if sources.get(f, {}).get("source") == provider]
        for f in cleared:
            setattr(user, f, None)
        db.commit()
        return {"deleted": len(cleared)}
    if kind == "activities":
        result = db.execute(delete(Activity).where(Activity.user_id == user.id, Activity.source == provider))
    else:
        result = db.execute(delete(WellnessDay).where(WellnessDay.user_id == user.id, WellnessDay.source == provider))
    db.commit()
    return {"deleted": result.rowcount}


@router.delete("/{provider}")
async def unlink(
    provider: str,
    purge: bool = False,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    if provider not in PROVIDERS:
        raise HTTPException(status_code=404)
    conn = db.scalar(select(Connection).where(Connection.user_id == user.id, Connection.provider == provider))
    if conn is None:
        raise HTTPException(status_code=404, detail="Not connected")
    if provider == "strava":
        await strava.deauthorize(conn)
    db.delete(conn)
    # Strava's API agreement requires deleting its data when the user disconnects.
    if purge or provider == "strava":
        db.execute(delete(Activity).where(Activity.user_id == user.id, Activity.source == provider))
        if provider == "garmin":
            db.execute(delete(WellnessDay).where(WellnessDay.user_id == user.id, WellnessDay.source == "garmin"))
    db.commit()
    return {"ok": True}
