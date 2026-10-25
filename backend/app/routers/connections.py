"""Link and unlink Strava and Garmin."""

import logging
import secrets
from datetime import date, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from .. import backfill, runtime, sync_options
from ..db import Activity, Connection, OAuthState, SessionLocal, User, UserStravaApp, WellnessDay, get_db, utcnow
from ..deps import current_user
from ..providers import garmin, strava
from ..security import encrypt_json

log = logging.getLogger("coachquest.connections")

router = APIRouter(prefix="/api/connections", tags=["connections"])

PROVIDERS = ("strava", "garmin")


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
    }


async def run_sync(conn_id: int) -> None:
    db = SessionLocal()
    try:
        conn = db.get(Connection, conn_id)
        if conn:
            await (strava.sync if conn.provider == "strava" else garmin.sync)(db, conn)
    finally:
        db.close()


@router.get("")
def list_connections(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    conns = db.scalars(select(Connection).where(Connection.user_id == user.id)).all()
    own = strava.own_app(db, user.id)
    return {
        "connections": [conn_out(c) for c in conns],
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
    if saved is None or saved.user_id != user.id or saved.created_at < utcnow() - timedelta(minutes=15):
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
    conn = db.scalar(select(Connection).where(Connection.user_id == user.id, Connection.provider == provider))
    if conn is None:
        raise HTTPException(status_code=404, detail="Not connected")
    if conn.last_sync_at and conn.last_sync_at > utcnow() - timedelta(minutes=5):
        raise HTTPException(
            status_code=429,
            detail="Already synced in the last 5 minutes. New activities will come in on the next sync.",
        )
    count = await (strava.sync if provider == "strava" else garmin.sync)(db, conn)
    return {"fetched": count, "connection": conn_out(conn)}


class SyncOptions(BaseModel):
    activities: bool | None = None
    wellness: bool | None = None


def _conn(db: DbSession, user: User, provider: str) -> Connection:
    conn = None
    if provider in PROVIDERS:
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
    conn = _conn(db, user, provider)
    current = sync_options.options(conn)
    changes = {k: v for k, v in body.model_dump(exclude_none=True).items() if k in current}
    if not changes:
        raise HTTPException(status_code=422, detail=f"{provider} supports: {', '.join(current)}")
    turned_on = any(v and not current[k] for k, v in changes.items())
    conn.options = {**current, **changes}
    if turned_on:
        # Start the next sync from scratch so the newly enabled data is backfilled.
        conn.last_sync_at = None
    db.commit()
    if turned_on:
        background.add_task(run_sync, conn.id)
    return conn_out(conn)


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
    conn = _conn(db, user, provider)
    if conn.backfill and conn.backfill.get("status") in ("running", "waiting"):
        raise HTTPException(status_code=409, detail="An import is already running for this connection")
    try:
        backfill.start(db, conn, body.since)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    background.add_task(backfill.run, conn.id)
    return conn_out(conn)


@router.post("/{provider}/refresh")
def refresh_activities(
    provider: str, background: BackgroundTasks, user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    """Re-download stored activities to fill in fields added since they were imported."""
    conn = _conn(db, user, provider)
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
    if kind == "weight":
        # Weight lives on the profile; clear it only if it came from this provider.
        if user.weight_source == provider:
            user.weight_kg = user.weight_source = user.weight_updated_at = None
            db.commit()
            return {"deleted": 1}
        return {"deleted": 0}
    if kind == "activities":
        result = db.execute(delete(Activity).where(Activity.user_id == user.id, Activity.source == provider))
    else:
        result = db.execute(delete(WellnessDay).where(WellnessDay.user_id == user.id))
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
            db.execute(delete(WellnessDay).where(WellnessDay.user_id == user.id))
    db.commit()
    return {"ok": True}
