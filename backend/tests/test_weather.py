"""The weather page: rides grouped into routes, and the forecast along a route (Open-Meteo faked)."""

import asyncio
from datetime import date, datetime, timedelta

import pytest

from app import geo, ride_routes, weather
from app.db import Activity, Plan, Segment, SessionLocal

LOOP = [(-33.93, 18.86), (-33.90, 18.95), (-33.91, 19.12), (-33.80, 19.05), (-33.73, 18.96), (-33.93, 18.86)]
OTHER = [(-34.10, 18.40), (-34.20, 18.45), (-34.30, 18.40), (-34.10, 18.40)]


def _fake_hourly(wind_from=0, speed=20, rain=0, start=None):
    start = start or date.today()
    times, n = [], weather.DAYS * 24
    for h in range(n):
        t = datetime.combine(start, datetime.min.time()) + timedelta(hours=h)
        times.append(t.strftime("%Y-%m-%dT%H:00"))
    day_speed = [speed + (10 if (h // 24) % 2 else 0) for h in range(n)]  # odd days windier
    return {
        "time": times,
        "temperature_2m": [18.0] * n,
        "precipitation": [0.0] * n,
        "precipitation_probability": [rain] * n,
        "weather_code": [3] * n,
        "wind_speed_10m": day_speed,
        "wind_direction_10m": [wind_from] * n,
        "wind_gusts_10m": [s + 10 for s in day_speed],
    }


@pytest.fixture()
def fake_weather(monkeypatch):
    async def fake(points):
        return [_fake_hourly() for _ in points]

    monkeypatch.setattr(weather, "forecast", fake)


def test_wind_kinds():
    assert weather.wind_kind(0, 0, 20) == "head"  # riding north, wind from the north
    assert weather.wind_kind(180, 0, 20) == "tail"
    assert weather.wind_kind(90, 0, 20) == "cross"
    assert weather.wind_kind(0, 0, 5) == "calm"
    assert weather.compass(225) == "SW"


def test_polyline_round_trip_and_shape():
    enc = geo.encode(LOOP)
    assert [tuple(round(x, 4) for x in p) for p in geo.decode(enc)] == LOOP
    assert geo.decode("_p~iF~ps|U_ulLnnqC_mqNvxq`@") == [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]
    pts = geo.resample(geo.decode(enc), 10)
    assert len(pts) == 10 and pts[0] == pts[-1]  # a loop starts and ends in the same place


def test_route_forecast_ranks_days(fake_weather):
    fc = asyncio.run(weather.route_forecast(geo.encode(LOOP), 120, "07:00", date.today()))
    assert len(fc["days"]) == weather.DAYS and len(fc["best"]) == 3
    calm_days = {(date.today() + timedelta(days=n)).isoformat() for n in range(0, weather.DAYS, 2)}
    assert set(fc["best"]) <= calm_days  # the windier odd days lose
    ride = fc["days"][0]["ride"]
    assert ride["finish"] == "09:00" and ride["wind_from"] == "N" and len(ride["stretches"]) == weather.STRETCHES
    assert sum(ride["share"].values()) in (99, 100, 101)
    assert weather.direction_advice(ride)
    assert len(fc["line"]) == weather.STRETCHES + 1


def _ride(aid, pts, days_ago, minutes=120, name="Loop"):
    with SessionLocal() as db:
        db.add(
            Activity(
                user_id=aid,
                source="strava",
                external_id=f"{name}{days_ago}",
                name=name,
                sport="Ride",
                start_time=datetime.now() - timedelta(days=days_ago),
                duration_s=minutes * 60,
                distance_m=geo.length_m(pts),
                elevation_m=800,
                avg_power=150,
                polyline=geo.encode(pts),
            )
        )
        db.commit()


def test_rides_grouped_into_routes(make_user, fake_weather):
    p = make_user("a@example.com")
    aid = p.get("/api/auth/me").json()["id"]
    _ride(aid, LOOP, 3, 120)
    _ride(aid, list(reversed(LOOP)), 30, 110)  # the same loop the other way round
    _ride(aid, [(lat + 0.001, lng) for lat, lng in LOOP], 400, 130)  # a slightly different line
    _ride(aid, OTHER, 5, name="Cape Point")
    with SessionLocal() as db:
        groups = ride_routes.ride_groups(db, aid)
    loop = next(g for g in groups if g["name"] == "Loop")
    assert loop["count"] == 3 and loop["fastest_minutes"] == 110 and len(groups) == 2
    r = p.get("/api/athletes/me/weather/routes").json()
    assert {x["name"] for x in r["routes"]} == {"Loop", "Cape Point"}
    key = next(x["key"] for x in r["routes"] if x["name"] == "Loop")
    d = p.get(f"/api/athletes/me/weather/routes/{key}?start=06:30").json()
    assert d["start"] == "06:30" and d["route"]["count"] == 3 and len(d["days"]) == weather.DAYS
    assert p.get("/api/athletes/me/weather/routes/ride-999999").status_code == 404
    assert p.get(f"/api/athletes/me/weather/routes/{key}?start=7am").status_code == 422
    assert len(p.get("/api/athletes/me/weather/home").json()["days"]) == weather.DAYS


def test_others_need_the_activities_scope(make_user):
    p = make_user("a@example.com")
    aid = p.get("/api/auth/me").json()["id"]
    other = make_user("b@example.com")
    assert other.get(f"/api/athletes/{aid}/weather/routes").status_code == 404


def _day(d: date, kind: str, segment_id=None, minutes=120):
    return {"date": d.isoformat(), "type": kind, "duration_min": minutes, "segment_id": segment_id}


def test_plan_days_get_the_weather(make_user, monkeypatch):
    async def wet(points):
        return [_fake_hourly(rain=80) for _ in points]

    monkeypatch.setattr(weather, "forecast", wet)
    p = make_user("a@example.com")
    aid = p.get("/api/auth/me").json()["id"]
    _ride(aid, OTHER, 2, name="Cape Point")  # where the athlete starts riding
    today = date.today()
    with SessionLocal() as db:
        seg = Segment(athlete_id=aid, strava_id=1, kind="route", name="Loop", polyline=geo.encode(LOOP))
        db.add(seg)
        db.flush()
        days = [
            _day(today, "Road", seg.id),
            _day(today + timedelta(days=1), "Road"),
            _day(today + timedelta(days=2), "Rest"),
            _day(today + timedelta(days=3), "Zwift / indoor"),
            _day(today + timedelta(days=20), "Road"),
        ]
        plan = Plan(athlete_id=aid, author_id=aid, title="P", content_md="", model="m", weeks=[{"days": days}])
        db.add(plan)
        db.commit()
        plan_id, seg_id = plan.id, seg.id
    r = p.get(f"/api/athletes/me/weather/plan/{plan_id}").json()
    assert set(r["days"]) == {today.isoformat(), (today + timedelta(days=1)).isoformat()}
    on_route = r["days"][today.isoformat()]
    assert on_route["on_route"] and on_route["place"] == "Loop" and on_route["route_key"] == f"fav-{seg_id}"
    assert on_route["headwind"] is not None and "Rain likely" in on_route["warnings"]
    home = r["days"][(today + timedelta(days=1)).isoformat()]
    assert not home["on_route"] and home["place"] is None and home["temp_max"] == 18
    other = make_user("b@example.com")
    assert other.get(f"/api/athletes/{aid}/weather/plan/{plan_id}").status_code == 404
    assert other.get(f"/api/athletes/me/weather/plan/{plan_id}").status_code == 404
