"""Deleting accounts nobody uses, after two warnings (Admin → Settings → Accounts).

Off by default (`account_cleanup`). An account whose last visit (its newest session, or sign-in; else
when it was made) is `account_cleanup_months` ago (default 12) is deleted on that date, after:

- a warning email 30 days before ("your account will be deleted on <date>; sign in to keep it"),
- a final warning 7 days before.

Signing in is all it takes to keep it: the last visit moves, so the date moves and the warnings no
longer count (they were before the visit). An account is only deleted when both warnings went out
for this absence and the final one at least FINAL_DAYS ago, so a mail server that's down never
leads to a deletion without warning. Never deleted: admins, disabled or unapproved accounts, and
accounts an admin marked "Never delete" (`keep_account`). Deleting works as Admin → Users → Delete:
CoachQuest's access to Strava and Intervals.icu is revoked and the user is told by email.
"""

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import accounts, inactivity, mailer, runtime
from .config import settings
from .db import SessionLocal, User, utcnow

log = logging.getLogger("coachquest.account_cleanup")

FIRST_DAYS = 30
FINAL_DAYS = 7
BATCH = 50  # emails and deletions per run


def enabled() -> bool:
    return runtime.get("account_cleanup") == "on" and mailer.configured()


def months() -> int:
    try:
        return max(3, int(runtime.get("account_cleanup_months") or 12))
    except ValueError:
        return 12


def deletion_date(last_visit: datetime) -> date:
    """The day an account unused since `last_visit` is deleted (months of ~30.44 days)."""
    return (last_visit + timedelta(days=round(months() * 30.44))).date()


def candidates(db: DbSession) -> list[tuple[User, datetime]]:
    """Accounts this can ever apply to, with their last visit."""
    visits = inactivity.last_visits(db)
    users = db.scalars(
        select(User).where(User.is_active, User.approved, User.is_admin.is_(False), User.keep_account.is_(False))
    ).all()
    return [(u, visits.get(u.id) or u.created_at) for u in users]


def status(u: User, last: datetime) -> dict:
    """When the account is due, and the warnings sent for this absence. A first warning promises at
    least FIRST_DAYS (a late one, e.g. just after the setting was switched on, moves the date)."""
    warned = u.deletion_warned_at if u.deletion_warned_at and u.deletion_warned_at > last else None
    final = u.deletion_final_warned_at if u.deletion_final_warned_at and u.deletion_final_warned_at > last else None
    delete_on = deletion_date(last)
    if warned:
        delete_on = max(delete_on, warned.date() + timedelta(days=FIRST_DAYS))
    return {"delete_on": delete_on, "warned_at": warned, "final_warned_at": final}


def _warning(u: User, delete_on: date, final: bool) -> tuple[str, str]:
    base = settings.public_base_url
    subject = (
        "Final reminder: your CoachQuest account will be deleted"
        if final
        else "Your CoachQuest account will be deleted if it isn't used"
    )
    text = (
        f"Hi {u.display_name},\n\n"
        f"You haven't used CoachQuest for a long time, so your account and its data (activities, plans, "
        f"workouts, notes and links to other apps) will be deleted on {delete_on:%d %B %Y}.\n\n"
        f"To keep it, just sign in before then: {base}/\n\n"
        + ("This is the last reminder. " if final else "We'll remind you once more a week before. ")
        + "If you don't need it any more, you don't have to do anything. Questions? Reply to this email.\n"
    )
    return subject, text


async def run(now: datetime | None = None) -> dict:
    """The daily job: send warnings that are due, delete accounts whose time has come."""
    out = {"warned": 0, "final": 0, "deleted": 0}
    if not enabled():
        return out
    now = now or utcnow()
    today = now.date()
    done = 0
    with SessionLocal() as db:
        for u, last in candidates(db):
            if done >= BATCH:
                break
            st = status(u, last)
            delete_on = st["delete_on"]
            days_left = (delete_on - today).days
            if days_left > FIRST_DAYS:
                continue
            if st["warned_at"] is None:
                delete_on = max(delete_on, today + timedelta(days=FIRST_DAYS))
                field, final = "deletion_warned_at", False
            elif st["final_warned_at"] is None and days_left <= FINAL_DAYS:
                field, final = "deletion_final_warned_at", True
            elif (
                st["final_warned_at"] is not None
                and days_left <= 0
                and (now - st["final_warned_at"]).days >= FINAL_DAYS
            ):
                await _delete(db, u)
                out["deleted"] += 1
                done += 1
                continue
            else:
                continue
            if final:  # a final warning that comes late (mail was down) still gives a week
                delete_on = max(delete_on, today + timedelta(days=FINAL_DAYS))
            subject, text = _warning(u, delete_on, final)
            try:
                await mailer.send(u.email, subject, text)
            except mailer.MailError as exc:
                log.warning("Deletion warning to user %s not sent: %s", u.id, exc)
                continue
            setattr(u, field, now)
            db.commit()
            out["final" if final else "warned"] += 1
            done += 1
    if any(out.values()):
        log.info("Unused accounts: %s", out)
    return out


async def _delete(db: DbSession, u: User) -> None:
    email, name, uid = u.email, u.display_name, u.id
    await accounts.revoke_links(db, u)
    accounts.delete_account(db, u)
    log.info("Deleted unused account %s", uid)
    try:
        await mailer.send(
            email,
            "Your CoachQuest account has been deleted",
            f"Hi {name},\n\nAs we wrote before, your CoachQuest account wasn't used for {months()} months, so it "
            "and its data have been deleted. CoachQuest no longer has access to your Strava or Intervals.icu "
            "account. Copies in our backups are removed as the backups rotate out (within 14 days).\n\n"
            f"You're welcome back any time: {settings.public_base_url}/\n",
        )
    except mailer.MailError as exc:
        log.warning("Deletion notice to %s not sent: %s", uid, exc)
