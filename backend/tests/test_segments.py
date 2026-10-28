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
    assert segments.parse_link("https://www.strava.com/activities/1234567") is None
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
    found = p.get("/api/athletes/me/segments/strava").json()
    assert [(f["kind"], f["name"]) for f in found] == [("segment", "Helshoogte"), ("route", "Franschhoek loop")]
    assert found[1]["est_minutes"] == 270 and found[0]["elevation_m"] == 330
    assert calls[-1].endswith("/athletes/99/routes")
    # Once a favourite, it's not offered again.
    p.post("/api/athletes/me/segments", json={"link": "https://www.strava.com/segments/1234567", "name": "Hells"})
    assert [f["kind"] for f in p.get("/api/athletes/me/segments/strava").json()] == ["route"]


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
    assert (
        athlete.patch(url, json={"segment_id": seg["id"]}).json()["weeks"][0]["days"][3]["segment"]["id"] == seg["id"]
    )
    assert athlete.patch(url, json={"segment_id": 999}).status_code == 422
    assert "segment" not in athlete.patch(url, json={"segment_id": None}).json()["weeks"][0]["days"][3]
    day = coach.plan_schema()["schema"]["properties"]["weeks"]["items"]["properties"]["days"]["items"]
    assert "segment_id" in day["required"] and "segment_id" in day["properties"]["extra_sessions"]["items"]["required"]
    assert "`favourites`" in coach.SYSTEM_PROMPT and "A `route`" in coach.SYSTEM_PROMPT


def test_friends_cannot_add_favourites(make_user):
    athlete, friend, aid = _friends(make_user)
    assert friend.post(f"/api/athletes/{aid}/segments", json={"link": LINK}).status_code == 403
    assert friend.get(f"/api/athletes/{aid}/segments").status_code == 200
