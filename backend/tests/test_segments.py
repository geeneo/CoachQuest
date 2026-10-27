"""Saved Strava segments: added from a link, given to the AI coach, shown on plan days."""

from test_friend_sharing import _friends
from test_phase3 import _create, _week, planner  # noqa: F401  (fixture)

from app import coach, segments
from app.db import Connection, SessionLocal, User
from app.providers import strava
from app.security import encrypt_json

LINK = "https://www.strava.com/segments/1234567?filter=overall"


def test_links():
    assert segments.strava_id(LINK) == 1234567
    assert segments.strava_id("https://www.strava.com/segments/89012") == 89012
    assert segments.strava_id("1234567") == 1234567
    assert segments.strava_id("https://www.strava.com/activities/1234567") is None
    assert segments.strava_id("Helshoogte") is None


def test_add_with_strava_details(make_user, monkeypatch):
    p = make_user("rider@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    with SessionLocal() as db:
        db.add(Connection(user_id=uid, provider="strava", token_enc=encrypt_json({"access_token": "t"})))
        db.commit()

    async def fake_segment(db, conn, sid):
        assert sid == 1234567
        return {"name": "Helshoogte", "distance_m": 6100, "avg_grade": 5.2, "elevation_m": 330, "city": "Stellenbosch"}

    monkeypatch.setattr(strava, "segment", fake_segment)
    s = p.post("/api/athletes/me/segments", json={"link": LINK, "notes": "hill repeats"}).json()
    assert s["name"] == "Helshoogte" and s["url"] == "https://www.strava.com/segments/1234567"
    assert s["avg_grade"] == 5.2 and s["notes"] == "hill repeats"
    assert p.post("/api/athletes/me/segments", json={"link": LINK}).status_code == 409
    assert p.post("/api/athletes/me/segments", json={"link": "not a link"}).status_code == 422
    with SessionLocal() as db:
        assert segments.for_ai(db, uid) == [
            {
                "id": s["id"],
                "name": "Helshoogte",
                "distance_km": 6.1,
                "avg_grade_pct": 5.2,
                "climb_m": 330,
                "notes": "hill repeats",
            }
        ]
        facts = coach.build_facts(db, db.get(User, uid), {"plans"}, {})
        assert facts["saved_segments"][0]["name"] == "Helshoogte"
    p.patch(f"/api/athletes/me/segments/{s['id']}", json={"name": "Helshoogte pass"})
    assert p.get("/api/athletes/me/segments").json()[0]["name"] == "Helshoogte pass"
    assert p.request("DELETE", f"/api/athletes/me/segments/{s['id']}").status_code == 200
    assert p.get("/api/athletes/me/segments").json() == []


def test_without_strava_the_name_given_is_used(make_user):
    p = make_user("rider@example.com")
    s = p.post("/api/athletes/me/segments", json={"link": LINK, "name": "Hells"}).json()
    assert s["name"] == "Hells" and s["distance_m"] is None
    s2 = p.post("/api/athletes/me/segments", json={"link": "https://www.strava.com/segments/42424"}).json()
    assert s2["name"] == "Strava segment 42424"


def test_plan_days_show_the_segment(make_user, planner):  # noqa: F811
    athlete = make_user("rider@example.com")
    seg = athlete.post("/api/athletes/me/segments", json={"link": LINK, "name": "Helshoogte"}).json()
    week = _week()
    week["days"][2].update(type="Hill repeats", description="6 x Helshoogte", segment_id=seg["id"])
    week["days"][0]["extra_sessions"] = [
        {"type": "Walk", "description": "x", "duration_min": 20, "intensity": [], "segment_id": 999}
    ]
    planner["value"] = [week, week]
    plan = athlete.get(f"/api/athletes/me/plans/{_create(athlete)['id']}").json()
    days = {d["weekday"]: d for d in plan["weeks"][0]["days"]}
    assert days["sat"]["segment"]["name"] == "Helshoogte" and days["sat"]["segment"]["url"].endswith("/1234567")
    assert "segment" not in days["tue"]["extra_sessions"][0]  # 999 isn't a saved segment: not shown
    # Set and clear by hand; someone else's segment id is refused.
    url = f"/api/athletes/me/plans/{plan['id']}/days/{days['thu']['date']}"
    assert (
        athlete.patch(url, json={"segment_id": seg["id"]}).json()["weeks"][0]["days"][3]["segment"]["id"] == seg["id"]
    )
    assert athlete.patch(url, json={"segment_id": 999}).status_code == 422
    assert "segment" not in athlete.patch(url, json={"segment_id": None}).json()["weeks"][0]["days"][3]
    # The AI's answer format carries it.
    day = coach.plan_schema()["schema"]["properties"]["weeks"]["items"]["properties"]["days"]["items"]
    assert "segment_id" in day["required"] and "segment_id" in day["properties"]["extra_sessions"]["items"]["required"]
    assert "saved_segments" in coach.SYSTEM_PROMPT


def test_friends_cannot_add_segments(make_user):
    athlete, friend, aid = _friends(make_user)
    assert friend.post(f"/api/athletes/{aid}/segments", json={"link": LINK}).status_code == 403
    assert friend.get(f"/api/athletes/{aid}/segments").status_code == 200
