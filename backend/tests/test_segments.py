"""Favourite Strava routes and segments: added from a link or from Strava, used by the AI coach, shown on plan days."""

from datetime import timedelta

from test_friend_sharing import _friends
from test_phase3 import _create, _week, planner  # noqa: F401  (fixture)

from app import coach, segments
from app.db import Connection, SessionLocal, User, utcnow
from app.providers import strava
from app.security import encrypt_json

LINK = "https://www.strava.com/segments/1234567?filter=overall"
ROUTE = "https://www.strava.com/routes/3234567890123456789"


def _strava(uid):
    with SessionLocal() as db:
        token = encrypt_json({"access_token": "t"})
        later = utcnow() + timedelta(hours=1)  # a fresh token: no refresh call
        db.add(Connection(user_id=uid, provider="strava", token_enc=token, external_id="99", expires_at=later))
        db.commit()


def test_links():
    assert segments.parse_link(LINK) == ("segment", 1234567)
    assert segments.parse_link(ROUTE) == ("route", 3234567890123456789)
    assert segments.parse_link("https://www.strava.com/segments/89012") == ("segment", 89012)
    assert segments.parse_link("1234567") == ("segment", 1234567)
    assert segments.parse_link("https://www.strava.com/activities/1234567") == ("ride", 1234567)
    assert segments.parse_link("https://www.strava.com/athletes/1234567") is None
    assert segments.parse_link("Helshoogte") is None
    assert segments.clean_uses(["long ride", "flying", "hill repeats"]) == ["hill repeats", "long ride"]


