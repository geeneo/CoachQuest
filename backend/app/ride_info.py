"""More on a planned outdoor ride (Calendar): its numbers, food and drink, pacing and kit.

The numbers come from the day's route and the athlete's own rides on it (ride_routes.py): distance,
climbing, the speed they usually ride it at, and so a finish time from their usual start. Without a
route, their recent outdoor speed gives a rough distance for the planned time. Food, drink, pacing and
kit are rules of thumb from the length, the day's zones, FTP and the forecast (weather.py); general
guidance, not a prescription.
"""

import math
import re
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import ride_routes
from .activity_types import category, is_outdoor, is_ride
from .db import Activity, Segment

RECENT_RIDES = 20
BOTTLE_ML = 750
GEL_G = 25  # carbs in a gel (or a bar, roughly)

# Coggan power zones, as fractions of FTP.
ZONES = {"Z1": (0.0, 0.55), "Z2": (0.56, 0.75), "Z3": (0.76, 0.90), "Z4": (0.91, 1.05), "Z5": (1.06, 1.20)}


# Plan session types by how they move: each gets the athlete's own speed for that (recent_speed).
OUTDOOR_RIDES = {"Road", "Gravel", "MTB", "E-MTB", "Hill repeats"}
ON_FOOT = {"Outdoor run": "run", "Trail run": "run", "Walk": "walk", "Hike": "walk"}
# Without enough of the athlete's own walks or runs: a typical pace (km/h). Rides have no default.
DEFAULT_SPEED = {"walk": 5.0, "run": 10.0}
MIN_KM = {"ride": 5, "run": 2, "walk": 1}
SPEED_FROM = {"ride": "your recent outdoor rides", "run": "your recent runs", "walk": "your recent walks"}


def mode(session_type: str | None) -> str | None:
    """ "ride", "run" or "walk" for a plan session type; None when it doesn't move along a route."""
    if session_type in OUTDOOR_RIDES or session_type == "Race":
        return "ride"
    return ON_FOOT.get(session_type or "")


def _mode_of(a: Activity) -> str | None:
    if is_ride(a):
        return "ride" if is_outdoor(a) else None
    c = category(a)
    if c in ("Run", "Trail run"):
        return "run"
    if c in ("Walk", "Hike"):
        return "walk"
    return None


def recent_speed(db: DbSession, athlete_id: int, kind: str = "ride") -> float | None:
    """The athlete's average speed (km/h) over their last outdoor rides, runs or walks ("ride" / "run" /
    "walk"); for walks and runs a typical pace when they have none logged."""
    rows = db.scalars(
        select(Activity)
        .where(
            Activity.user_id == athlete_id,
            Activity.distance_m >= MIN_KM.get(kind, 5) * 1000,
            Activity.duration_s > 0,
        )
        .order_by(Activity.start_time.desc())
        .limit(RECENT_RIDES * 5)
    ).all()
    done = [a for a in rows if _mode_of(a) == kind][:RECENT_RIDES]
    seconds = sum(a.duration_s for a in done)
    if seconds:
        return round(sum(a.distance_m for a in done) / seconds * 3.6, 1)
    return DEFAULT_SPEED.get(kind)


def planned_distance(day: dict, speed: float | None) -> dict:
    """A plan day's planned km and climbing: its route's when it rides one, else roughly from the
    planned time at the athlete's usual outdoor speed (outdoor rides only). {} when there's nothing."""
    seg = day.get("segment")
    if seg and seg.get("kind") != "segment" and seg.get("distance_m"):
        return {
            "planned_km": round(seg["distance_m"] / 1000, 1),
            "planned_elevation_m": seg.get("elevation_m"),
            "planned_from": "route",
        }
    if day.get("type") in OUTDOOR_RIDES and day.get("duration_min") and speed:  # `speed`: the ride speed
        return {"planned_km": round(speed * day["duration_min"] / 60), "planned_from": "estimate"}
    return {}


def route_history(groups: list[dict], seg: Segment) -> dict | None:
    """The athlete's ridden route (a group from ride_routes.ride_groups) that follows this favourite."""
    if not seg.polyline or not seg.distance_m:
        return None
    me = {"km": seg.distance_m / 1000, "shape": ride_routes._shape(seg.polyline)}
    for g in groups:
        if g.get("polyline") and ride_routes._same(
            {"km": g["distance_km"], "shape": ride_routes._shape(g["polyline"])}, me
        ):
            return g
    return None


