"""Taper mode for the morning readiness note: the last TAPER_DAYS days before a race.

Everything here is decided in code; the AI writes it up. For each day from today to the race: the
planned session as written, and a flag where it breaks a taper rule (strength in the last
NO_STRENGTH_DAYS days, long sessions in race week, too much time against a usual week). Then
race-morning fitness, fatigue and form if the plan is followed (the PMC carried forward with each
day's planned TSS), against the form a one-day race wants, and the go/no-go thresholds from the
athlete's own recovery baselines.
"""

import copy
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import plan_approval, plan_tracker, plan_workouts
from .db import Plan, Race
from .fitness import ATL_DAYS, CTL_DAYS
from .queries import activities_since, load_curve
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


def _refs(db: DbSession, athlete_id: int, start: date, end: date) -> dict[str, tuple[Plan, int, int]]:
    """Each date from start to end: (plan, week index, day index) in the newest approved plan that has it."""
    plans = db.scalars(
        select(Plan)
        .where(Plan.athlete_id == athlete_id, Plan.start_date.is_not(None), Plan.approval == plan_approval.APPROVED)
        .order_by(Plan.created_at.desc())
    ).all()
    out: dict[str, tuple[Plan, int, int]] = {}
    for p in plans:
        for wi, w in enumerate(p.weeks or []):
            for di, d in enumerate(w.get("days") or []):
                if start.isoformat() <= d["date"] <= end.isoformat():
                    out.setdefault(d["date"], (p, wi, di))
    return out


def plan_days(db: DbSession, athlete_id: int, start: date, end: date) -> dict[str, dict]:
    """Each date from start to end with its day in the newest approved plan that has it."""
    return {k: p.weeks[wi]["days"][di] for k, (p, wi, di) in _refs(db, athlete_id, start, end).items()}


# "Make these changes": the flags as edits to the plan, worked out in code.
SHORTENED = " (Shortened for the taper.)"
MIN_SESSION = 30  # a session isn't cut shorter than this
UNSHORTENABLE = {"Rest", "Race", "Strength", "Yoga / mobility"}


def _drop_strength(d: dict) -> None:
    """No strength in the last NO_STRENGTH_DAYS days: drop it; an extra session takes the main one's place."""
    extras = [e for e in plan_tracker.extras(d) if e["type"] != "Strength"]
    if d["type"] == "Strength":
        if extras:
            main = extras.pop(0)
            for k in ("type", "description", "duration_min", "intensity", "segment_id", "strength"):
                d[k] = main.get(k)
        else:
            d.update(type="Rest", description="Rest: strength dropped for the taper.", duration_min=0, intensity=[])
            d["strength"] = d["segment_id"] = None
        d["workout"] = None
    d["extra_sessions"] = extras


def _shorten(d: dict, minutes: int) -> bool:
    minutes = max(MIN_SESSION, int(round(minutes / 5) * 5))
    if minutes >= (d.get("duration_min") or 0):
        return False
    d["duration_min"] = minutes
    if SHORTENED.strip() not in (d.get("description") or ""):
        d["description"] = ((d.get("description") or "").rstrip() + SHORTENED).strip()
    return True


def _adjustable(d: dict) -> bool:
    return (
        not d.get("locked")
        and d["type"] not in UNSHORTENABLE
        and not (d.get("workout") or {}).get("steps")  # a structured workout keeps its own length
        and (d.get("duration_min") or 0) > MIN_SESSION
    )


def proposed(db: DbSession, athlete_id: int, race: Race, today: date) -> list[dict]:
    """The plan days the taper rules change, each with its plan reference, the new day and why."""
    race_day = race.target_date
    refs = _refs(db, athlete_id, today, race_day - timedelta(days=1))
    days = {iso: copy.deepcopy(p.weeks[wi]["days"][di]) for iso, (p, wi, di) in refs.items()}
    why: dict[str, list[str]] = {}
    race_week_start = race_day - timedelta(days=6)
    for iso in sorted(days):
        d, day = days[iso], date.fromisoformat(iso)
        if d.get("locked") or d["type"] == "Race":
            continue
        to_go = (race_day - day).days
        if to_go <= NO_STRENGTH_DAYS and "Strength" in _types(d):
            _drop_strength(d)
            why.setdefault(iso, []).append(f"no strength {to_go} days before the race")
        if day >= race_week_start and plan_tracker.day_minutes(d) > RACE_WEEK_LONGEST_MIN and _adjustable(d):
            others = plan_tracker.day_minutes(d) - (d.get("duration_min") or 0)
            if _shorten(d, RACE_WEEK_LONGEST_MIN - others):
                why.setdefault(iso, []).append(f"at most {RACE_WEEK_LONGEST_MIN} min in race week")
    usual = usual_week_minutes(db, athlete_id, today)
    for first, last, share in (
        (race_day - timedelta(days=13), race_day - timedelta(days=7), TAPER_WEEK_SHARE),
        (race_week_start, race_day - timedelta(days=1), RACE_WEEK_SHARE),
    ):
        if first < today or not usual:
            continue
        window = [iso for iso in sorted(days) if first.isoformat() <= iso <= last.isoformat()]
        total = sum(plan_tracker.day_minutes(days[iso]) for iso in window)
        target = share * usual
        cut = [iso for iso in window if _adjustable(days[iso])]
        flexible = sum(days[iso]["duration_min"] for iso in cut)
        if total <= target or not flexible:
            continue
        factor = max(0.0, target - (total - flexible)) / flexible
        for iso in cut:
            if _shorten(days[iso], days[iso]["duration_min"] * factor):
                why.setdefault(iso, []).append(f"about {round(target)} min that week against a usual {usual}")
    out = []
    for iso in sorted(why):
        p, wi, di = refs[iso]
        before, after = p.weeks[wi]["days"][di], days[iso]
        out.append(
            {
                "date": iso,
                "label": label(date.fromisoformat(iso)),
                "why": "; ".join(why[iso]),
                "before": _session(before),
                "after": _session(after),
                "_ref": (p, wi, di),
                "_day": after,
            }
        )
    return out


