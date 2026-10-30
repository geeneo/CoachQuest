"""Weather along a route for the next 16 days (Open-Meteo), and what it means for a ride.

For each day, the ride starts at the chosen time and takes the route's usual time; every stretch of the
route gets the wind at the place and hour you'd ride it, as a headwind, crosswind or tailwind. The day
is summed up by its worst conditions anywhere on the route (wind, gusts, rain, temperature), and days
are ranked so the best ones stand out. Also: would the other direction round have less headwind?

Open-Meteo's free API is for non-commercial use; with a key (Admin → Settings → Weather, a paid plan)
it uses the customer endpoint. Forecasts are cached for an hour per place (rounded to about 2 km).
"""

import logging
import time as clock
from datetime import date, datetime, timedelta

import httpx

from . import geo, runtime

log = logging.getLogger("coachquest.weather")

FREE_URL = "https://api.open-meteo.com/v1/forecast"
PAID_URL = "https://customer-api.open-meteo.com/v1/forecast"
PLACES_URL = "https://geocoding-api.open-meteo.com/v1/search"
HOURLY = (
    "temperature_2m,precipitation,precipitation_probability,weather_code,"
    "wind_speed_10m,wind_direction_10m,wind_gusts_10m"
)
DAYS = 16
CACHE_S = 3600
SAMPLE_POINTS = 7  # places along the route to ask the weather for
STRETCHES = 40  # pieces of the route, each coloured by its wind
CALM_KMH = 8  # below this the wind doesn't count as head- or tailwind

_cache: dict[tuple, tuple[float, dict]] = {}

# WMO weather codes → (label, emoji).
CODES = {
    0: ("Clear", "☀️"),
    1: ("Mostly clear", "🌤️"),
    2: ("Partly cloudy", "⛅"),
    3: ("Overcast", "☁️"),
    45: ("Fog", "🌫️"),
    48: ("Fog", "🌫️"),
    51: ("Light drizzle", "🌦️"),
    53: ("Drizzle", "🌦️"),
    55: ("Heavy drizzle", "🌧️"),
    56: ("Freezing drizzle", "🌧️"),
    57: ("Freezing drizzle", "🌧️"),
    61: ("Light rain", "🌦️"),
    63: ("Rain", "🌧️"),
    65: ("Heavy rain", "🌧️"),
    66: ("Freezing rain", "🌧️"),
    67: ("Freezing rain", "🌧️"),
    71: ("Light snow", "🌨️"),
    73: ("Snow", "🌨️"),
    75: ("Heavy snow", "❄️"),
    77: ("Snow grains", "🌨️"),
    80: ("Rain showers", "🌦️"),
    81: ("Rain showers", "🌧️"),
    82: ("Heavy showers", "⛈️"),
    85: ("Snow showers", "🌨️"),
    86: ("Snow showers", "❄️"),
    95: ("Thunderstorm", "⛈️"),
    96: ("Thunderstorm, hail", "⛈️"),
    99: ("Thunderstorm, hail", "⛈️"),
}
COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


class WeatherError(Exception):
    pass


def compass(deg: float | None) -> str:
    return "" if deg is None else COMPASS[round(deg / 45) % 8]


def _key(p: geo.Point) -> tuple:
    return (round(p[0] / 0.02) * 0.02, round(p[1] / 0.02) * 0.02)


async def forecast(points: list[geo.Point]) -> list[dict]:
    """Hourly forecast for each point (Open-Meteo, cached an hour per ~2 km square)."""
    keys = [_key(p) for p in points]
    now = clock.monotonic()
    missing = sorted({k for k in keys if k not in _cache or now - _cache[k][0] > CACHE_S})
    if missing:
        api_key = runtime.get("open_meteo_key")
        params = {
            "latitude": ",".join(f"{k[0]:.3f}" for k in missing),
            "longitude": ",".join(f"{k[1]:.3f}" for k in missing),
            "hourly": HOURLY,
            "forecast_days": DAYS,
            "timezone": "auto",
            "wind_speed_unit": "kmh",
        }
        if api_key:
            params["apikey"] = api_key
        data = None
        for attempt in (1, 2):  # once more after a network blip
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    r = await client.get(PAID_URL if api_key else FREE_URL, params=params)
                    r.raise_for_status()
                    data = r.json()
                break
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("Open-Meteo failed (try %s): %s", attempt, exc)
                if attempt == 2 or (isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500):
                    raise WeatherError("The weather service didn't answer; try again in a minute") from exc
        for k, d in zip(missing, data if isinstance(data, list) else [data], strict=False):
            _cache[k] = (now, d["hourly"])
    return [_cache[k][1] for k in keys]


