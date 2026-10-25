"""Emails about sharing: invitations, acceptances and changes.

Sent in the background after the request has finished, only when email is
set up and the recipient hasn't switched these off in Profile. A failed send
is logged, never shown to the person who triggered it.
"""

import logging

from fastapi import BackgroundTasks

from . import mailer
from .config import settings
from .db import User

log = logging.getLogger("coachquest.notifications")

SCOPE_NAMES = {
    "activities": "activities",
    "fitness": "fitness and load",
    "wellness": "wellness",
    "profile": "profile (FTP, heart rates, goal)",
    "weight": "weight",
    "plans": "training plans and the AI coach",
}


def scopes_text(scopes: list[str]) -> str:
    return ", ".join(SCOPE_NAMES.get(s, s) for s in scopes)


async def _send(to: str, subject: str, text: str) -> None:
    try:
        await mailer.send(to, subject, text)
    except mailer.MailError as exc:
        log.warning("Sharing email to %s not sent: %s", to, exc)


def notify(background: BackgroundTasks, to: User, subject: str, body: str) -> None:
    if not to.notify_sharing or not to.is_active or not mailer.configured():
        return
    text = (
        f"Hi {to.display_name},\n\n{body}\n\nOpen Sharing: {settings.public_base_url}/sharing\n\n"
        "You can turn these emails off in CoachQuest under Profile."
    )
    background.add_task(_send, to.email, f"CoachQuest: {subject}", text)
