"""CoachQuest API: app wiring, CSRF guard and the sync scheduler."""

import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from . import runtime
from .config import check_required, settings
from .db import Connection, SessionLocal, init_db
from .routers import admin, athletes, auth, connections, grants, plans
from .routers.connections import run_sync

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("coachquest")

scheduler = AsyncIOScheduler(timezone="UTC")


async def sync_all(provider: str) -> None:
    db = SessionLocal()
    try:
        ids = db.scalars(select(Connection.id).where(Connection.provider == provider)).all()
    finally:
        db.close()
    log.info("Scheduled %s sync for %d connections", provider, len(ids))
    for conn_id in ids:
        await run_sync(conn_id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    check_required()
    init_db()
    with SessionLocal() as db:
        runtime.load(db)
    if settings.enable_scheduler:
        scheduler.add_job(sync_all, "interval", hours=6, args=["strava"], id="strava")
        scheduler.add_job(sync_all, "cron", hour="6,18", minute=15, args=["garmin"], id="garmin")
        scheduler.start()
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(title="CoachQuest", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def csrf_guard(request: Request, call_next):
    """State-changing API calls must carry a custom header.

    Browsers can't add custom headers to cross-site form posts, and a
    cross-site fetch with one needs a CORS preflight that we never grant.
    """
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path.startswith("/api/"):
        if request.headers.get("x-requested-with") != "CoachQuest":
            return JSONResponse({"detail": "Missing X-Requested-With header"}, status_code=403)
    return await call_next(request)


for r in (admin.router, auth.router, auth.internal, connections.router, grants.router, athletes.router, plans.router):
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"ok": True}
