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

from datetime import date

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


def can_approve(db: DbSession, user: User, athlete_id: int) -> bool:
    team = coaches(db, athlete_id)
    if user.id == athlete_id:
        return not team or user.plan_approval_off
    return any(c.id == user.id for c in team)


def role(user: User, athlete_id: int) -> str:
    return "athlete" if user.id == athlete_id else "coach"


def log(p: Plan, user: User, event: str, **extra) -> None:
    """Add to the plan's history (a new list, so SQLAlchemy sees the change)."""
    entry = {"at": utcnow().isoformat(timespec="seconds"), "by": user.display_name, "role": role(user, p.athlete_id)}
    p.history = [*(p.history or []), {**entry, "event": event, **{k: v for k, v in extra.items() if v}}]


def changes(current: list[dict], proposed: list[dict]) -> list[dict]:
    """Days a proposal changes, for the coach to review."""
    by_date = {d["date"]: d for w in proposed for d in w["days"]}
    fields = ("type", "description", "duration_min")
    out = []
    for w in current:
        for d in w["days"]:
            n = by_date.get(d["date"])
            if n and any(d.get(k) != n.get(k) for k in fields):
                out.append(
                    {"date": d["date"], "before": {k: d.get(k) for k in fields}, "after": {k: n.get(k) for k in fields}}
                )
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


def require_approver(db: DbSession, user: User, p: Plan) -> None:
    if not can_approve(db, user, p.athlete_id):
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
