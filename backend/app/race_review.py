"""After a race: how it went, set against earlier years, the weather, and other riders.

- The ride: the athlete's session on the race's day(s) that is most likely the race (one linked to the race,
  else one Strava marks as a race, else the one closest to the race's distance); the athlete can pick
  another. Its elapsed time (start to finish, stops included), moving time and stopped time.
- The post-race update (Race.result): the official time, positions, how it went, food, problems and what to
  do differently, and riders typed in to compare with.
- Earlier editions: the athlete's rides in earlier years within EDITION_WINDOW_DAYS of the race's date that
  follow the same line (or, without a line, are about as long), each with its numbers and the fitness
  (CTL) they started with.
- Segments: Strava's detail of each of these rides (one request each, kept: Activity.detail) gives the time
  on every Strava segment of the course, so the years can be set side by side, segment by segment.
- Weather: the wind (head, cross, tail), gusts, temperature and rain each ride had, from Open-Meteo's
  history at the hour each part of the line was ridden (weather.ride_weather).
- Other riders: athletes on CoachQuest who share their activities with this athlete and rode the same
  race (same day, same line), and riders the athlete typed in with their time. Strava's API doesn't give
  other athletes' rides or segment leaderboards, so these are the only sources.
"""

import logging
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import geo, localtime, race_stages, runtime, weather
from .activity_types import category, is_outdoor
from .db import AccessLog, Activity, Connection, Grant, Race, User, utcnow
from .fitness import RUNS, pmc, same_session
from .queries import activities_since, daily_load, history_start
from .race_estimate import format_time

log = logging.getLogger("coachquest.race_review")

EDITION_WINDOW_DAYS = 21  # an earlier edition is within three weeks of the race's date, a year (or more) back
MAX_YEARS = 8
# The same course: starts within 3 km, lengths within 15%, lines on average within 1 km (courses change a
# little from year to year; ride_routes.py is stricter for training routes).
START_M = 3000
LENGTH_SHARE = 0.15
GAP_M = 1000
SHAPE_POINTS = 40
DETAIL_RETRY = timedelta(hours=6)  # a failed detail request is tried again after this
# 2: each segment's place on the course (start_km) and when it started (offset_s). Older details are
# fetched again once (one Strava request per ride).
DETAIL_VERSION = 2
NEAR_LINE_M = 300  # a segment's start this close to the ride's line is on it
MAX_DETAIL_FETCHES = 6  # per review: the ride and up to five earlier editions
MAX_RIDER_DETAILS = 8  # other riders whose segment times are fetched (one request each, with their Strava)
RUN_DISCIPLINES = {"Run", "Trail run", "Ultra"}


# ---- the race's ride ----


def race_days(race: Race) -> list[date]:
    if race.target_date is None:
        return []
    last = race_stages.last_day(race) or race.target_date
    return [race.target_date + timedelta(days=i) for i in range((last - race.target_date).days + 1)]


def _fits(race: Race, a: Activity) -> bool:
    """A run for a running race, a ride for a cycling race; anything for multisport."""
    if race.discipline in RUN_DISCIPLINES:
        return category(a) in RUNS
    if race.discipline in ("Triathlon", "Duathlon", "Multisport", "Swim / open water", "Other"):
        return True
    return category(a) not in RUNS and category(a) not in ("Strength", "Yoga", "Walk", "Hike")


def candidates(db: DbSession, athlete: User, race: Race) -> list[Activity]:
    """The athlete's sessions on the race's day(s), one per session (copies from other sources left out)."""
    days = race_days(race)
    if not days:
        return []
    tz = localtime.zone(athlete.timezone)
    since = datetime.combine(days[0] - timedelta(days=1), datetime.min.time())
    acts = [a for a in activities_since(db, athlete.id, since) if localtime.local_date(a.start_time, tz) in days]
    return [a for a in acts if _fits(race, a)]


def pick_ride(race: Race, cands: list[Activity]) -> Activity | None:
    """The athlete's choice, else the one linked to the race, marked a race, or closest to its distance."""
    chosen = (race.result or {}).get("activity_id")
    for a in cands:
        if a.id == chosen:
            return a
    if not cands:
        return None
    km = race.distance_km

    def key(a: Activity):
        off = abs(a.distance_m / 1000 - km) / km if km else 0
        return (a.race_id != race.id, not a.is_race, off, -a.distance_m)

    return min(cands, key=key)


