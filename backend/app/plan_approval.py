"""Coach approval for plans the AI writes, so a human coach stays in charge.

When an athlete who has a coach (an active share with the plans scope) asks
the AI coach for a plan, the plan waits for a coach ("awaiting") and puts
nothing on the calendar, so nothing goes to Zwift or MyWhoosh. When they ask
for a re-plan of an approved plan, the new weeks wait as a proposal (`pending`)
and the plan they follow stays as it is. A coach approves, or sends it back
with a note (saved as a plan comment, so the next re-plan reads it).

Plans and re-plans a coach asks for are approved at once: the coach is the one
deciding. An athlete without a coach is never asked to wait. If the last coach
stops sharing, or a coach (or an admin) switches approval off for the athlete
(`User.plan_approval_off`), the athlete's plans apply at once and they can
approve their own waiting ones.
"""

from datetime import date, datetime, timedelta

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import plan_tracker
from .db import Grant, Plan, User, utcnow
from .notifications import notify

APPROVED, AWAITING, SENT_BACK = "approved", "awaiting", "sent_back"


def coaches(db: DbSession, athlete_id: int) -> list[User]:
    """Coaches who may approve: active shares with the plans scope."""
    ids = {
        g.coach_id
        for g in db.scalars(select(Grant).where(Grant.athlete_id == athlete_id, Grant.status == "active"))
        if "plans" in (g.scopes or [])
    }
    return list(db.scalars(select(User).where(User.id.in_(ids), User.is_active.is_(True)))) if ids else []


def required(db: DbSession, athlete: User) -> bool:
    """Do plans this athlete asks for wait for a coach? Yes when they have one, unless switched off."""
    return not athlete.plan_approval_off and bool(coaches(db, athlete.id))


def needs_approval(db: DbSession, athlete_id: int, requester: User) -> bool:
    return requester.id == athlete_id and required(db, requester)


DEFAULT_WAIT_HOURS = 48
WAIT_CHOICES = (24, 48, 72, 0)  # 0 = never: only a coach decides


def wait_hours(athlete: User) -> int:
    return DEFAULT_WAIT_HOURS if athlete.approval_wait_hours is None else athlete.approval_wait_hours


def waiting_since(p: Plan) -> datetime | None:
    """When the waiting proposal (or the waiting plan) was made."""
    if p.pending and p.pending.get("at"):
        return datetime.fromisoformat(p.pending["at"])
    if p.approval == AWAITING:
        made = [h for h in (p.history or []) if h.get("event") in ("created", "replanned")]
        return datetime.fromisoformat(made[-1]["at"]) if made else None
    return None


def first_day(p: Plan) -> date | None:
    """The first day the waiting change touches."""
    if p.pending:
        dates = [c["date"] for c in p.pending.get("changes") or []]
        return date.fromisoformat(min(dates)) if dates else None
    return p.start_date


def athlete_may_decide_at(p: Plan, athlete: User) -> datetime | None:
    """From when the athlete may approve or send back what waits for a coach (None: only a coach).

    After the coach's waiting time; at once when the change starts before that time is up (e.g. tomorrow's
    session), so a slow answer never blocks training."""
    since, hours = waiting_since(p), wait_hours(athlete)
    if since is None or hours == 0:
        return None
    deadline = since + timedelta(hours=hours)
    first = first_day(p)
    if first is not None and first <= deadline.date():
        return since
    return deadline


def can_approve(db: DbSession, user: User, athlete_id: int, p: Plan | None = None) -> bool:
    team = coaches(db, athlete_id)
    if user.id == athlete_id:
        if not team or user.plan_approval_off:
            return True
        at = athlete_may_decide_at(p, user) if p is not None else None
        return at is not None and utcnow() >= at
    return any(c.id == user.id for c in team)


def remind_coaches(db: DbSession, background: BackgroundTasks | None = None) -> int:
    """Hourly: halfway through the waiting time, remind the coaches once. Returns reminders sent."""
    sent = 0
    now = utcnow()
    for p in db.scalars(select(Plan).where((Plan.approval == AWAITING) | Plan.pending.is_not(None))):
        athlete = db.get(User, p.athlete_id)
        since, hours = waiting_since(p), wait_hours(athlete) if athlete else 0
        if not since or not hours or not athlete.is_active or now < since + timedelta(hours=hours / 2):
            continue
        if any(h.get("event") == "reminded" and h.get("at", "") >= since.isoformat() for h in p.history or []):
            continue
        tasks = background or BackgroundTasks()
        for c in coaches(db, p.athlete_id):
            notify(
                tasks,
                c,
                f"Reminder: {athlete.display_name}'s plan waits for your approval",
                f'{athlete.display_name}\'s "{p.title}" still waits for a coach. If no coach answers within '
                f"{hours} hours of the request, {athlete.display_name} may approve it themselves.",
                ("the plan", f"/athletes/{p.athlete_id}/plans/{p.id}"),
                setting="notify_comments",
            )
        p.history = [
            *(p.history or []),
            {"at": now.isoformat(timespec="seconds"), "by": "CoachQuest", "role": "reminder", "event": "reminded"},
        ]
        db.commit()
        sent += 1
    return sent


def role(user: User, athlete_id: int) -> str:
    return "athlete" if user.id == athlete_id else "coach"


