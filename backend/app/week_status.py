"""'How is your week going?': the current plan week so far, checked in code (no AI call), so it's
up to date every time the AI coach tab opens.

Looks at the plan days up to today (today counts once something is logged): sessions done, missed
or partly done, time and TSS against what was planned so far, form (TSB), today's readiness note
against today's session, and the next race's target fitness. Gives a verdict and a short list of
points, each ok / warn / bad, and where the week ends if the rest goes as planned.
"""

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import localtime, plan_approval, plan_follow, plan_tracker
from .db import Assessment, Plan, User
from .queries import activities_since, load_curve
from .routers.races import upcoming

ON_TRACK = 0.85  # done share of the time planned so far
BEHIND = 0.6
HARD = 1.3  # TSS share of the planned so far that is "much harder than planned"
TIRED_TSB = -25
WEEKDAY = {"mon": "Mon", "tue": "Tue", "wed": "Wed", "thu": "Thu", "fri": "Fri", "sat": "Sat", "sun": "Sun"}


def _kind(session_type: str) -> str:
    return "indoor" if session_type == "Zwift / indoor" else session_type.lower()


def _hm(minutes: int) -> str:
    h, m = divmod(round(minutes), 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def current_week(db: DbSession, athlete: User, today: date) -> tuple[Plan, dict] | None:
    """The newest approved plan's week holding today, with each day's status and actuals."""
    plans = db.scalars(
        select(Plan)
        .where(Plan.athlete_id == athlete.id, Plan.start_date.is_not(None), Plan.approval == plan_approval.APPROVED)
        .order_by(Plan.created_at.desc())
    ).all()
    for p in plans:
        start = next((w["start"] for w in p.weeks or [] if w["start"] <= today.isoformat() < _plus7(w["start"])), None)
        if start is None:
            continue
        plan_follow.update(db, p, athlete, today)
        since = datetime.combine(date.fromisoformat(start) - timedelta(days=1), datetime.min.time())
        weeks = plan_tracker.with_actuals(
            p.weeks, activities_since(db, athlete.id, since), today, localtime.zone(athlete.timezone)
        )
        return p, next(w for w in weeks if w["start"] == start)
    return None


def _plus7(iso: str) -> str:
    return (date.fromisoformat(iso) + timedelta(days=7)).isoformat()


def status(db: DbSession, athlete: User, scopes: set[str], today: date | None = None) -> dict | None:
    today = today or localtime.today(athlete)
    found = current_week(db, athlete, today)
    if found is None:
        return None
    _, week = found
    days = week["days"]
    t = today.isoformat()
    # So far: the days before today, and today once something is logged (else it's still to come).
    so_far = [d for d in days if d["date"] < t or (d["date"] == t and d["actual"])]
    ahead = [d for d in days if d not in so_far]
    planned_min = sum(plan_tracker.day_minutes(d) for d in so_far)
    done_min = sum(d["actual"]["minutes"] for d in so_far if d["actual"])
    planned_tss = sum(d["planned_tss"] for d in so_far)
    done_tss = sum((d["actual"] or {}).get("tss") or 0 for d in so_far)
    sessions = [d for d in so_far if d["type"] != "Rest"]
    done = [d for d in sessions if d["status"] in ("goal_met", "partial")]
    missed = [d for d in sessions if d["status"] == "missed"]
    partial = [d for d in sessions if d["status"] == "partial"]
    points: list[dict] = []

    def add(level: str, text: str) -> None:
        points.append({"level": level, "text": text})

    # Sessions
    if sessions:
        explained = [d for d in missed if d.get("missed_reason")]
        unexplained = [d for d in missed if not d.get("missed_reason")]
        todays_open = any(d["date"] == t and d["type"] != "Rest" for d in ahead)  # today counts once logged
        text = f"{len(done)} of {len(sessions)} sessions done {'before today' if todays_open else 'so far'}"
        if unexplained:
            names = ", ".join(f"{WEEKDAY[d['weekday']]} {_kind(d['type'])}" for d in unexplained)
            add("bad" if len(unexplained) > 1 else "warn", f"{text}: missed {names}.")
        elif explained:
            names = ", ".join(f"{WEEKDAY[d['weekday']]} ({d['missed_reason']})" for d in explained)
            add("ok", f"{text}; missed {names}, which is explained.")
        else:
            add("ok", f"{text}.")
        if partial:
            add(
                "warn",
                "Cut short: "
                + ", ".join(
                    f"{WEEKDAY[d['weekday']]} ({d['actual']['minutes']} of {plan_tracker.day_minutes(d)} min)"
                    for d in partial
                )
                + ".",
            )
    # Time
    if planned_min:
        share = done_min / planned_min
        text = f"{_hm(done_min)} of the {_hm(planned_min)} planned so far ({round(share * 100)}%)"
        if share >= ON_TRACK:
            add("ok", f"Time: {text}.")
        elif share >= BEHIND:
            add("warn", f"Time: {text}, a little behind.")
        else:
            add("bad", f"Time: {text}, well behind: don't try to squeeze it all into the days left.")
    # Load
    if planned_tss and done_tss > HARD * planned_tss:
        phase = (week.get("phase") or "").lower()
        why = " In a peak or taper week, freshness matters more than extra load." if phase in ("peak", "taper") else ""
        add("warn", f"Load: {done_tss} TSS against ≈{planned_tss} planned so far, harder than planned.{why}")
    # Form and fitness
    curve = load_curve(db, athlete.id, 8, today)[0] if "fitness" in scopes else []
    if curve and curve[-1].ctl > 0:  # no load data at all: nothing to say about form or fitness
        now = curve[-1]
        tsb, ctl = round(now.tsb), round(now.ctl)
        if tsb < TIRED_TSB:
            add("bad", f"Form {tsb}: very tired. Make the next session easy, or rest, before anything hard.")
        elif tsb < -10:
            add("ok", f"Form {tsb}: tired in a productive way; sleep and fuel well.")
        else:
            add("ok", f"Form {tsb:+d}: fresh enough for the sessions ahead.")
        race = next((r for r in upcoming(db, athlete.id, today) if r.target_ctl), None)
        if race and race.target_date:
            to_go = (race.target_date - today).days
            gap = race.target_ctl - ctl
            if gap > 5 and to_go <= 21:
                add(
                    "warn",
                    f"{race.name} in {to_go} days: fitness {ctl} against the target {race.target_ctl}. Too close "
                    "to close the gap safely: arrive fresh rather than chase it.",
                )
            elif gap > 5:
                add("warn", f"{race.name} in {to_go} days: fitness {ctl}, target {race.target_ctl} ({gap} to go).")
            else:
                add("ok", f"{race.name} in {to_go} days: fitness {ctl}, on target ({race.target_ctl}).")
    # Today's readiness against today's session
    todays = next((d for d in days if d["date"] == t), None)
    note = db.scalar(
        select(Assessment)
        .where(Assessment.athlete_id == athlete.id, Assessment.kind == "daily", Assessment.period_start == today)
        .order_by(Assessment.created_at.desc())
        .limit(1)
    )
    if note and todays and todays["type"] != "Rest" and not todays["actual"] and note.verdict in ("easy", "rest"):
        add(
            "warn",
            f"Today's readiness says {note.verdict.upper()}, and the plan has {_kind(todays['type'])} "
            f"{_hm(plan_tracker.day_minutes(todays))}: keep it easy, or swap it with a later day.",
        )
    # Where the week ends if the rest goes as planned
    rest_min = sum(plan_tracker.day_minutes(d) for d in ahead)
    rest_tss = sum(d["planned_tss"] for d in ahead)
    left = [d for d in ahead if d["type"] != "Rest"]
    week_min = sum(plan_tracker.day_minutes(d) for d in days)
    projection = (
        f"If the {len(left)} session{'s' if len(left) != 1 else ''} left go as planned, the week ends at "
        f"{_hm(done_min + rest_min)} and about {done_tss + rest_tss} TSS (planned {_hm(week_min)})."
        if left
        else None
    )
    levels = [p["level"] for p in points]
    if "bad" in levels:
        verdict, headline = "off", "Off track"
    elif "warn" in levels:
        n = levels.count("warn")
        verdict, headline = "watch", f"Mostly on track: {n} thing{'s' if n != 1 else ''} to watch"
    else:
        verdict, headline = "on", "On track"
    return {"verdict": verdict, "headline": headline, "points": points, "projection": projection, "as_of": t}
