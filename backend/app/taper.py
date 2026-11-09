"""Taper mode for the morning readiness note: the last TAPER_DAYS days before a race.

Everything here is decided in code; the AI writes it up. For each day from today to the race: the
planned session as written, and a flag where it breaks a taper rule (strength in the last
NO_STRENGTH_DAYS days, long sessions in race week, too much time against a usual week). Then
race-morning fitness, fatigue and form if the plan is followed (the PMC carried forward with each
day's planned TSS), against the form a one-day race wants, and the go/no-go thresholds from the
athlete's own recovery baselines.
"""

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import plan_approval, plan_tracker
from .db import Plan, Race
from .fitness import ATL_DAYS, CTL_DAYS
from .queries import activities_since
from .routers.races import upcoming

TAPER_DAYS = 14
NO_STRENGTH_DAYS = 10  # no strength sessions this close to the race
RACE_WEEK_LONGEST_MIN = 90  # longest session in the six days before the race
RACE_WEEK_SHARE = 0.6  # race week's planned time against a usual week (the last four weeks)
TAPER_WEEK_SHARE = 0.85  # the week before race week
TARGET_FORM = (5, 15)  # race-morning form (TSB) for a one-day race
TIRED_TSB = -15  # in a taper, form under this makes the day easy (readiness_verdict)


def label(d: date) -> str:
    return f"{d:%a} {d.day} {d:%b}"


def race_ahead(db: DbSession, athlete_id: int, today: date) -> Race | None:
    """The next race when it's 1 to TAPER_DAYS days away (race day itself isn't a taper day)."""
    for r in upcoming(db, athlete_id, today):
        if r.target_date and 0 < (r.target_date - today).days <= TAPER_DAYS:
            return r
    return None


def plan_days(db: DbSession, athlete_id: int, start: date, end: date) -> dict[str, dict]:
    """Each date from start to end with its day in the newest approved plan that has it."""
    plans = db.scalars(
        select(Plan)
        .where(Plan.athlete_id == athlete_id, Plan.start_date.is_not(None), Plan.approval == plan_approval.APPROVED)
        .order_by(Plan.created_at.desc())
    ).all()
    out: dict[str, dict] = {}
    for p in plans:
        for w in p.weeks or []:
            for d in w.get("days") or []:
                if start.isoformat() <= d["date"] <= end.isoformat():
                    out.setdefault(d["date"], d)
    return out


def project(ctl: float, atl: float, tss_by_day: list[float]) -> dict:
    """CTL / ATL / TSB after the given days (TSB on the morning after: CTL - ATL)."""
    for tss in tss_by_day:
        ctl += (tss - ctl) / CTL_DAYS
        atl += (tss - atl) / ATL_DAYS
    return {"ctl": round(ctl, 1), "atl": round(atl, 1), "tsb": round(ctl - atl, 1)}


def _session(d: dict) -> dict:
    out = {
        "planned": " + ".join([d["type"], *(e["type"] for e in plan_tracker.extras(d))]),
        "minutes": plan_tracker.day_minutes(d),
    }
    if d.get("intensity"):
        out["intensity"] = d["intensity"]
    if d.get("description"):
        out["description"] = d["description"][:200]
    return out


def _types(d: dict) -> list[str]:
    return [d["type"], *(e["type"] for e in plan_tracker.extras(d))]


def usual_week_minutes(db: DbSession, athlete_id: int, today: date) -> int:
    """Average weekly training time over the four weeks before today."""
    since = datetime.combine(today - timedelta(days=28), datetime.min.time())
    acts = [a for a in activities_since(db, athlete_id, since) if a.start_time.date() < today]
    return round(sum(a.duration_s or 0 for a in acts) / 60 / 4)


def facts(
    db: DbSession,
    athlete_id: int,
    race: Race,
    today: date,
    yesterday: tuple[float, float] | None,
    today_tss: float,
    numbers: dict,
) -> dict:
    """The taper facts for the readiness note. `yesterday`: (CTL, ATL) at the end of yesterday;
    `today_tss`: what's logged today so far; `numbers`: readiness_verdict's numbers (baselines)."""
    race_day = race.target_date
    days_to_go = (race_day - today).days
    plan = plan_days(db, athlete_id, today, race_day)
    usual = usual_week_minutes(db, athlete_id, today)
    days, flags, tss = [], [], []
    race_week_start = race_day - timedelta(days=6)
    for i in range(days_to_go):
        day = today + timedelta(days=i)
        d = plan.get(day.isoformat())
        row = {"date": day.isoformat(), "label": label(day), **(_session(d) if d else {"planned": None})}
        days.append(row)
        planned = plan_tracker.day_tss(d) if d else 0
        tss.append(max(today_tss, planned) if i == 0 else planned)
        if not d:
            continue
        to_go = (race_day - day).days
        if "Strength" in _types(d) and to_go <= NO_STRENGTH_DAYS:
            flags.append(
                f"{row['label']}: strength {to_go} days before the race. Drop it (at most light upper body "
                "with no legs, and not in race week)."
            )
        if day >= race_week_start and row["minutes"] > RACE_WEEK_LONGEST_MIN:
            flags.append(
                f"{row['label']}: {row['minutes']} min in race week. Keep it to {RACE_WEEK_LONGEST_MIN} min or "
                "less, easy with a few short efforts."
            )
    for name, first, last, share in (
        ("The week before race week", race_day - timedelta(days=13), race_day - timedelta(days=7), TAPER_WEEK_SHARE),
        ("Race week", race_week_start, race_day - timedelta(days=1), RACE_WEEK_SHARE),
    ):
        if first < today or not usual:
            continue  # partly gone: only judged while it's all ahead
        minutes = sum(r["minutes"] or 0 for r in days if first.isoformat() <= r["date"] <= last.isoformat())
        if minutes > share * usual:
            flags.append(
                f"{name} ({label(first)} to {label(last)}) has {minutes} min planned against a usual "
                f"{usual} min a week: cut it to about {round(share * usual)} min, keeping the short efforts."
            )
    out = {
        "race": {
            "name": race.name,
            "date": race_day.isoformat(),
            "label": label(race_day),
            "days_to_go": days_to_go,
            "distance_km": race.distance_km,
            "elevation_m": race.elevation_m,
        },
        "days": days,
        "usual_week_minutes": usual,
        "target_form": {"from": TARGET_FORM[0], "to": TARGET_FORM[1]},
        "flags": flags,
    }
    if yesterday is not None:
        p = project(*yesterday, tss)
        out["projection"] = {"race_morning": p, "with_the_plan_as_it_is": True}
        if p["tsb"] < TARGET_FORM[0]:
            flags.append(
                f"With the plan as it is you'd start the race at form {p['tsb']:+.0f}, under the "
                f"{TARGET_FORM[0]:+d} to {TARGET_FORM[1]:+d} a race wants: make the flagged and the longest "
                "sessions shorter, or add a rest day."
            )
        elif p["tsb"] > TARGET_FORM[1] + 10:
            flags.append(
                f"With the plan as it is you'd start the race at form {p['tsb']:+.0f}, fresher than it needs: "
                "keep the short race-pace efforts so the legs stay sharp."
            )
    hrv, rhr = numbers.get("hrv_baseline"), numbers.get("resting_hr_baseline")
    go = {}
    if hrv:
        go["easy_if_hrv_below_ms"], go["rest_if_hrv_below_ms"] = round(0.93 * hrv), round(0.85 * hrv)
    if rhr:
        go["easy_if_resting_hr_above"], go["rest_if_resting_hr_above"] = round(rhr + 4), round(rhr + 7)
    if go:
        out["go_no_go"] = go
    return out
