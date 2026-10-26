"""CoachQuest API: app wiring, CSRF guard and the sync scheduler."""

import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from . import assessments, auth_log, backfill, plan_approval, runtime, sync_engine
from .config import check_required, settings
from .db import Connection, SessionLocal, User, init_db
from .deps import READ_REQUEST
from .routers import (
    admin,
    athlete_notes,
    athletes,
    auth,
    coach_ai,
    comments,
    connections,
    grants,
    instructions,
    plans,
    preferences,
    races,
    workouts,
)
from .routers.connections import run_sync

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("coachquest")

scheduler = AsyncIOScheduler(timezone="UTC")


async def sync_all(provider: str) -> None:
    db = SessionLocal()
    try:
        ids = db.scalars(
            select(Connection.id)
            .join(User, User.id == Connection.user_id)
            .where(Connection.provider == provider, User.is_active)  # paused or disabled accounts don't sync
        ).all()
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
            backfill.refresh_outdated(db)  # picked up by the backfill job below
    if settings.enable_scheduler:
        sync_engine.reset_stuck()
    if settings.enable_scheduler:
        scheduler.add_job(sync_all, "interval", hours=6, args=["strava"], id="strava")
        scheduler.add_job(sync_all, "cron", hour="6,18", minute=15, args=["garmin"], id="garmin")
        scheduler.add_job(sync_all, "interval", hours=6, args=["intervals_icu"], id="intervals_icu")
        scheduler.add_job(backfill.resume_due, "interval", minutes=15, id="backfill")
        scheduler.add_job(sync_engine.run_due, "interval", minutes=1, id="workout-sync")
        scheduler.add_job(auth_log.purge_job, "cron", hour=3, minute=20, id="log-retention")
        scheduler.add_job(plan_approval.remind_job, "cron", minute=5, id="approval-reminders")  # hourly
        # After the morning Garmin sync window, so last night's sleep and HRV are in.
        scheduler.add_job(assessments.run_scheduled, "cron", hour=6, minute=40, args=["daily"], id="ai-daily")
        # Runs daily; each athlete gets their review on the first day of their own week.
        scheduler.add_job(assessments.run_scheduled, "cron", hour=6, minute=50, args=["weekly"], id="ai-weekly")
        scheduler.start()
        scheduler.add_job(backfill.resume_due, id="backfill-now")  # once, right away
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
    # Admins may read any athlete's data but not change it (deps.allowed_scopes).
    READ_REQUEST.set(request.method in ("GET", "HEAD"))
    return await call_next(request)


for r in (
    admin.router,
    coach_ai.router,
    auth.router,
    auth.internal,
    connections.router,
    grants.router,
    athletes.router,
    plans.router,
    preferences.router,
    races.router,
    workouts.router,
    comments.router,
    instructions.router,
    athlete_notes.router,
):
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"ok": True}