def fuel(minutes: int, temp_max: float | None = None) -> dict:
    """Carbs and fluid for a ride of this length (sports-nutrition rules of thumb)."""
    hours = minutes / 60
    if minutes < 75:
        carbs_h, carb_note = 0, "No food needed; a bottle of water (or a carb drink if it's hard)."
    elif minutes < 150:
        carbs_h, carb_note = 45, "30–60 g of carbs an hour from the first half hour."
    else:
        carbs_h, carb_note = 75, "60–90 g of carbs an hour from the start; practise it on long rides."
    hot = temp_max is not None and temp_max >= 25
    ml_h = 750 if hot else 550
    out = {
        "carbs_g_per_h": carbs_h,
        "carbs_g": round(carbs_h * max(0, hours - 0.25)),
        "fluid_ml": round(ml_h * hours / 50) * 50,
        "bottles": max(1, math.ceil(ml_h * hours / BOTTLE_ML)),
        "note": carb_note + (" Hot: add electrolytes and drink to a plan." if hot else ""),
    }
    out["gels"] = math.ceil(out["carbs_g"] / GEL_G) if out["carbs_g"] else 0
    return out


def pacing(intensity: list[str], ftp: int | None) -> list[str]:
    """Power for the day's zones (e.g. "Z2: 150–200 W"), when FTP is known."""
    if not ftp:
        return []
    out = []
    for chip in intensity or []:
        for z in re.findall(r"\bZ([1-5])\b", chip.upper()):
            lo, hi = ZONES[f"Z{z}"]
            line = f"Z{z}: {round(lo * ftp)}–{round(hi * ftp)} W" if lo else f"Z1: under {round(hi * ftp)} W"
            if line not in out:
                out.append(line)
    return out


def kit(weather: dict | None) -> list[str]:
    """What to wear and take, from the forecast on the ride."""
    if not weather:
        return []
    out = []
    lo, hi = weather.get("temp_min"), weather.get("temp_max")
    if lo is not None and lo < 8:
        out.append("Winter kit: long sleeves, full gloves, overshoes")
    elif lo is not None and lo < 14:
        out.append("Arm warmers and a gilet for the cool start")
    if hi is not None and hi >= 28:
        out.append("Sun cream and light colours; start early")
    if (weather.get("rain_chance") or 0) >= 40:
        out.append("Rain jacket and mudguards")
    if (weather.get("wind_kmh") or 0) >= 30 or (weather.get("gusts_kmh") or 0) >= 45:
        out.append("Windy: stay low, and deep wheels can be a handful")
    return out


def numbers(
    day: dict, seg: Segment | None, history: dict | None, speed: float | None, start: str, kind: str = "ride"
) -> dict:
    """Distance, climbing, speed and finish for the planned ride."""
    minutes = day.get("duration_min") or 0
    out: dict = {"minutes": minutes, "start": start}
    route_km = seg.distance_m / 1000 if seg is not None and seg.kind != "segment" and seg.distance_m else None
    if history and history.get("avg_speed_kmh"):
        speed, out["speed_from"] = history["avg_speed_kmh"], f"your {history['count']} rides on it"
    elif speed:
        out["speed_from"] = SPEED_FROM[kind]
    if route_km:
        out["distance_km"] = round(route_km, 1)
        out["climb_m"] = seg.elevation_m
        if speed:
            minutes = round(route_km / speed * 60)
    elif speed and minutes:
        km = speed * minutes / 60
        out["distance_km"] = round(km) if km >= 10 else round(km, 1)  # a 30 min walk is 2.5 km, not 2
        out["distance_rough"] = True
    if speed:
        out["speed_kmh"] = speed
        if kind != "ride":  # walks and runs read as pace (min/km), as runners and walkers think of them
            secs = round(3600 / speed)
            out["pace_per_km"] = f"{secs // 60}:{secs % 60:02d}"
    out["kind"] = kind
    if history:
        out["ridden"] = history["count"]
        out["fastest_minutes"] = history.get("fastest_minutes")
    out["ride_minutes"] = minutes
    if minutes:
        h, m = (int(x) for x in start.split(":"))
        out["finish"] = (datetime(2000, 1, 1, h, m) + timedelta(minutes=minutes)).strftime("%H:%M")
    return out