async def places(query: str) -> list[dict]:
    """Towns and places matching a name (Open-Meteo geocoding), for setting a home location."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(PLACES_URL, params={"name": query, "count": 8, "language": "en"})
            r.raise_for_status()
            found = r.json().get("results") or []
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("Open-Meteo place search failed: %s", exc)
        raise WeatherError("The place search didn't answer; try again in a minute") from exc
    out = []
    for f in found:
        where = ", ".join(x for x in (f.get("admin1"), f.get("country")) if x)
        out.append(
            {
                "name": f.get("name") or "",
                "where": where,
                "lat": round(float(f["latitude"]), 4),
                "lng": round(float(f["longitude"]), 4),
            }
        )
    return out


def _index(hourly: dict) -> dict[str, int]:
    return {t: i for i, t in enumerate(hourly["time"])}


def _at(hourly: dict, idx: dict, when: datetime, field: str):
    i = idx.get(when.strftime("%Y-%m-%dT%H:00"))
    if i is None:
        return None
    values = hourly.get(field) or []
    return values[i] if i < len(values) else None


def wind_kind(wind_from: float, heading: float, speed: float) -> str:
    """head, cross or tail for a rider going `heading` with wind from `wind_from`; calm under CALM_KMH."""
    if speed < CALM_KMH:
        return "calm"
    angle = abs((wind_from - heading + 180) % 360 - 180)
    return "head" if angle <= 45 else "tail" if angle >= 135 else "cross"


def _stretches(points: list[geo.Point]) -> list[dict]:
    """The route in STRETCHES pieces: middle point, heading and how far along (0-1)."""
    pts = geo.resample(points, STRETCHES + 1)
    return [
        {
            "mid": ((pts[i][0] + pts[i + 1][0]) / 2, (pts[i][1] + pts[i + 1][1]) / 2),
            "heading": geo.bearing(pts[i], pts[i + 1]),
            "at": (i + 0.5) / STRETCHES,
        }
        for i in range(STRETCHES)
    ]


def _nearest(p: geo.Point, samples: list[geo.Point]) -> int:
    return min(range(len(samples)), key=lambda i: geo.distance_m(p, samples[i]))


def _ride_day(day: date, start: str, minutes: int, stretches, samples, hourlies, reverse=False) -> dict | None:
    """One day's ride: the wind on each stretch and the worst conditions anywhere, or None past the forecast."""
    h, m = (int(x) for x in start.split(":"))
    begin = datetime.combine(day, datetime.min.time()) + timedelta(hours=h, minutes=m)
    idxs = [_index(hr) for hr in hourlies]
    order = list(reversed(stretches)) if reverse else stretches
    kinds, temps, rain_p, rain_mm, gusts, winds, codes = [], [], [], [], [], [], []
    for n, s in enumerate(order):
        when = begin + timedelta(minutes=minutes * (n + 0.5) / len(order))
        k = s["near"]
        hr, idx = hourlies[k], idxs[k]
        speed = _at(hr, idx, when, "wind_speed_10m")
        wfrom = _at(hr, idx, when, "wind_direction_10m")
        if speed is None or wfrom is None:
            return None
        heading = (s["heading"] + 180) % 360 if reverse else s["heading"]
        kinds.append(wind_kind(wfrom, heading, speed))
        winds.append((speed, wfrom))
        for lst, field in (
            (temps, "temperature_2m"),
            (rain_p, "precipitation_probability"),
            (rain_mm, "precipitation"),
            (gusts, "wind_gusts_10m"),
            (codes, "weather_code"),
        ):
            v = _at(hr, idx, when, field)
            if v is not None:
                lst.append(v)
    share = {k: round(100 * kinds.count(k) / len(kinds)) for k in ("head", "cross", "tail", "calm")}
    speed = max(w[0] for w in winds)
    mid_wind = winds[len(winds) // 2]
    half = len(kinds) // 2

    def half_says(part: list[str]) -> str:
        top = max(("head", "tail", "cross", "calm"), key=part.count)
        return {"head": "headwind", "tail": "tailwind", "cross": "crosswind", "calm": "calm"}[top]

    code = max(codes) if codes else None
    return {
        "date": day.isoformat(),
        "start": start,
        "finish": (begin + timedelta(minutes=minutes)).strftime("%H:%M"),
        "code": code,
        "label": CODES.get(code, ("", ""))[0],
        "icon": CODES.get(code, ("", "🌡️"))[1],
        "temp_min": round(min(temps)) if temps else None,
        "temp_max": round(max(temps)) if temps else None,
        "rain_chance": round(max(rain_p)) if rain_p else 0,
        "rain_mm": round(max(rain_mm), 1) if rain_mm else 0,
        "wind_kmh": round(speed),
        "wind_from": compass(mid_wind[1]),
        "wind_deg": round(mid_wind[1]),
        "gusts_kmh": round(max(gusts)) if gusts else None,
        "share": share,
        "first_half": half_says(kinds[:half]),
        "second_half": half_says(kinds[half:]),
        "stretches": kinds,  # in route order
    }


def score(d: dict) -> float:
    """Lower is a better day to ride: wind, gusts, headwind, rain, and heat or cold."""
    s = d["wind_kmh"] + 0.4 * (d["gusts_kmh"] or 0) + 0.25 * d["wind_kmh"] * d["share"]["head"] / 100 * 4
    s += 0.35 * d["rain_chance"] + 8 * d["rain_mm"]
    if d["temp_min"] is not None and d["temp_min"] < 8:
        s += 2 * (8 - d["temp_min"])
    if d["temp_max"] is not None and d["temp_max"] > 30:
        s += 2 * (d["temp_max"] - 30)
    return round(s, 1)


def _daily(hourly: dict, day: date) -> dict:
    """The whole day at one place (the day strip): weather, low and high, rain chance, strongest wind."""
    rows = [i for i, t in enumerate(hourly["time"]) if t.startswith(day.isoformat())]
    if not rows:
        return {}
    daytime = [i for i in rows if "06:00" <= hourly["time"][i][11:16] <= "19:00"] or rows

    def col(field, idx):
        return [hourly[field][i] for i in idx if hourly[field][i] is not None]

    codes = col("weather_code", daytime)
    winds = col("wind_speed_10m", daytime)
    strongest = max(daytime, key=lambda i: hourly["wind_speed_10m"][i] or 0)
    code = max(codes, key=codes.count) if codes else None
    return {
        "date": day.isoformat(),
        "code": code,
        "label": CODES.get(code, ("", ""))[0],
        "icon": CODES.get(code, ("", "🌡️"))[1],
        "temp_min": round(min(col("temperature_2m", rows))),
        "temp_max": round(max(col("temperature_2m", rows))),
        "rain_chance": round(max(col("precipitation_probability", daytime) or [0])),
        "wind_kmh": round(max(winds)) if winds else None,
        "wind_from": compass(hourly["wind_direction_10m"][strongest]),
    }


async def route_forecast(encoded: str, minutes: int, start: str, today: date) -> dict:
    """The forecast for riding this route at `start` each day, ranked, with each day's whole-day weather."""
    points = geo.decode(encoded)
    if len(points) < 2:
        raise WeatherError("This route has no map line yet")
    samples = geo.resample(points, SAMPLE_POINTS)
    hourlies = await forecast(samples)
    stretches = _stretches(points)
    for s in stretches:
        s["near"] = _nearest(s["mid"], samples)
    minutes = max(15, minutes or 60)
    days = []
    for n in range(DAYS):
        day = today + timedelta(days=n)
        ride = _ride_day(day, start, minutes, stretches, samples, hourlies)
        whole = _daily(hourlies[0], day)
        if not whole:
            continue
        if ride:
            ride["score"] = score(ride)
            back = _ride_day(day, start, minutes, stretches, samples, hourlies, reverse=True)
            ride["reverse"] = {"share": back["share"], "score": score(back)} if back else None
        days.append({**whole, "ride": ride})
    ranked = sorted((d for d in days if d["ride"]), key=lambda d: d["ride"]["score"])
    for place, d in enumerate(ranked[:3], 1):
        d["rank"] = place
    return {
        "days": days,
        "best": [d["date"] for d in ranked[:3]],
        "line": [[round(p[0], 5), round(p[1], 5)] for p in geo.resample(points, STRETCHES + 1)],
    }


def direction_advice(ride: dict) -> str:
    """Either way round the same, or which way has less headwind."""
    back = ride.get("reverse")
    if not back:
        return ""
    here, there = ride["share"]["head"], back["share"]["head"]
    if abs(here - there) < 10:
        return "Either way round: the wind is about the same both directions."
    if there < here:
        return f"Ride it the other way round: {there}% headwind instead of {here}%."
    return f"This way round is better: {here}% headwind instead of {there}% the other way."


WET_CHANCE = 50  # % rain chance, or
WET_MM = 1.0  # mm in an hour, counts as wet
WINDY_KMH = 30
GUSTY_KMH = 45


def plan_summary(d: dict, place: str | None = None, route_key: str | None = None) -> dict:
    """A plan day's weather in a line: along its route at riding time (`d` from _ride_day), or the whole
    day where the athlete starts (`d` from _daily). With warnings for rain, wind, cold and heat."""
    on_route = "share" in d
    out = {
        k: d.get(k)
        for k in ("icon", "label", "temp_min", "temp_max", "rain_chance", "wind_kmh", "wind_from", "gusts_kmh")
    }
    out.update(
        place=place,
        route_key=route_key,
        on_route=on_route,
        start=d.get("start"),
        finish=d.get("finish"),
        headwind=d["share"]["head"] if on_route else None,
        advice=direction_advice(d) if on_route else "",
    )
    warnings = []
    if (d.get("rain_chance") or 0) >= WET_CHANCE or (d.get("rain_mm") or 0) >= WET_MM:
        warnings.append("Rain likely")
    if (d.get("wind_kmh") or 0) >= WINDY_KMH or (d.get("gusts_kmh") or 0) >= GUSTY_KMH:
        warnings.append("Windy")
    if d.get("temp_min") is not None and d["temp_min"] < 5:
        warnings.append("Cold")
    if d.get("temp_max") is not None and d["temp_max"] >= 32:
        warnings.append("Hot")
    out["warnings"] = warnings
    return out