def test_add_segment_and_route_with_strava_details(make_user, monkeypatch):
    p = make_user("rider@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    _strava(uid)

    async def fake_segment(db, conn, sid):
        assert sid == 1234567
        return {
            "kind": "segment",
            "strava_id": sid,
            "name": "Helshoogte",
            "distance_m": 6100,
            "avg_grade": 5.2,
            "elevation_m": 330,
            "city": "Stellenbosch",
        }

    async def fake_route(db, conn, rid):
        return {
            "kind": "route",
            "strava_id": rid,
            "name": "Franschhoek loop",
            "distance_m": 121000,
            "elevation_m": 1250,
            "est_minutes": 270,
            "sport": "ride",
        }

    monkeypatch.setattr(strava, "segment", fake_segment)
    monkeypatch.setattr(strava, "route", fake_route)
    s = p.post("/api/athletes/me/segments", json={"link": LINK, "notes": "4-8 times", "uses": ["hill repeats"]}).json()
    assert (
        s["kind"] == "segment" and s["name"] == "Helshoogte" and s["url"] == "https://www.strava.com/segments/1234567"
    )
    assert s["avg_grade"] == 5.2 and s["uses"] == ["hill repeats"]
    r = p.post("/api/athletes/me/segments", json={"link": ROUTE, "uses": ["long ride", "endurance"]}).json()
    assert r["kind"] == "route" and r["url"].endswith("/routes/3234567890123456789") and r["est_minutes"] == 270
    assert p.post("/api/athletes/me/segments", json={"link": LINK}).status_code == 409
    assert p.post("/api/athletes/me/segments", json={"link": "not a link"}).status_code == 422
    listing = p.get("/api/athletes/me/segments").json()
    assert [f["name"] for f in listing["favourites"]] == ["Franschhoek loop", "Helshoogte"]  # routes, then segments
    assert listing["strava_linked"] is True and "hill repeats" in listing["uses"]
    with SessionLocal() as db:
        ai = {f["name"]: f for f in segments.for_ai(db, uid)}
        assert ai["Franschhoek loop"] == {
            "id": r["id"],
            "kind": "route",
            "name": "Franschhoek loop",
            "distance_km": 121.0,
            "climb_m": 1250,
            "est_minutes": 270,
            "uses": ["endurance", "long ride"],
        }
        assert ai["Helshoogte"]["avg_grade_pct"] == 5.2 and ai["Helshoogte"]["notes"] == "4-8 times"
        facts = coach.build_facts(db, db.get(User, uid), {"plans"}, {})
        assert {f["kind"] for f in facts["favourites"]} == {"route", "segment"}
    p.patch(f"/api/athletes/me/segments/{s['id']}", json={"name": "Helshoogte pass", "uses": ["intervals", "x"]})
    edited = next(f for f in p.get("/api/athletes/me/segments").json()["favourites"] if f["id"] == s["id"])
    assert edited["name"] == "Helshoogte pass" and edited["uses"] == ["intervals"]
    assert p.request("DELETE", f"/api/athletes/me/segments/{s['id']}").status_code == 200
    assert len(p.get("/api/athletes/me/segments").json()["favourites"]) == 1


def test_pick_from_strava(make_user, monkeypatch):
    p = make_user("rider@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    assert p.get("/api/athletes/me/segments/strava").status_code == 409  # not linked
    _strava(uid)
    calls = []

    class FakeResp:
        def __init__(self, data):
            self.status_code, self._data = 200, data

        def raise_for_status(self):
            pass

        def json(self):
            return self._data

    async def fake_get(self, url, params=None, headers=None):
        calls.append(url)
        if "/segments/" in url and not url.endswith("/starred"):
            return FakeResp({"id": 1234567, "name": "Helshoogte", "distance": 6100})
        if url.endswith("/segments/starred"):
            return FakeResp(
                [
                    {
                        "id": 1234567,
                        "name": "Helshoogte",
                        "distance": 6100,
                        "average_grade": 5.2,
                        "elevation_high": 500,
                        "elevation_low": 170,
                    }
                ]
            )
        return FakeResp(
            [
                {
                    "id": 3234567890123456789,
                    "id_str": "3234567890123456789",
                    "name": "Franschhoek loop",
                    "distance": 121000,
                    "elevation_gain": 1250,
                    "estimated_moving_time": 16200,
                    "type": 1,
                }
            ]
        )

    import httpx

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    got = p.get("/api/athletes/me/segments/strava").json()
    assert got["private_routes"] is False  # linked before read_all was asked for
    found = got["found"]
    assert [(f["kind"], f["name"]) for f in found] == [("segment", "Helshoogte"), ("route", "Franschhoek loop")]
    assert found[1]["est_minutes"] == 270 and found[0]["elevation_m"] == 330
    assert calls[-1].endswith("/athletes/99/routes")
    # Once a favourite, it's not offered again.
    p.post("/api/athletes/me/segments", json={"link": "https://www.strava.com/segments/1234567", "name": "Hells"})
    assert [f["kind"] for f in p.get("/api/athletes/me/segments/strava").json()["found"]] == ["route"]


def test_without_strava_the_name_given_is_used(make_user):
    p = make_user("rider@example.com")
    s = p.post("/api/athletes/me/segments", json={"link": LINK, "name": "Hells"}).json()
    assert s["name"] == "Hells" and s["distance_m"] is None
    r = p.post("/api/athletes/me/segments", json={"link": ROUTE}).json()
    assert r["name"] == "Strava route 3234567890123456789"


def test_plan_days_show_the_favourite(make_user, planner):  # noqa: F811
    athlete = make_user("rider@example.com")
    seg = athlete.post("/api/athletes/me/segments", json={"link": LINK, "name": "Helshoogte"}).json()
    route = athlete.post("/api/athletes/me/segments", json={"link": ROUTE, "name": "Franschhoek loop"}).json()
    week = _week()
    week["days"][2].update(type="Road", description="Long ride on the Franschhoek loop", segment_id=route["id"])
    week["days"][0]["extra_sessions"] = [
        {
            "type": "Hill repeats",
            "description": "6 x Helshoogte",
            "duration_min": 60,
            "intensity": [],
            "segment_id": seg["id"],
        },
        {"type": "Walk", "description": "x", "duration_min": 20, "intensity": [], "segment_id": 999},
    ]
    planner["value"] = [week, week]
    plan = athlete.get(f"/api/athletes/me/plans/{_create(athlete)['id']}").json()
    days = {d["weekday"]: d for d in plan["weeks"][0]["days"]}
    assert days["sat"]["segment"]["kind"] == "route" and days["sat"]["segment"]["url"].endswith("3234567890123456789")
    assert days["tue"]["extra_sessions"][0]["segment"]["name"] == "Helshoogte"
    assert "segment" not in days["tue"]["extra_sessions"][1]  # 999 isn't a favourite: not shown
    url = f"/api/athletes/me/plans/{plan['id']}/days/{days['thu']['date']}"
    # Thursday is indoors: a workout only, no route or segment.
    assert "segment" not in athlete.patch(url, json={"segment_id": seg["id"]}).json()["weeks"][0]["days"][3]
    thu = athlete.patch(url, json={"type": "Hill repeats", "segment_id": seg["id"]}).json()["weeks"][0]["days"][3]
    assert thu["segment"]["id"] == seg["id"]
    # Switched to indoors, the day loses it.
    thu = athlete.patch(url, json={"type": "Zwift / indoor"}).json()["weeks"][0]["days"][3]
    assert "segment" not in thu and thu["segment_id"] is None
    assert athlete.patch(url, json={"segment_id": 999}).status_code == 422
    assert "segment" not in athlete.patch(url, json={"segment_id": None}).json()["weeks"][0]["days"][3]
    day = coach.plan_schema()["schema"]["properties"]["weeks"]["items"]["properties"]["days"]["items"]
    assert "segment_id" in day["required"] and "segment_id" in day["properties"]["extra_sessions"]["items"]["required"]
    assert "`favourites`" in coach.SYSTEM_PROMPT and "A `route`" in coach.SYSTEM_PROMPT
    assert "an indoor day is its structured workout only" in coach.SYSTEM_PROMPT


def test_indoor_sessions_get_no_route_from_the_ai(make_user, planner):  # noqa: F811
    athlete = make_user("rider@example.com")
    seg = athlete.post("/api/athletes/me/segments", json={"link": LINK, "name": "Kendal climb A"}).json()
    week = _week()
    week["days"][1]["segment_id"] = seg["id"]  # Thursday, Zwift / indoor
    week["days"][1]["extra_sessions"] = [
        {"type": "Treadmill run", "description": "x", "duration_min": 20, "intensity": [], "segment_id": seg["id"]}
    ]
    planner["value"] = [week, week]
    plan = athlete.get(f"/api/athletes/me/plans/{_create(athlete)['id']}").json()
    thu = next(d for d in plan["weeks"][0]["days"] if d["weekday"] == "thu")
    assert thu["segment_id"] is None and "segment" not in thu
    assert thu["extra_sessions"][0]["segment_id"] is None


def test_friends_cannot_add_favourites(make_user):
    athlete, friend, aid = _friends(make_user)
    assert friend.post(f"/api/athletes/{aid}/segments", json={"link": LINK}).status_code == 403
    assert friend.get(f"/api/athletes/{aid}/segments").status_code == 200


RIDE = "https://www.strava.com/activities/20709345142"


def test_a_ride_becomes_a_route(make_user, monkeypatch):
    from datetime import datetime

    from app.db import Activity

    p = make_user("rider@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    assert segments.parse_link(RIDE) == ("ride", 20709345142)
    with SessionLocal() as db:  # already imported from Strava: no Strava call needed
        db.add(
            Activity(
                user_id=uid,
                source="strava",
                external_id="20709345142",
                name="Sillos, Stellenbosch over Hells and back",
                sport="Ride",
                start_time=datetime(2026, 10, 24, 6, 0),
                duration_s=17700,
                distance_m=120700,
                elevation_m=1213,
            )
        )
        db.commit()
    body = {"link": RIDE, "uses": ["long ride"], "notes": "long ride 120km"}
    f = p.post("/api/athletes/me/segments", json=body).json()
    assert f["kind"] == "ride" and f["url"] == RIDE and f["name"] == "Sillos, Stellenbosch over Hells and back"
    assert f["distance_m"] == 120700 and f["elevation_m"] == 1213 and f["est_minutes"] == 295
    with SessionLocal() as db:
        [ai] = segments.for_ai(db, uid)
        assert ai["kind"] == "route" and ai["from_a_ride"] is True and ai["distance_km"] == 120.7

    # Not imported: asked from Strava (the athlete's own ride).
    _strava(uid)

    async def fake_activity(db, conn, aid):
        return {"name": "Morning loop", "distance_m": 60000, "elevation_m": 500, "est_minutes": 130, "sport": "ride"}

    monkeypatch.setattr(strava, "activity", fake_activity)
    g = p.post("/api/athletes/me/segments", json={"link": "https://www.strava.com/activities/555"}).json()
    assert g["name"] == "Morning loop" and g["est_minutes"] == 130


def test_a_ride_without_strava_keeps_the_name_given(make_user):
    p = make_user("rider@example.com")
    f = p.post("/api/athletes/me/segments", json={"link": RIDE, "name": "Sillos over Hells"}).json()
    assert f["kind"] == "ride" and f["name"] == "Sillos over Hells" and f["distance_m"] is None


def test_calendar_shows_the_route(make_user, planner):  # noqa: F811
    athlete = make_user("rider@example.com")
    route = athlete.post("/api/athletes/me/segments", json={"link": ROUTE, "name": "Franschhoek loop"}).json()
    week = _week()
    week["days"][2].update(type="Road", description="Long ride", segment_id=route["id"])
    planner["value"] = [week, week]
    plan = _create(athlete)
    full = athlete.get(f"/api/athletes/me/plans/{plan['id']}").json()
    sat = next(d for d in full["weeks"][0]["days"] if d["weekday"] == "sat")["date"]
    cal = athlete.get(f"/api/athletes/me/calendar?start={sat}&end={sat}").json()
    day = next(d for d in cal["days"] if d["date"] == sat)
    assert day["plan"]["segment"]["name"] == "Franschhoek loop" and day["plan"]["segment"]["kind"] == "route"


def test_add_several_from_strava_at_once(make_user, monkeypatch):
    p = make_user("rider@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    url = "/api/athletes/me/segments/from-strava"
    pick = {"items": [{"kind": "route", "strava_id": 7}]}
    assert p.post(url, json=pick).status_code == 409  # not linked
    _strava(uid)

    async def fake_favourites(db, conn):
        return [
            {"kind": "segment", "strava_id": 1, "name": "Helshoogte", "distance_m": 6100, "avg_grade": 5.2},
            {"kind": "segment", "strava_id": 2, "name": "Franschhoek Pass", "distance_m": 9000, "avg_grade": 4.1},
            {"kind": "route", "strava_id": 7, "name": "Long loop", "distance_m": 121000, "est_minutes": 270},
        ]

    monkeypatch.setattr(strava, "favourites", fake_favourites)
    body = {
        "items": [
            {"kind": "segment", "strava_id": 1},
            {"kind": "route", "strava_id": 7},
            {"kind": "segment", "strava_id": 999},  # not on the athlete's Strava: skipped
        ]
    }
    added = p.post(url, json=body).json()["added"]
    assert [(a["kind"], a["name"]) for a in added] == [("segment", "Helshoogte"), ("route", "Long loop")]
    assert added[0]["uses"] == ["hill repeats"] and added[1]["uses"] == ["endurance"]  # defaults per kind
    assert added[1]["est_minutes"] == 270
    # Uses for all picked; ones already saved are skipped.
    body = {"items": [{"kind": "segment", "strava_id": 1}, {"kind": "segment", "strava_id": 2}], "uses": ["intervals"]}
    added = p.post(url, json=body).json()["added"]
    assert [(a["name"], a["uses"]) for a in added] == [("Franschhoek Pass", ["intervals"])]
    assert len(p.get("/api/athletes/me/segments").json()["favourites"]) == 3
    assert p.post(url, json={"items": [{"kind": "ride", "strava_id": 1}]}).status_code == 422


def test_long_route_ids_survive_the_browser(make_user, monkeypatch):
    """Strava route ids have 19 digits, more than a JavaScript number keeps: they go out and come back as text."""
    p = make_user("rider@example.com")
    _strava(p.get("/api/auth/me").json()["id"])
    rid = 3234567890123456789

    async def fake_favourites(db, conn):
        return [{"kind": "route", "strava_id": rid, "name": "Long loop", "distance_m": 121000}]

    monkeypatch.setattr(strava, "favourites", fake_favourites)
    found = p.get("/api/athletes/me/segments/strava").json()["found"]
    assert found[0]["strava_id"] == str(rid)
    body = {"items": [{"kind": "route", "strava_id": found[0]["strava_id"]}]}
    added = p.post("/api/athletes/me/segments/from-strava", json=body).json()["added"]
    assert [a["strava_id"] for a in added] == [str(rid)]
    assert added[0]["url"].endswith(f"/routes/{rid}")


def test_share_routes_with_everyone(make_user):
    a = make_user("rider@example.com")
    b = make_user("other@example.com")
    url = "/api/athletes/me/segments"
    climb = a.post(
        url, json={"link": LINK, "name": "Helshoogte", "uses": ["hill repeats"], "notes": "4-8 times"}
    ).json()
    loop = a.post(url, json={"link": ROUTE, "name": "Franschhoek loop", "uses": ["long ride"]}).json()
    assert climb["shared"] is False
    assert b.get("/api/shared-routes").json() == []  # nothing shared yet

    assert a.patch(f"{url}/{climb['id']}", json={"shared": True}).json()["shared"] is True
    a.patch(f"{url}/{loop['id']}", json={"shared": True})
    shared = b.get("/api/shared-routes").json()
    rider = a.get("/api/auth/me").json()["display_name"]
    assert [(s["name"], s["shared_by"], s["have"]) for s in shared] == [
        ("Franschhoek loop", [rider], False),
        ("Helshoogte", [rider], False),
    ]
    assert [s["name"] for s in b.get("/api/shared-routes?kind=segment").json()] == ["Helshoogte"]
    assert [s["name"] for s in b.get("/api/shared-routes?q=long").json()] == ["Franschhoek loop"]

    # b adds the climb to their favourites: details, uses and notes come along; not shared by b.
    copy = b.post(f"{url}/copy", json={"segment_id": climb["id"]}).json()
    assert (copy["name"], copy["uses"], copy["notes"], copy["shared"]) == (
        "Helshoogte",
        ["hill repeats"],
        "4-8 times",
        False,
    )
    assert b.post(f"{url}/copy", json={"segment_id": climb["id"]}).status_code == 409
    assert next(s for s in b.get("/api/shared-routes").json() if s["name"] == "Helshoogte")["have"] is True
    # Shared by two people: listed once, with both names.
    b.patch(f"{url}/{copy['id']}", json={"shared": True})
    helshoogte = [s for s in a.get("/api/shared-routes").json() if s["name"] == "Helshoogte"]
    assert len(helshoogte) == 1 and helshoogte[0]["shared_count"] == 2

    # Unsharing: no longer offered; copies stay.
    a.patch(f"{url}/{loop['id']}", json={"shared": False})
    assert "Franschhoek loop" not in [s["name"] for s in b.get("/api/shared-routes").json()]
    assert b.post(f"{url}/copy", json={"segment_id": loop["id"]}).status_code == 404

    # An admin takes a shared one off the list for everyone; others can't.
    assert b.delete(f"/api/shared-routes/{climb['id']}").status_code == 403
    boss = make_user("admin@example.com")
    assert boss.delete(f"/api/shared-routes/{climb['id']}").json() == {"ok": True}
    assert a.get("/api/shared-routes").json() == []
    assert len(b.get(url).json()["favourites"]) == 1
