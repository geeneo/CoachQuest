"""Sharing with a friend: view only, and never treated as the athlete's coach."""

from test_phase3 import _create, planner  # noqa: F401  (fixture)
from test_sharing import _seed

from app import comments, dashboard, plan_approval
from app.db import AccessLog, SessionLocal, User

ALL = ["activities", "fitness", "wellness", "profile", "weight", "plans"]


def _friends(make_user, scopes=ALL):
    athlete = make_user("athlete@example.com", "Athlete")
    friend = make_user("friend@example.com", "Friend")
    aid = athlete.get("/api/auth/me").json()["id"]
    _seed(aid)
    g = athlete.post("/api/grants", json={"coach_email": "friend@example.com", "scopes": scopes, "role": "friend"})
    assert g.status_code == 200 and g.json()["role"] == "friend"
    assert friend.post(f"/api/grants/{g.json()['id']}/accept").status_code == 200
    return athlete, friend, aid


def test_friend_sees_what_is_shared(make_user):
    athlete, friend, aid = _friends(make_user, ["activities", "fitness"])
    assert friend.get(f"/api/athletes/{aid}/activities").status_code == 200
    assert friend.get(f"/api/athletes/{aid}/plans").status_code == 404  # plans not shared
    summary = friend.get(f"/api/athletes/{aid}").json()
    assert summary["view_only"] is True and summary["scopes"] == ["activities", "fitness"]
    assert [a["role"] for a in friend.get("/api/athletes").json()] == ["friend"]
    with SessionLocal() as db:  # looks are logged for the athlete
        assert db.query(AccessLog).filter_by(athlete_id=aid, resource="activities").count() >= 1
    assert athlete.get("/api/grants").json()["given"][0]["role"] == "friend"


def test_friend_cannot_change_anything(make_user, planner):  # noqa: F811
    athlete, friend, aid = _friends(make_user)
    plan = _create(athlete)
    # Not a coach: the athlete's own plan doesn't wait for approval.
    assert plan["approval"] == "approved"
    url = f"/api/athletes/{aid}/plans/{plan['id']}"
    seen = friend.get(url).json()
    assert seen["viewer_role"] == "friend" and seen["can_approve"] is False
    day = seen["weeks"][0]["days"][1]["date"]
    r = friend.patch(f"{url}/days/{day}", json={"description": "Changed"})
    assert r.status_code == 403 and "View only" in r.json()["detail"]
    assert friend.post(f"{url}/replan", json={"reason": "x"}).status_code == 403
    assert friend.request("DELETE", url).status_code == 403
    assert friend.post(f"/api/athletes/{aid}/plans", json={"title": "t", "goal": "g"}).status_code == 403
    comment = {"target": "plan", "target_id": plan["id"], "body": "Nice"}
    assert friend.post(f"/api/athletes/{aid}/comments", json=comment).status_code == 403
    assert friend.get(f"/api/athletes/{aid}/comments?target=plan&target_id={plan['id']}").status_code == 200
    with SessionLocal() as db:
        a, f = db.get(User, aid), db.query(User).filter_by(email="friend@example.com").one()
        assert plan_approval.coaches(db, aid) == [] and not plan_approval.required(db, a)
        assert f.id not in {u.id for u in comments._recipients(db, aid, a)}  # no coach emails
        assert dashboard.coach_dashboard(db, f) == []
    # The athlete still edits their own plan.
    assert (
        athlete.patch(f"/api/athletes/me/plans/{plan['id']}/days/{day}", json={"description": "Mine"}).status_code
        == 200
    )


def test_coach_and_friend_are_separate(make_user):
    athlete, friend, aid = _friends(make_user)
    r = athlete.post("/api/grants", json={"coach_email": "friend@example.com", "scopes": ["plans"], "role": "coach"})
    assert r.status_code == 409 and "friend" in r.json()["detail"]
    # Same role again just updates what is shared.
    r = athlete.post(
        "/api/grants", json={"coach_email": "friend@example.com", "scopes": ["activities"], "role": "friend"}
    )
    assert r.status_code == 200 and r.json()["scopes"] == ["activities"]
    bad = {"coach_email": "friend@example.com", "scopes": ["activities"], "role": "boss"}
    assert athlete.post("/api/grants", json=bad).status_code == 422
    # Either side ends it.
    gid = athlete.get("/api/grants").json()["given"][0]["id"]
    assert friend.request("DELETE", f"/api/grants/{gid}").status_code == 200
    assert friend.get(f"/api/athletes/{aid}/activities").status_code == 404