def log(p: Plan, user: User, event: str, **extra) -> None:
    """Add to the plan's history (a new list, so SQLAlchemy sees the change)."""
    entry = {"at": utcnow().isoformat(timespec="seconds"), "by": user.display_name, "role": role(user, p.athlete_id)}
    p.history = [*(p.history or []), {**entry, "event": event, **{k: v for k, v in extra.items() if v}}]


FIELDS = ("type", "description", "duration_min", "extra_sessions")


def _shown(d: dict) -> dict:
    """A day as the coach reviews it: all its sessions in one line ("Zwift / indoor + Strength")."""
    sessions = [d, *plan_tracker.extras(d)]
    return {
        "type": " + ".join(s.get("type") or "" for s in sessions),
        "description": " · ".join(s.get("description") or "" for s in sessions if s.get("description")),
        "duration_min": plan_tracker.day_minutes(d),
    }


def _differs(a: dict, b: dict) -> bool:
    return any((a.get(k) or None) != (b.get(k) or None) for k in FIELDS)


def changes(current: list[dict], proposed: list[dict]) -> list[dict]:
    """Days a proposal changes, for the coach to review."""
    by_date = {d["date"]: d for w in proposed for d in w["days"]}
    out = []
    for w in current:
        for d in w["days"]:
            n = by_date.get(d["date"])
            if n and _differs(d, n):
                out.append({"date": d["date"], "before": _shown(d), "after": _shown(n)})
    return out


def propose(p: Plan, user: User, fresh: list[dict], summary: str, model: str, today: date, **why) -> dict:
    """Keep a re-plan as a proposal: the current weeks stay until a coach approves."""
    preview = [dict(w, days=[dict(d) for d in w["days"]]) for w in (p.weeks or [])]
    changed = plan_tracker.merge_replan(preview, fresh, today)
    p.pending = {
        "fresh": fresh,
        "summary": summary,
        "model": model,
        "by": user.display_name,
        "at": utcnow().isoformat(timespec="seconds"),
        "changed": changed,
        "changes": changes(p.weeks or [], preview),
        **{k: v for k, v in why.items() if v},
    }
    log(p, user, "replan_proposed", **why)
    return p.pending


def propose_day(p: Plan, user: User, date_iso: str, new: dict, why: str, model: str, **reasons) -> dict:
    """A one-day re-plan, shown next to the current day; applied when approved (see plans.approve)."""
    current = next(d for w in p.weeks for d in w["days"] if d["date"] == date_iso)
    p.pending = {
        "day_patch": {"date": date_iso, **new},
        "summary": why,
        "model": model,
        "by": user.display_name,
        "at": utcnow().isoformat(timespec="seconds"),
        "changed": 1,
        "changes": [{"date": date_iso, "before": _shown(current), "after": _shown(new)}],
        **{k: v for k, v in reasons.items() if v},
    }
    log(p, user, "day_proposed", day=date_iso, **reasons)
    return p.pending


def require_approver(db: DbSession, user: User, p: Plan) -> None:
    if not can_approve(db, user, p.athlete_id, p):
        raise HTTPException(status_code=403, detail="Only the athlete's coach can approve or send back this plan")
    if p.approval == APPROVED and not p.pending:
        raise HTTPException(status_code=409, detail="Nothing is waiting for approval on this plan")


def ask_coaches(db: DbSession, background: BackgroundTasks, p: Plan, what: str) -> None:
    athlete = db.get(User, p.athlete_id)
    for c in coaches(db, p.athlete_id):
        notify(
            background,
            c,
            f"{athlete.display_name}'s {what} waits for your approval",
            f'{athlete.display_name} asked the AI coach for {what} ("{p.title}"). It goes to their calendar, '
            "Zwift and MyWhoosh only once a coach approves it. Open it to approve, edit or send it back.",
            ("the plan", f"/athletes/{p.athlete_id}/plans/{p.id}"),
            setting="notify_comments",
        )


def tell_athlete(db: DbSession, background: BackgroundTasks, p: Plan, coach: User, what: str) -> None:
    athlete = db.get(User, p.athlete_id)
    if athlete.id == coach.id:
        return
    notify(
        background,
        athlete,
        f'{coach.display_name} {what} "{p.title}"',
        f'{coach.display_name} {what} your plan "{p.title}".',
        ("the plan", f"/athletes/{p.athlete_id}/plans/{p.id}"),
        setting="notify_comments",
    )


async def remind_job() -> None:
    """Scheduler job (hourly)."""
    from .db import SessionLocal

    tasks = BackgroundTasks()
    with SessionLocal() as db:
        remind_coaches(db, tasks)
    await tasks()


def athlete_decided(db: DbSession, background: BackgroundTasks, p: Plan, athlete: User, what: str) -> str:
    """When the athlete decides instead of a coach: the note for the history, and the coaches are told."""
    note = f"by the athlete (no coach answer within {wait_hours(athlete)} h, or the day came first)"
    for c in coaches(db, p.athlete_id):
        notify(
            background,
            c,
            f'{athlete.display_name} {what} "{p.title}" without a coach',
            f'No coach answered in time, so {athlete.display_name} {what} "{p.title}" themselves. '
            "You can still re-plan or edit it.",
            ("the plan", f"/athletes/{p.athlete_id}/plans/{p.id}"),
            setting="notify_comments",
        )
    return note
