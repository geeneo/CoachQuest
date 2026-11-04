"""Product news emails: an admin writes to users about new features (Admin → Email users).

Super admins write a subject and text (Markdown, sent as HTML and plain text; email_md.py), pick who gets it (everyone,
users seen in the last 30 days, or coaches), send a test to themselves, then send. It goes to active,
approved users who haven't switched news off (Profile, `notify_news`) and whose emails an admin
hasn't stopped (`emails_disabled`). Sending runs in the background, one email at a time with a short
pause so the mail server isn't flooded, and each send is kept with how many went out.
"""

import asyncio
import logging
from datetime import timedelta
from html import escape

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import email_md, inactivity, mailer
from .config import settings
from .db import Grant, NewsEmail, SessionLocal, User, utcnow

log = logging.getLogger("coachquest.news_email")

AUDIENCES = {
    "all": "Everyone",
    "active30": "Used CoachQuest in the last 30 days",
    "coaches": "Coaches (with at least one athlete)",
}
PAUSE_S = 1.0  # between emails


def recipients(db: DbSession, audience: str) -> list[User]:
    users = db.scalars(
        select(User)
        .where(User.is_active, User.approved, User.emails_disabled.is_(False), User.notify_news)
        .order_by(User.id)
    ).all()
    if audience == "active30":
        since = utcnow() - timedelta(days=30)
        seen = inactivity.last_visits(db)
        users = [u for u in users if (seen.get(u.id) or u.created_at) >= since]
    elif audience == "coaches":
        coaches = set(db.scalars(select(Grant.coach_id).where(Grant.status == "active", Grant.role == "coach")).all())
        users = [u for u in users if u.id in coaches]
    return list(users)


def text(u: User, body: str) -> str:
    base = settings.public_base_url
    return (
        f"Hi {u.display_name},\n\n{email_md.to_text(body)}\n— CoachQuest\n{base}/\n\n"
        'You get this as a CoachQuest user. Don\'t want news emails? Untick "Email me CoachQuest news" '
        f"under Profile ({base}/profile), or reply to this email.\n"
    )


def html_body(u: User, subject: str, body: str) -> str:
    """The same email as HTML: the Markdown of the text (headings, lists, bold) laid out."""
    base = settings.public_base_url
    greeting = f'<p style="{email_md.TEXT};margin:0 0 14px">Hi {escape(u.display_name)},</p>'
    footer = (
        "You get this as a CoachQuest user. Don't want news emails? Untick <b>Email me CoachQuest news</b> under "
        f'<a href="{base}/profile" style="color:#6b7280">Profile</a>, or reply to this email.'
    )
    return email_md.page(subject, greeting + email_md.to_html(body), ("Open CoachQuest", f"{base}/"), footer)


async def send_one(u: User, subject: str, body: str) -> None:
    await mailer.send(u.email, subject, text(u, body), html_body(u, subject, body))


async def send_all(email_id: int) -> None:
    """Send a news email to its audience (run in the background)."""
    with SessionLocal() as db:
        e = db.get(NewsEmail, email_id)
        if e is None:
            return
        to = recipients(db, e.audience)
        e.recipients = len(to)
        db.commit()
        for i, u in enumerate(to):
            try:
                await send_one(u, e.subject, e.body)
                e.sent += 1
            except mailer.MailError as exc:
                log.warning("News email %s to user %s not sent: %s", e.id, u.id, exc)
                e.failed += 1
            if i % 10 == 9:
                db.commit()  # progress for the admin page
            await asyncio.sleep(PAUSE_S)
        e.status, e.finished_at = "sent", utcnow()
        db.commit()
        log.info("News email %s: %s sent, %s failed", e.id, e.sent, e.failed)


def out(e: NewsEmail, db: DbSession) -> dict:
    by = db.get(User, e.created_by) if e.created_by else None
    return {
        "id": e.id,
        "subject": e.subject,
        "body": e.body,
        "audience": e.audience,
        "audience_label": AUDIENCES.get(e.audience, e.audience),
        "by": by.display_name if by else None,
        "created_at": e.created_at,
        "status": e.status,
        "recipients": e.recipients,
        "sent": e.sent,
        "failed": e.failed,
        "finished_at": e.finished_at,
    }