# ---- earlier editions ----


def _shape(encoded: str | None) -> list | None:
    pts = geo.decode(encoded) if encoded else []
    return geo.resample(pts, SHAPE_POINTS) if len(pts) >= 2 else None


def same_course(a: Activity, b: Activity) -> bool:
    """The same course: about as long, starting close, along the same line (when both have one)."""
    ka, kb = a.distance_m / 1000, b.distance_m / 1000
    if not ka or not kb or abs(ka - kb) > LENGTH_SHARE * max(ka, kb):
        return False
    sa, sb = _shape(a.polyline), _shape(b.polyline)
    if sa is None or sb is None:
        return True  # no line to go by: as long is all there is
    if geo.distance_m(sa[0], sb[0]) > START_M:
        return False
    fa, fb = geo.flat(sa), geo.flat(sb)
    return geo.mean_gap_within(fa, fb, GAP_M) and geo.mean_gap_within(fb, fa, GAP_M)


def editions(db: DbSession, athlete: User, race: Race, ride: Activity | None) -> list[Activity]:
    """The athlete's rides of this race in earlier years, newest first: one a year."""
    if race.target_date is None:
        return []
    tz = localtime.zone(athlete.timezone)
    earliest = race.target_date.replace(year=race.target_date.year - MAX_YEARS) - timedelta(days=EDITION_WINDOW_DAYS)
    rows = activities_since(db, athlete.id, datetime.combine(earliest, datetime.min.time()))
    by_year: dict[int, Activity] = {}
    for a in rows:
        day = localtime.local_date(a.start_time, tz)
        if day.year >= race.target_date.year or not _fits(race, a) or not is_outdoor(a):
            continue
        try:
            anniversary = race.target_date.replace(year=day.year)
        except ValueError:  # 29 February
            anniversary = race.target_date.replace(year=day.year, day=28)
        if abs((day - anniversary).days) > EDITION_WINDOW_DAYS:
            continue
        if a.race_id == race.id:
            ok = True
        elif ride is not None:
            ok = same_course(ride, a)
        else:
            km = race.distance_km
            ok = bool(km) and a.is_race and abs(a.distance_m / 1000 - km) <= LENGTH_SHARE * km
        if not ok:
            continue
        best = by_year.get(day.year)
        if (
            best is None
            or (a.race_id == race.id) > (best.race_id == race.id)
            or ((a.race_id == race.id) == (best.race_id == race.id) and a.is_race > best.is_race)
        ):
            by_year[day.year] = a
    return [by_year[y] for y in sorted(by_year, reverse=True)]


# ---- Strava's detail (segments, laps, temperature) ----