def public(changes: list[dict]) -> list[dict]:
    return [{k: v for k, v in c.items() if not k.startswith("_")} for c in changes]


def apply(db: DbSession, athlete_id: int, race: Race, today: date) -> int:
    """Make the proposed changes in the plan(s); the calendar workouts follow. Returns the days changed."""
    changes = proposed(db, athlete_id, race, today)
    plans: dict[int, tuple[Plan, list]] = {}
    for c in changes:
        p, wi, di = c["_ref"]
        weeks = plans.setdefault(p.id, (p, copy.deepcopy(p.weeks)))[1]
        weeks[wi]["days"][di] = c["_day"]
    for p, weeks in plans.values():
        p.weeks = weeks
    db.commit()
    for p, _ in plans.values():
        plan_workouts.reconcile(db, p, today)
    return len(changes)


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


def _tss_with(tss: list[float], today: date, changes: list[dict]) -> list[float]:
    """The planned TSS per day from today, with the proposed changes made."""
    out = list(tss)
    for c in changes:
        i = (date.fromisoformat(c["date"]) - today).days
        if 0 <= i < len(out):
            out[i] = plan_tracker.day_tss(c["_day"])
    return out


def race_morning_form(db: DbSession, athlete_id: int, race: Race, today: date, changes: list[dict]):
    """Race-morning form (TSB) with the plan as it is, and with the proposed changes made."""
    curve, _ = load_curve(db, athlete_id, 2, today)
    plan = plan_days(db, athlete_id, today, race.target_date)
    tss = []
    for i in range((race.target_date - today).days):
        d = plan.get((today + timedelta(days=i)).isoformat())
        tss.append(plan_tracker.day_tss(d) if d else 0)
    if tss:
        tss[0] = max(tss[0], curve[-1].tss)
    start = (curve[-2].ctl, curve[-2].atl)
    return project(*start, tss)["tsb"], project(*start, _tss_with(tss, today, changes))["tsb"]


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
    changes = proposed(db, athlete_id, race, today)
    if changes:
        out["plan_changes"] = [
            {"label": c["label"], "why": c["why"], "after": f"{c['after']['planned']}, {c['after']['minutes']} min"}
            for c in changes
        ]
    if yesterday is not None:
        p = project(*yesterday, tss)
        out["projection"] = {"race_morning": p, "with_the_plan_as_it_is": True}
        if changes:
            out["projection_with_changes"] = {"race_morning": project(*yesterday, _tss_with(tss, today, changes))}
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


PROJECT_DAYS = 14  # how far the chart looks ahead without a race coming
PROJECT_TO_RACE_DAYS = 56  # up to a race this close


def projection(db: DbSession, athlete_id: int, today: date) -> list[dict]:
    """Fitness, fatigue and form from today on if the plan is followed (the planned sessions' TSS), as
    TrainingPeaks projects its chart: up to the next race when it's within PROJECT_TO_RACE_DAYS, else
    PROJECT_DAYS. Today counts what's logged, or what's planned when that's more."""
    race = next((r for r in upcoming(db, athlete_id, today) if r.target_date and r.target_date >= today), None)
    if race and (race.target_date - today).days <= PROJECT_TO_RACE_DAYS:
        end = race.target_date
    else:
        race, end = None, today + timedelta(days=PROJECT_DAYS)
    curve, _ = load_curve(db, athlete_id, 2, today)
    ctl, atl = curve[-2].ctl, curve[-2].atl
    done_today = curve[-1].tss
    plan = plan_days(db, athlete_id, today, end)
    out = []
    day = today
    while day <= end:
        d = plan.get(day.isoformat())
        planned = plan_tracker.day_tss(d) if d else 0
        tss = max(done_today, planned) if day == today else planned
        tsb = ctl - atl
        ctl += (tss - ctl) / CTL_DAYS
        atl += (tss - atl) / ATL_DAYS
        row = {
            "day": day.isoformat(),
            "planned_tss": planned or None,
            "ctl": round(ctl, 1),
            "atl": round(atl, 1),
            "tsb": round(tsb, 1),
        }
        if race and day == race.target_date:
            row["race"] = race.name
        out.append(row)
        day += timedelta(days=1)
    return out
