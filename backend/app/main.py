"""CoachQuest API: app wiring, CSRF guard and the sync scheduler."""

import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from . import (
    account_cleanup,
    accounts,
    assessments,
    auth_log,
    backfill,
    error_log,
    evening,
    hr_load,
    inactivity,
    morning,
    plan_approval,
    posts_seed,
    profile_sync,
    runtime,
    storage_watch,
    sync_engine,
)
from .config import check_required, settings
from .db import Connection, SessionLocal, User, init_db
from .deps import READ_REQUEST, current_user
from .routers import (
    admin,
    athlete_notes,
    athletes,
    auth,
    coach_ai,
    comments,
    connections,
    diagnostics,
    exercises,
    grants,
    health,
    instructions,
    load_audit,
    plans,
    posts,
    preferences,
    races,
    segments,
    weather,
    welcome,
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
    error_log.install()  # warnings and errors to Admin → Errors (after the tables exist)
    with SessionLocal() as db:
        runtime.load(db)
        accounts.promote_super_admins(db)
        posts_seed.seed(db)
        profile_sync.rescore_all_once(db)  # after a change in how TSS is scored
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
        scheduler.add_job(storage_watch.daily, "cron", hour=4, minute=10, id="storage-watch")
        scheduler.add_job(inactivity.run, "cron", hour=8, minute=25, id="inactivity-emails")  # 10:25 in SA
        scheduler.add_job(account_cleanup.run, "cron", hour=8, minute=35, id="account-cleanup")
        scheduler.add_job(plan_approval.remind_job, "cron", minute=5, id="approval-reminders")  # hourly
        # The morning note at each athlete's own time, once last night's sleep is in (morning.py).
        scheduler.add_job(morning.run, "interval", minutes=5, id="ai-daily")
        scheduler.add_job(evening.run, "interval", minutes=5, id="evening-preview")
        # Heart-rate zones for sessions without power (training load as TrainingPeaks' hrTSS), a few at a time.
        scheduler.add_job(hr_load.fill, "interval", minutes=10, id="hr-zones")
        scheduler.add_job(error_log.daily, "cron", hour=4, minute=45, id="problems-email")  # 06:45 in SA
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
    posts.router,
    segments.router,
    segments.shared_router,
    health.router,
    weather.router,
    welcome.public,
    welcome.admin,
    exercises.router,
    load_audit.router,
    diagnostics.router,
):
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/version")
def version(_: User = Depends(current_user)):
    """The API's build, for the page footer: a screenshot then says which version it shows."""
    return {"commit": settings.build_commit, "built": settings.build_time}
