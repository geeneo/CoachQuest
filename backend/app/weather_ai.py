"""The forecast for the AI coach (coach.py): the plan days within the forecast (16 days), so it can put
the long ride on the calmest dry day, move a ride indoors on a stormy one, or say which way round to
ride a loop.

Two parts: the whole day at the athlete's home location (Weather page), and for each favourite route
riding it at their usual start time: headwind share, wind, gusts and rain. Weather isn't Strava data;
the routes are the favourites the AI already gets. A failing weather service never stops a plan: the
facts just have no weather.
"""

import logging
from datetime import date, timedelta

from sqlalchemy.orm import Session as DbSession

from . import ride_routes, runtime, segments, weather
from .db import User

log = logging.getLogger("coachquest.weather_ai")

MAX_ROUTES = 6  # favourite routes with a forecast (the most recently added)

PROMPT_RULE = """- `weather` (when present) is the forecast for the plan days within the next 16 days: `days` is \
the whole day near the athlete's home, `routes` is riding each favourite route (by `id`) that day from \
`start_time`: `headwind_pct` (share of the ride into the wind), wind, gusts and rain chance. Use it:
  - Put the week's long outdoor ride on its calmest dry day, and hard outdoor efforts on days without \
strong wind or rain, when the weekday preferences leave that choice (they still win). Prefer the \
favourite route with the least headwind that day.
  - On a day with rain likely (60%+) or strong wind or gusts (40+ km/h wind, 55+ km/h gusts), plan the \
ride indoors ("Zwift / indoor") when that is one of the athlete's session types, else shorter and \
sheltered; say why in the description.
  - Mention the weather in a session's description only when it shaped it ("calmest day this week", \
"start early: 32°C by noon", "rain likely: indoors"). Keep it short.
  - Days past the forecast are planned as usual. Forecasts change: don't promise the weather."""


def _row(d: dict) -> dict:
    return {
        "date": d["date"],
        "sky": d.get("label"),
        "temp_c": [d.get("temp_min"), d.get("temp_max")],
        "rain_pct": d.get("rain_chance"),
        "wind_kmh": d.get("wind_kmh"),
        "wind_from": d.get("wind_from"),
    }


async def for_ai(db: DbSession, athlete: User, first: date, last: date, today: date) -> dict | None:
    """The forecast for the days from `first` to `last` that are in the forecast, or None."""
    if runtime.get("ai_weather") == "off":
        return None
    first, last = max(first, today), min(last, today + timedelta(days=weather.DAYS - 1))
    home = ride_routes.home_point(db, athlete)
    if first > last or home is None:
        return None
    window = {(first + timedelta(days=n)).isoformat() for n in range((last - first).days + 1)}
    start = ride_routes.usual_start(db, athlete)
    try:
        hourly = (await weather.forecast([home]))[0]
        days = [_row(d) for n in range(weather.DAYS) if (d := weather._daily(hourly, today + timedelta(days=n)))]
        out = {
            "source": "Open-Meteo forecast",
            "start_time": start,
            "days": [d for d in days if d["date"] in window],
        }
        favs = [s for s in segments.for_athlete(db, athlete.id) if s.kind != "segment" and s.polyline]
        routes = []
        for s in sorted(favs, key=lambda x: x.id, reverse=True)[:MAX_ROUTES]:
            minutes = s.est_minutes or round((s.distance_m or 0) / 1000 / 25 * 60)
            fc = await weather.route_forecast(s.polyline, minutes, start, today)
            per_day = [
                {
                    "date": d["date"],
                    "headwind_pct": d["ride"]["share"]["head"],
                    "wind_kmh": d["ride"]["wind_kmh"],
                    "gusts_kmh": d["ride"]["gusts_kmh"],
                    "rain_pct": d["ride"]["rain_chance"],
                }
                for d in fc["days"]
                if d["ride"] and d["date"] in window
            ]
            if per_day:
                routes.append({"id": s.id, "name": s.name, "days": per_day})
        if routes:
            out["routes"] = routes
        return out if out["days"] else None
    except Exception as exc:  # the weather service, odd answers: plan without weather
        log.warning("No weather for the AI coach (athlete %s): %s", athlete.id, exc)
        return None
