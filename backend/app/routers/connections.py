"""Link and unlink Strava and Garmin."""

import secrets
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from .. import runtime
from ..db import Activity, Connection, OAuthState, SessionLocal, User, WellnessDay, get_db, utcnow
from ..deps import current_user
from ..providers import garmin, strava

router = APIRouter(prefix="/api/connections", tags=["connections"])

PROVIDERS = ("strava", "garmin")


def conn_out(conn: Connection) -> dict:
    return {
        "provider": conn.provider,
        "status": conn.status,
        "external_id": conn.external_id,
        "last_sync_at": conn.last_sync_at,
        "last_error": conn.last_error,
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
    return {
        "connections": [conn_out(c) for c in conns],
        "strava_configured": bool(runtime.get("strava_client_id") and runtime.get("strava_client_secret")),
    }


@router.post("/strava/authorize")
def strava_authorize(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    if not runtime.get("strava_client_id"):
        raise HTTPException(status_code=503, detail="Strava is not configured on this server")
    db.execute(delete(OAuthState).where(OAuthState.created_at < utcnow() - timedelta(minutes=15)))
    state = secrets.token_urlsafe(24)
    db.add(OAuthState(state=state, user_id=user.id, provider="strava"))
    db.commit()
    return {"url": strava.authorize_url(state)}


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
    except Exception:
        return RedirectResponse("/connections?error=strava", status_code=303)
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
        raise HTTPException(status_code=429, detail="Synced less than 5 minutes ago")
    count = await (strava.sync if provider == "strava" else garmin.sync)(db, conn)
    return {"fetched": count, "connection": conn_out(conn)}


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
