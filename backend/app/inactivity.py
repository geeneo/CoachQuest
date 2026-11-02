"""'We haven't seen you' emails: one friendly email to a user who hasn't used CoachQuest for a while.

Admin → Settings → Email switches it on (`inactivity_email`, off by default) and sets the days
(`inactivity_days`, default 30). A user gets it when their last visit (their newest session, or
sign-in) is that long ago, their account is active and approved, and neither their own switch
(Profile, `notify_inactivity`), an admin's per-user switch (`inactivity_emails`) nor the admin's
"emails to this user" switch is off. One email per absence: it goes again only after they've been
back and away again. The email says what's new since their last visit (activities synced, comments,
races coming up) and links back; at most BATCH a day, so the mail server isn't flooded.
"""

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from . import mailer, runtime
from .config import settings
from .db import Activity, AuthEvent, Comment, Race, SessionLocal, User, utcnow
from .db import Session as LoginSession

log = logging.getLogger("coachquest.inactivity")

BATCH = 50


def enabled() -> bool:
    return runtime.get("inactivity_email") == "on" and mailer.configured()


def days() -> int:
    try:
        return max(7, int(runtime.get("inactivity_days") or 30))
    except ValueError:
        return 30


def last_visits(db: DbSession) -> dict[int, datetime]:
    """Each user's last visit: their newest session, else their last sign-in."""
    seen: dict[int, datetime] = {}
    for uid, at in db.execute(
        select(LoginSession.user_id, func.max(LoginSession.last_seen_at)).group_by(LoginSession.user_id)
    ):
        seen[uid] = at
    for uid, at in db.execute(
        select(AuthEvent.user_id, func.max(AuthEvent.at))
        .where(AuthEvent.event == "login_ok")
        .group_by(AuthEvent.user_id)
    ):
        if uid is not None and at and (uid not in seen or at > seen[uid]):
            seen[uid] = at
    return seen


def due(db: DbSession, now: datetime | None = None) -> list[tuple[User, datetime]]:
    """Users the email should go to now, with their last visit, longest away first."""
    now = now or utcnow()
    cutoff = now - timedelta(days=days())
    visits = last_visits(db)
    out = []
    for u in db.scalars(
        select(User).where(
            User.is_active,
            User.approved,
            User.emails_disabled.is_(False),
            User.notify_inactivity,
            User.inactivity_emails,
        )
    ):
        last = visits.get(u.id) or u.created_at
        if last < cutoff and (u.inactivity_emailed_at is None or u.inactivity_emailed_at < last):
            out.append((u, last))
    return sorted(out, key=lambda x: x[1])


def message(db: DbSession, u: User, last: datetime, today: date | None = None) -> tuple[str, str]:
    """Subject and text: when they were last here, what's new since, and the way back."""
    today = today or date.today()
    away = (today - last.date()).days
    new_acts = db.scalar(
        select(func.count()).select_from(Activity).where(Activity.user_id == u.id, Activity.start_time > last)
    )
    new_comments = db.scalar(
        select(func.count())
        .select_from(Comment)
        .where(Comment.athlete_id == u.id, Comment.author_id != u.id, Comment.created_at > last)
    )
    races = db.scalars(
        select(Race)
        .where(Race.user_id == u.id, Race.active, Race.target_date >= today)
        .order_by(Race.target_date)
        .limit(2)
    ).all()
    news = []
    if new_acts:
        news.append(f"- {new_acts} activit{'y' if new_acts == 1 else 'ies'} synced from Strava or Garmin to look at")
    if new_comments:
        news.append(f"- {new_comments} new comment{'' if new_comments == 1 else 's'} on your training plan")
    for r in races:
        news.append(f"- {r.name}: {(r.target_date - today).days} days to go")
    base = settings.public_base_url
    text = (
        f"Hi {u.display_name},\n\n"
        f"We haven't seen you on CoachQuest since {last:%d %B} ({away} days ago)."
        + ("\n\nSince then:\n" + "\n".join(news) if news else "")
        + f"\n\nYour training, plan and AI coach are waiting: {base}/\n\n"
        'Don\'t want these reminders? Untick "Email me a reminder" under Profile '
        f"({base}/profile), or just reply to this email.\n"
    )
    return "We haven't seen you on CoachQuest for a while", text


async def run(now: datetime | None = None) -> int:
    """The daily job: email the users who are due (at most BATCH). Returns how many were sent."""
    if not enabled():
        return 0
    now = now or utcnow()
    sent = 0
    with SessionLocal() as db:
        for u, last in due(db, now)[:BATCH]:
            subject, text = message(db, u, last, now.date())
            try:
                await mailer.send(u.email, subject, text)
            except mailer.MailError as exc:
                log.warning("Inactivity email to user %s not sent: %s", u.id, exc)
                continue
            u.inactivity_emailed_at = now
            db.commit()
            sent += 1
    if sent:
        log.info("Sent %s inactivity emails", sent)
    return sent