def _parse_time(v: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")) if v else None
    except ValueError:
        return None


def start_km(line: list, cum: list[float], latlng, share: float | None) -> float | None:
    """Where on the ride a segment starts, in km: the point of the line nearest its start. A course that
    passes the same place twice (start and finish together, laps) has several; the one at about the same
    share of the ride as the effort's start time is taken."""
    if not latlng or len(latlng) != 2 or len(line) < 2:
        return None
    p = (latlng[0], latlng[1])
    gaps = [geo.distance_m(p, q) for q in line]
    near = [i for i, g in enumerate(gaps) if g <= NEAR_LINE_M]
    if not near:
        return None
    total = cum[-1] or 1
    if share is None:
        i = min(near, key=lambda i: gaps[i])
    else:
        i = min(near, key=lambda i: (abs(cum[i] / total - share), gaps[i]))
    return round(cum[i] / 1000, 1)


def compact_detail(d: dict) -> dict:
    """What the review keeps of Strava's detailed activity."""
    m = d.get("map") or {}
    line = geo.decode(m.get("polyline") or m.get("summary_polyline"))
    cum = [0.0]
    for a, b in zip(line, line[1:], strict=False):
        cum.append(cum[-1] + geo.distance_m(a, b))
    begin = _parse_time(d.get("start_date"))
    elapsed = d.get("elapsed_time") or 0
    segs = []
    for e in d.get("segment_efforts") or []:
        seg = e.get("segment") or {}
        if not seg.get("id"):
            continue
        at = _parse_time(e.get("start_date"))
        offset = round((at - begin).total_seconds()) if at and begin else None
        share = offset / elapsed if offset is not None and elapsed else None
        segs.append(
            {
                "id": seg["id"],
                "name": (seg.get("name") or e.get("name") or "")[:120],
                "distance_m": round(seg.get("distance") or e.get("distance") or 0),
                "grade": seg.get("average_grade"),
                "climb": seg.get("climb_category") or 0,
                "elapsed_s": e.get("elapsed_time"),
                "moving_s": e.get("moving_time"),
                "start_index": e.get("start_index") or 0,
                "watts": round(e["average_watts"]) if e.get("average_watts") and e.get("device_watts") else None,
                "hr": round(e["average_heartrate"]) if e.get("average_heartrate") else None,
                "pr_rank": e.get("pr_rank"),
                "offset_s": offset,
                "start_km": start_km(line, cum, seg.get("start_latlng"), share),
            }
        )
    segs.sort(key=lambda s: s["start_index"])
    laps = [
        {
            "name": (lap.get("name") or "")[:60],
            "elapsed_s": lap.get("elapsed_time"),
            "moving_s": lap.get("moving_time"),
            "distance_m": round(lap.get("distance") or 0),
            "watts": round(lap["average_watts"]) if lap.get("average_watts") else None,
            "hr": round(lap["average_heartrate"]) if lap.get("average_heartrate") else None,
        }
        for lap in (d.get("laps") or [])[:100]
    ]
    return {
        "segments": segs,
        "laps": laps if len(laps) > 1 else [],
        "avg_temp": d.get("average_temp"),
        "elapsed_s": d.get("elapsed_time"),
        "moving_s": d.get("moving_time"),
        "fetched_at": utcnow().isoformat(),
        "v": DETAIL_VERSION,
    }


def strava_copy(db: DbSession, a: Activity) -> Activity | None:
    """The Strava copy of a session (itself when it came from Strava): Strava has the segments."""
    if a.source == "strava":
        return a
    near = db.scalars(
        select(Activity).where(
            Activity.user_id == a.user_id,
            Activity.source == "strava",
            Activity.start_time >= a.start_time - timedelta(hours=1),
            Activity.start_time <= a.start_time + timedelta(hours=1),
        )
    ).all()
    return next((x for x in near if same_session(a, x)), None)


def _due(a: Activity) -> bool:
    d = a.detail or {}
    if d.get("segments") is not None and not d.get("error") and d.get("v", 1) >= DETAIL_VERSION:
        return False
    tried = d.get("tried_at")
    return not tried or datetime.fromisoformat(tried) < utcnow() - DETAIL_RETRY


async def fill_details(db: DbSession, athlete_id: int, acts: list[Activity]) -> list[str]:
    """Fetch Strava's detail for the rides that don't have it yet (at most MAX_DETAIL_FETCHES). Returns
    notes for what couldn't be had; a failure never stops the review."""
    from .providers import strava

    copies = [c for c in (strava_copy(db, a) for a in acts) if c is not None]
    todo = [c for c in copies if _due(c)][:MAX_DETAIL_FETCHES]
    if not todo:
        return []
    conn = db.scalar(
        select(Connection).where(
            Connection.user_id == athlete_id, Connection.provider == "strava", Connection.status == "active"
        )
    )
    if conn is None:
        return ["Link Strava to see segment times (Connections)."]
    notes = []
    for c in todo:
        try:
            d = compact_detail(await strava.activity_detail(db, conn, c.external_id))
            c.detail = d
            if d.get("elapsed_s"):
                c.elapsed_s = int(d["elapsed_s"])
        except Exception as exc:  # rate limit, token, network, deleted on Strava
            log.warning("Strava detail for activity %s failed: %r", c.id, exc)
            c.detail = {**(c.detail or {}), "error": str(exc)[:200], "tried_at": utcnow().isoformat()}
            if not notes:
                notes.append("Strava didn't answer for some rides' segments; they're tried again later.")
    db.commit()
    return notes


async def fill_rider_details(db: DbSession, others: list[dict]) -> None:
    """Strava's detail of other riders' rides, each with their own Strava link (they share these rides with
    the viewer): their segment times for the table. Failures are left out quietly."""
    for o in others[:MAX_RIDER_DETAILS]:
        a = db.get(Activity, o["activity_id"])
        if a is not None:
            await fill_details(db, o["athlete_id"], [a])


def detail_of(db: DbSession, a: Activity) -> dict | None:
    c = strava_copy(db, a)
    d = c.detail if c is not None else None
    return d if d and d.get("segments") is not None else None


# ---- numbers ----


def ctl_before(db: DbSession, athlete_id: int, days: list[date]) -> dict[date, float]:
    """Fitness (CTL) at the end of the day before each of `days`."""
    if not days:
        return {}
    by_day = daily_load(db, athlete_id)
    first = history_start(by_day, min(days) - timedelta(days=1))
    curve = {p.day: p.ctl for p in pmc(by_day, first, max(days))}
    return {d: curve.get(d - timedelta(days=1), 0.0) for d in days}


def ride_stats(db: DbSession, a: Activity, tz, ctl: float | None = None) -> dict:
    copy = strava_copy(db, a)
    d = copy.detail if copy is not None and copy.detail and copy.detail.get("segments") is not None else None
    elapsed = a.elapsed_s or (d or {}).get("elapsed_s") or (copy.elapsed_s if copy else None)
    moving = a.duration_s or None
    km = a.distance_m / 1000
    local = a.start_time.replace(tzinfo=UTC).astimezone(tz)
    temp = (d or {}).get("avg_temp")
    return {
        "activity_id": a.id,
        "source": a.source,
        "external_id": a.external_id,
        "strava_id": copy.external_id if copy else None,
        "name": a.name,
        "date": local.date().isoformat(),
        "year": local.year,
        "start": local.strftime("%H:%M"),
        "distance_km": round(km, 1),
        "elevation_m": round(a.elevation_m or 0),
        "elapsed_s": elapsed,
        "moving_s": moving,
        "stopped_s": max(0, elapsed - moving) if elapsed and moving else None,
        "speed_moving": round(km / (moving / 3600), 1) if moving else None,
        "speed_elapsed": round(km / (elapsed / 3600), 1) if elapsed else None,
        "avg_power": round(a.avg_power) if a.avg_power else None,
        "norm_power": round(a.norm_power) if a.norm_power else None,
        "avg_hr": round(a.avg_hr) if a.avg_hr else None,
        "max_hr": round(a.max_hr) if a.max_hr else None,
        "tss": round(a.tss or 0),
        "kj": round(a.kilojoules) if a.kilojoules else None,
        "ctl_before": round(ctl, 1) if ctl is not None else None,
        "device_temp": round(temp) if temp is not None else None,
        "has_segments": d is not None,
        "has_line": bool(a.polyline or (copy.polyline if copy else None)),
    }


def segment_table(rows: list[tuple[str, dict | None]], riders: list[tuple[str, dict | None]] = ()) -> list[dict]:
    """Each Strava segment of the course, in course order (where it starts, then the shorter first), with
    the time, speed, power and heart rate on it in each of the athlete's rides ([(label, detail)], the race
    first) and each other rider's ([(label, detail)]: only on segments the athlete rode). The athlete's best
    year is marked; "vs best" is the race against their best earlier year."""
    order: list[int] = []
    info: dict[int, dict] = {}
    for _, d in rows:
        for s in (d or {}).get("segments") or []:
            if s["id"] not in info:
                info[s["id"]] = s
                order.append(s["id"])
    own = {label for label, _ in rows}
    out = []
    for sid in order:
        times = {}
        for label, d in [*rows, *riders]:
            efforts = [s for s in (d or {}).get("segments") or [] if s["id"] == sid]
            if efforts:  # ridden twice (a lap course): the faster one
                e = min(efforts, key=lambda s: s["elapsed_s"] or 1e9)
                secs = e["elapsed_s"]
                times[label] = {
                    "elapsed_s": secs,
                    "watts": e["watts"],
                    "hr": e["hr"],
                    "kmh": round(e["distance_m"] / secs * 3.6, 1) if secs and e["distance_m"] else None,
                }
        if len(times) < 1:
            continue
        valid = {k: v["elapsed_s"] for k, v in times.items() if v["elapsed_s"] and k in own}
        best = min(valid, key=valid.get) if valid else None
        first = rows[0][0]
        others = [v for k, v in valid.items() if k != first]
        s = info[sid]
        # Where it starts: on the race's own ride when it has it, else the first ride that does.
        at = [x.get("start_km") for _, d in rows for x in (d or {}).get("segments") or [] if x["id"] == sid]
        if not any(k in own for k in times):
            continue
        out.append(
            {
                "id": sid,
                "name": s["name"],
                "start_km": next((k for k in at if k is not None), None),
                "distance_m": s["distance_m"],
                "grade": s["grade"],
                "climb": s["climb"],
                "times": times,
                "best": best,
                # The race against the best earlier year: negative is faster.
                "vs_best_before": valid[first] - min(others) if first in valid and others else None,
            }
        )
    # Course order; segments without a place (older detail, off the line) keep theirs, after the rest.
    placed = sorted((r for r in out if r["start_km"] is not None), key=lambda r: (r["start_km"], r["distance_m"]))
    return placed + [r for r in out if r["start_km"] is None]


# ---- weather ----


async def weather_for(db: DbSession, a: Activity, today: date) -> dict | None:
    line = a.polyline or (strava_copy(db, a) or a).polyline
    if not line or not is_outdoor(a):
        return None
    minutes = round((a.elapsed_s or a.duration_s or 0) / 60)
    try:
        return await weather.ride_weather(line, a.start_time, minutes, today)
    except weather.WeatherError as exc:
        return {"error": str(exc)}


# ---- other riders ----


def admin_sees_all(viewer: User) -> bool:
    """An admin while admin_view_data is on: every athlete's data, read only (deps.allowed_scopes)."""
    return viewer.is_admin and runtime.get("admin_view_data") == "on"


def visible_riders(db: DbSession, viewer: User, owner: User) -> list[tuple[User, bool]]:
    """Athletes whose rides `viewer` may set beside `owner`'s race, and whether their post-race update too:
    an admin who sees all data, every active athlete (with their updates); the athlete themself, those who
    share their activities with them (their updates when they share their plans too, where races live).
    Anyone else (a coach looking at the athlete's race): none, as those athletes shared with the athlete."""
    if viewer.id != owner.id:
        if not admin_sees_all(viewer):
            return []
        users = db.scalars(select(User).where(User.id != owner.id, User.is_active)).all()
        return [(u, True) for u in users]
    grants = db.scalars(select(Grant).where(Grant.coach_id == viewer.id, Grant.status == "active")).all()
    out = []
    for g in grants:
        if "activities" not in (g.scopes or []):
            continue
        u = db.get(User, g.athlete_id)
        if u is not None and u.is_active:
            out.append((u, "plans" in (g.scopes or [])))
    return out


def post_race(race: Race | None) -> dict | None:
    """A race's post-race update as others see it (times formatted), or None without one."""
    res = dict((race.result if race else None) or {})
    res.pop("activity_id", None)
    res.pop("updated_at", None)
    if not res:
        return None
    res["official_time"] = format_time(res.get("official_s"))
    res["riders"] = [{**r, "time": format_time(r.get("time_s"))} for r in res.get("riders") or []]
    return res


def their_race(db: DbSession, u: User, days: list[date], a: Activity) -> Race | None:
    """The other athlete's own race entry for the same event: theirs on the same day(s), the one their ride
    is linked to first."""
    rows = db.scalars(select(Race).where(Race.user_id == u.id, Race.target_date.in_(days))).all()
    return next((r for r in rows if a.race_id == r.id or (r.result or {}).get("activity_id") == a.id), None) or (
        rows[0] if rows else None
    )


def other_riders(db: DbSession, viewer: User, owner: User, race: Race, ride: Activity | None) -> list[dict]:
    """Other athletes who rode the same race (the same day(s), the same course) that `viewer` may see, with
    their post-race update when they wrote one and `viewer` may read it (visible_riders)."""
    if ride is None:
        return []
    days = race_days(race)
    out = []
    for u, with_update in visible_riders(db, viewer, owner):
        tz = localtime.zone(u.timezone)
        since = datetime.combine(days[0] - timedelta(days=1), datetime.min.time())
        theirs = [
            a
            for a in activities_since(db, u.id, since)
            if localtime.local_date(a.start_time, tz) in days and _fits(race, a) and same_course(ride, a)
        ]
        if not theirs:
            continue
        a = min(theirs, key=lambda x: abs(x.distance_m - ride.distance_m))
        db.add(AccessLog(athlete_id=u.id, viewer_id=viewer.id, resource="activities"))
        stats = ride_stats(db, a, tz)
        row = {**stats, "ride_name": stats["name"], "athlete_id": u.id, "name": u.display_name}
        if with_update:
            r = their_race(db, u, days, a)
            update = post_race(r)
            if update:
                db.add(AccessLog(athlete_id=u.id, viewer_id=viewer.id, resource="plans"))
                row["post_race"] = update
                row["race_id"] = r.id
        out.append(row)
    if out:
        db.commit()
    return out


def all_reviews(db: DbSession, viewer: User, since: date, today: date, only_updates: bool) -> list[dict]:
    """Admin: every athlete's races from `since` to today with their post-race update, newest first. Each
    athlete listed is written to their access log."""
    rows = db.scalars(
        select(Race).where(Race.target_date.is_not(None), Race.target_date >= since, Race.target_date <= today)
    ).all()
    out, seen = [], set()
    for r in sorted(rows, key=lambda r: (r.target_date, r.id), reverse=True):
        u = db.get(User, r.user_id)
        if u is None or not u.is_active:
            continue
        update = post_race(r)
        if only_updates and not update:
            continue
        seen.add(u.id)
        out.append(
            {
                "athlete_id": u.id,
                "athlete": u.display_name,
                "race_id": r.id,
                "race": r.name,
                "date": r.target_date.isoformat(),
                "distance_km": r.distance_km,
                "target_time": format_time(r.target_seconds),
                "post_race": update,
            }
        )
    for uid in seen:
        db.add(AccessLog(athlete_id=uid, viewer_id=viewer.id, resource="plans"))
    db.commit()
    return out


def standings(me: dict | None, result: dict, others: list[dict], me_name: str = "You") -> list[dict]:
    """Everyone compared, fastest first, with the gap to the athlete: their official time when given, else
    the ride's elapsed time; other athletes' the same way; typed-in riders' own times."""
    rows = []
    if me is not None:
        t = result.get("official_s") or me.get("elapsed_s")
        if t:
            rows.append({"name": me_name, "time_s": t, "kind": "you", "category": result.get("category")})
    for o in others:
        t = (o.get("post_race") or {}).get("official_s") or o.get("elapsed_s")
        if t:
            cat = (o.get("post_race") or {}).get("category")
            rows.append(
                {"name": o["name"], "time_s": t, "kind": "athlete", "athlete_id": o["athlete_id"], "category": cat}
            )
    for r in result.get("riders") or []:
        if r.get("time_s"):
            rows.append({"name": r["name"], "time_s": r["time_s"], "kind": "typed", "category": r.get("category")})
    rows.sort(key=lambda r: r["time_s"])
    mine = next((r["time_s"] for r in rows if r["kind"] == "you"), None)
    for i, r in enumerate(rows, 1):
        r["place"] = i
        r["gap_s"] = r["time_s"] - mine if mine is not None else None
    return rows


# ---- for the AI coach ----


def recent_results(db: DbSession, athlete_id: int, today: date, days: int = 365) -> list[dict]:
    """Races of the last year with a post-race update: what the AI coach learns from them."""
    rows = db.scalars(
        select(Race).where(
            Race.user_id == athlete_id,
            Race.target_date.is_not(None),
            Race.target_date <= today,
            Race.target_date >= today - timedelta(days=days),
        )
    ).all()
    out = []
    for r in sorted(rows, key=lambda r: r.target_date, reverse=True):
        res = r.result or {}
        fields = {
            k: res.get(k)
            for k in RESULT_TEXT
            + ("official_s", "position", "field_size", "category", "category_position", "category_size", "feeling")
        }
        fields = {k: v for k, v in fields.items() if v not in (None, "")}
        if fields:
            out.append({"race": r.name, "date": r.target_date.isoformat(), **fields})
    return out


RESULT_TEXT = ("went_well", "went_badly", "nutrition", "problems", "next_time")

PROMPT_RULE = (
    "- `recent_race_results` are the athlete's own post-race notes on races of the last year: official time "
    "(`official_s`, seconds), positions, `feeling` (1-5), what went well and badly, food, problems and what to "
    "do differently (`next_time`). Build on them: if fuelling or pacing went wrong, plan for it (long rides that "
    "practise race food, a steadier start); don't repeat them back at length."
)
