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


def _ride(aid, pts, days_ago, minutes=120, name="Loop", external_id=None):
    with SessionLocal() as db:
        db.add(
            Activity(
                user_id=aid,
                source="strava",
                external_id=external_id or f"{name}{days_ago}",
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
    assert d["route"]["strava_url"] == "https://www.strava.com/activities/Loop3"
    assert d["route"]["rides"][1]["strava_url"] == "https://www.strava.com/activities/Loop30"
    assert p.get("/api/athletes/me/weather/routes/ride-999999").status_code == 404
    assert p.get(f"/api/athletes/me/weather/routes/{key}?start=7am").status_code == 422
    assert len(p.get("/api/athletes/me/weather/home").json()["days"]) == weather.DAYS


def test_others_need_the_activities_scope(make_user):
    p = make_user("a@example.com")
    aid = p.get("/api/auth/me").json()["id"]
    other = make_user("b@example.com")
    assert other.get(f"/api/athletes/{aid}/weather/routes").status_code == 404


def _day(d: date, kind: str, segment_id=None, minutes=120):
    return {
        "date": d.isoformat(),
        "type": kind,
        "duration_min": minutes,
        "segment_id": segment_id,
        "description": "",
        "intensity": [],
        "locked": False,
    }


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


def test_home_location(make_user, fake_weather, monkeypatch):
    p = make_user("a@example.com")
    aid = p.get("/api/auth/me").json()["id"]
    assert p.get("/api/athletes/me/weather/home").status_code == 409  # no ride, no home yet
    assert p.get("/api/athletes/me/weather/routes").json()["home"] == {
        "set": False,
        "name": "Where your latest outdoor ride started",
        "available": False,
    }
    r = p.request(
        "PUT", "/api/athletes/me/weather/home-location", json={"lat": -33.93, "lng": 18.86, "name": "Stellenbosch"}
    )
    assert r.json() == {"set": True, "name": "Stellenbosch", "lat": -33.93, "lng": 18.86}
    home = p.get("/api/athletes/me/weather/home").json()
    assert home["home"]["name"] == "Stellenbosch" and len(home["days"]) == weather.DAYS
    assert p.request("PUT", "/api/athletes/me/weather/home-location", json={"lat": 91, "lng": 0}).status_code == 422
    coach = make_user("b@example.com")
    assert (
        coach.request("PUT", f"/api/athletes/{aid}/weather/home-location", json={"lat": 1, "lng": 1}).status_code == 404
    )
    assert p.request("PUT", "/api/athletes/me/weather/home-location").json()["set"] is False

    async def found(q):
        return [{"name": "Paarl", "where": "Western Cape, South Africa", "lat": -33.72, "lng": 18.96}]

    monkeypatch.setattr(weather, "places", found)
    assert p.get("/api/athletes/me/weather/places?q=paarl").json()["places"][0]["name"] == "Paarl"
    assert p.get("/api/athletes/me/weather/places?q=p").status_code == 422


def test_ai_coach_gets_the_forecast(make_user, fake_weather, monkeypatch):
    from app import coach, runtime

    seen = {}

    async def fake_plan(db, viewer, athlete, facts):
        seen["facts"] = facts
        return {"summary_md": "Plan", "weeks": []}, "m"

    monkeypatch.setattr("app.routers.plans.generate_plan", fake_plan)
    p = make_user("a@example.com")
    aid = p.get("/api/auth/me").json()["id"]
    _ride(aid, OTHER, 2, name="Cape Point")
    with SessionLocal() as db:
        db.add(Segment(athlete_id=aid, strava_id=1, kind="route", name="Loop", polyline=geo.encode(LOOP)))
        db.add(Segment(athlete_id=aid, strava_id=2, kind="segment", name="Climb", polyline=geo.encode(LOOP)))
        db.commit()
    start = date.today()
    r = p.post(
        "/api/athletes/me/plans", json={"title": "B", "goal": "FTP", "weeks": 1, "start_date": start.isoformat()}
    )
    assert r.status_code == 200, r.text
    w = seen["facts"]["weather"]
    assert w["days"] and all(d["date"] >= date.today().isoformat() for d in w["days"])
    assert len(w["days"]) <= 7 and w["days"][0]["temp_c"] == [18, 18]
    assert [x["name"] for x in w["routes"]] == ["Loop"] and "headwind_pct" in w["routes"][0]["days"][0]
    assert "`weather`" in coach.SYSTEM_PROMPT

    real_get = runtime.get  # the admin switch turns it off
    monkeypatch.setattr(runtime, "get", lambda key: "off" if key == "ai_weather" else real_get(key))
    p.post("/api/athletes/me/plans", json={"title": "B", "goal": "FTP", "weeks": 1, "start_date": start.isoformat()})
    assert "weather" not in seen["facts"]


def test_calendar_ride_details(make_user, fake_weather):
    from app import ride_info

    p = make_user("a@example.com")
    aid = p.get("/api/auth/me").json()["id"]
    for n in range(3):
        _ride(aid, LOOP, 3 + n, minutes=180)  # the loop, three times, ~3h
    loop_m = geo.length_m(LOOP)
    with SessionLocal() as db:
        from app.db import User

        db.get(User, aid).ftp_watts = 250
        seg = Segment(
            athlete_id=aid, strava_id=1, kind="route", name="Loop", polyline=geo.encode(LOOP), distance_m=loop_m
        )
        db.add(seg)
        db.flush()
        today = date.today()
        days = [
            dict(_day(today, "Road", seg.id, 200), intensity=["Z2"]),
            _day(today + timedelta(days=1), "Road", None, 60),
            _day(today + timedelta(days=2), "Zwift / indoor"),
            _day(today + timedelta(days=3), "Rest"),
        ]
        db.add(
            Plan(
                athlete_id=aid,
                author_id=aid,
                title="P",
                content_md="",
                model="m",
                start_date=today,
                weeks=[{"phase": "Base", "days": days}],
            )
        )
        db.commit()
    end = today + timedelta(days=6)
    r = p.get(f"/api/athletes/me/weather/rides?start={today}&end={end}").json()
    assert set(r["days"]) == {today.isoformat(), (today + timedelta(days=1)).isoformat()}
    long = r["days"][today.isoformat()]
    n = long["numbers"]
    assert n["ridden"] == 3 and n["distance_km"] == round(loop_m / 1000, 1) and "3 rides" in n["speed_from"]
    assert n["ride_minutes"] == 180 and n["finish"]
    assert long["pacing"] == ["Z2: 140–188 W"] and long["fuel"]["carbs_g_per_h"] == 75
    assert long["weather"]["on_route"] and long["weather"]["place"] == "Loop"
    short = r["days"][(today + timedelta(days=1)).isoformat()]
    assert short["numbers"]["distance_rough"] and short["fuel"]["carbs_g_per_h"] == 0
    assert p.get(f"/api/athletes/me/weather/rides?start={end}&end={today}").status_code == 422
    assert ride_info.kit({"temp_min": 5, "temp_max": 30, "rain_chance": 60, "wind_kmh": 35}) == [
        "Winter kit: long sleeves, full gloves, overshoes",
        "Sun cream and light colours; start early",
        "Rain jacket and mudguards",
        "Windy: stay low, and deep wheels can be a handful",
    ]


def test_calendar_ride_details_survive_strava_failing(make_user, fake_weather, monkeypatch):
    """A favourite saved before lines were kept, while Strava refuses (e.g. rate limited)."""
    from app.db import Connection
    from app.providers import strava

    async def refuse(db, conn, strava_id):
        raise RuntimeError("Rate Limit Exceeded")

    monkeypatch.setattr(strava, "route", refuse)
    p = make_user("a@example.com")
    aid = p.get("/api/auth/me").json()["id"]
    _ride(aid, OTHER, 2, name="Cape Point")
    today = date.today()
    with SessionLocal() as db:
        db.add(Connection(user_id=aid, provider="strava", status="active", token_enc="x"))
        seg = Segment(athlete_id=aid, strava_id=7, kind="route", name="Old favourite", distance_m=129000)
        db.add(seg)
        db.flush()
        days = [_day(today, "Road", seg.id, 316), _day(today + timedelta(days=1), "Road", None, 25)]
        db.add(
            Plan(
                athlete_id=aid,
                author_id=aid,
                title="P",
                content_md="",
                model="m",
                start_date=today,
                weeks=[{"phase": "Base", "days": days}],
            )
        )
        db.commit()
    r = p.get(f"/api/athletes/me/weather/rides?start={today}&end={today + timedelta(days=6)}")
    assert r.status_code == 200, r.text
    sat = r.json()["days"][today.isoformat()]
    assert sat["numbers"]["distance_km"] == 129.0 and sat["weather"] and not sat["weather"]["on_route"]
    assert r.json()["days"][(today + timedelta(days=1)).isoformat()]["weather"]


def test_ridden_route_saved_as_favourite(make_user, fake_weather):
    p = make_user("a@example.com")
    aid = p.get("/api/auth/me").json()["id"]
    _ride(aid, LOOP, 3, external_id="16000000003")
    _ride(aid, LOOP, 10, external_id="16000000010")
    loop = p.get("/api/athletes/me/weather/routes").json()["routes"][0]
    assert loop["favourite_id"] is None
    detail = p.get(f"/api/athletes/me/weather/routes/{loop['key']}").json()["route"]
    r = p.post(
        "/api/athletes/me/segments", json={"link": detail["strava_url"], "name": "My loop", "uses": ["endurance"]}
    )
    assert r.status_code == 200, r.text
    routes = p.get("/api/athletes/me/weather/routes").json()["routes"]
    fav = next(x for x in routes if x["source"] == "favourite")
    ridden = next(x for x in routes if x["source"] == "rides")
    assert fav["name"] == "My loop" and fav["has_line"] and ridden["favourite_id"] == r.json()["id"]
