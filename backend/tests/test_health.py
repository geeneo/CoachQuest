"""Health conditions: the athlete sets them after accepting the disclaimer; coaches read; friends never."""

from test_friend_sharing import _friends
from test_phase3 import _create, planner  # noqa: F401  (fixture)

from app import coach, health
from app.db import SessionLocal, User

KNEE = {"id": "knee", "side": "left", "status": "current", "cleared": True, "note": "meniscus 2025"}


def test_conditions_need_the_disclaimer_first(make_user):
    p = make_user("a@example.com")
    h = p.get("/api/athletes/me/health").json()
    assert h["conditions"] == [] and h["disclaimer_accepted_at"] is None and "not medical advice" in h["disclaimer"]
    assert any(g["group"] == "Joints" for g in h["catalog"])
    assert p.request("PUT", "/api/me/health", json={"conditions": [KNEE]}).status_code == 422
    r = p.request("PUT", "/api/me/health", json={"conditions": [KNEE], "accept_disclaimer": True})
    assert r.status_code == 200, r.text
    assert r.json()["conditions"] == [KNEE] and r.json()["disclaimer_accepted_at"]
    # Once accepted, it stays accepted; an empty list clears them.
    assert p.request("PUT", "/api/me/health", json={"conditions": []}).json()["conditions"] == []


def test_cleaning():
    out = health.clean(
        [
            {"id": "asthma", "side": "left", "status": "weird", "cleared": "yes"},
            {"id": "asthma"},
            {"id": "knee", "side": "middle"},
        ]
    )
    assert out == [
        {"id": "asthma", "side": None, "status": "current", "cleared": None, "note": ""},
        {"id": "knee", "side": None, "status": "current", "cleared": None, "note": ""},
    ]
    for bad in ([{"id": "flu"}], [{"id": "other"}]):
        try:
            health.clean(bad)
            raise AssertionError(bad)
        except ValueError:
            pass


def test_coach_reads_friend_never(make_user):
    athlete, friend, aid = _friends(make_user)
    athlete.request("PUT", "/api/me/health", json={"conditions": [KNEE], "accept_disclaimer": True})
    assert friend.get(f"/api/athletes/{aid}/health").status_code == 404
    coach = make_user("c@example.com")
    g = athlete.post("/api/grants", json={"coach_email": "c@example.com", "scopes": ["plans"]}).json()
    coach.post(f"/api/grants/{g['id']}/accept")
    assert coach.get(f"/api/athletes/{aid}/health").json()["conditions"] == [KNEE]
    # Nobody but the athlete changes them: /me/health is always the caller's own.
    assert coach.request("PUT", "/api/me/health", json={"conditions": []}).status_code == 200
    assert athlete.get("/api/athletes/me/health").json()["conditions"] == [KNEE]


def test_ai_gets_conditions_and_friends_dont_see_them_in_plans(make_user, planner):  # noqa: F811
    athlete, friend, aid = _friends(make_user)
    athlete.request(
        "PUT",
        "/api/me/health",
        json={"conditions": [KNEE, {"id": "beta_blockers", "cleared": False}], "accept_disclaimer": True},
    )
    with SessionLocal() as db:
        facts = coach.build_facts(db, db.get(User, aid), {"plans"}, {})
    assert facts["health"] == [
        {
            "condition": "Knee (left)",
            "group": "Joints",
            "status": "current",
            "cleared_by_doctor": True,
            "note": "meniscus 2025",
        },
        {
            "condition": "On beta blockers",
            "group": "Heart and circulation",
            "status": "current",
            "cleared_by_doctor": False,
        },
    ]
    assert "`health`" in coach.SYSTEM_PROMPT and "your health notes" in coach.SYSTEM_PROMPT
    plan = _create(athlete)
    assert plan["facts"]["health"]
    seen = friend.get(f"/api/athletes/{aid}/plans/{plan['id']}").json()
    assert "health" not in seen["facts"] and seen["facts"]["request"]
