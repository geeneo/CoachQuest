"""Coach approval for AI plans, and the coach's notes box."""

import pytest
from test_phase3 import HARD, STEADY, _next_monday, _scheduled, _week

from app.db import Comment, SessionLocal


@pytest.fixture()
def team(make_user, monkeypatch):
    seen = {"value": [_week(), _week()]}

    async def fake_generate(db, viewer, athlete, facts):
        seen["facts"] = facts
        return {"summary_md": "Plan", "weeks": seen["value"]}, "claude-test"

    monkeypatch.setattr("app.routers.plans.generate_plan", fake_generate)
    athlete = make_user("a@example.com", "Ann")
    cobus = make_user("c@example.com", "Cobus")
    aid = athlete.get("/api/auth/me").json()["id"]
    g = athlete.post("/api/grants", json={"coach_email": "c@example.com", "scopes": ["plans"]}).json()
    cobus.post(f"/api/grants/{g['id']}/accept")
    return athlete, cobus, aid, seen


def _create(p, who="me", **extra):
    r = p.post(
        f"/api/athletes/{who}/plans",
        json={"title": "Block", "goal": "FTP", "weeks": 2, "start_date": _next_monday().isoformat(), **extra},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_athlete_plan_waits_for_the_coach(team):
    athlete, cobus, aid, _ = team
    p = _create(athlete)
    assert p["approval"] == "awaiting" and p["can_approve"] is False and p["viewer_role"] == "athlete"
    assert _scheduled(aid) == []  # nothing on the calendar, so nothing goes to Zwift
    assert athlete.get("/api/athletes/me/plans/current").json() is None
    url = f"/api/athletes/{aid}/plans/{p['id']}"
    assert athlete.post(f"{url}/approve").status_code == 403
    # The coach sees it flagged and can edit it before approving.
    row = next(r for r in cobus.get("/api/coach/dashboard").json() if r["id"] == aid)
    assert row["plans_waiting"] == 1 and "1 plan to approve" in row["flags"]
    seen = cobus.get(url).json()
    assert seen["can_approve"] is True and seen["viewer_role"] == "coach"
    assert cobus.get(f"/api/athletes/{aid}/plans").json()[0]["approval"] == "awaiting"
    r = cobus.post(f"{url}/approve").json()
    assert r["approval"] == "approved" and [e["event"] for e in r["history"]] == ["created", "approved"]
    assert len(_scheduled(aid)) == 4
    assert cobus.post(f"{url}/approve").status_code == 409


def test_send_back_and_rewrite(team):
    athlete, cobus, aid, seen = team
    p = _create(athlete)
    url = f"/api/athletes/{aid}/plans/{p['id']}"
    assert cobus.post(f"{url}/send-back", json={"note": "x"}).status_code == 422
    r = cobus.post(f"{url}/send-back", json={"note": "Too much intensity, keep it Z2"}).json()
    assert r["approval"] == "sent_back" and r["history"][-1]["note"] == "Too much intensity, keep it Z2"
    with SessionLocal() as db:
        assert db.query(Comment).one().body == "Too much intensity, keep it Z2"  # the re-plan reads it
    r = athlete.post(f"{url}/replan", json={"reason": "Coach's feedback"}).json()
    assert r["approval"] == "awaiting" and "pending" not in r
    assert seen["facts"]["request"]["replan"]["comments"][0]["text"] == "Too much intensity, keep it Z2"
    assert _scheduled(aid) == []


def test_athlete_replan_is_a_proposal(team):
    athlete, cobus, aid, seen = team
    p = _create(athlete)
    url = f"/api/athletes/{aid}/plans/{p['id']}"
    cobus.post(f"{url}/approve")
    before = [(w.day, w.name) for w in _scheduled(aid)]
    seen["value"] = [_week(tue_steps=HARD, thu_steps=STEADY), _week()]
    seen["value"][0]["days"][0]["description"] = "Changed"
    r = athlete.post(f"{url}/replan", json={"reason": "Feeling strong"}).json()
    assert r["pending"] is True and r["approval"] == "approved"
    assert r["pending"] and r["changed"] >= 1  # noqa: PT018
    plan = athlete.get(url).json()
    assert plan["pending"]["reason"] == "Feeling strong" and plan["pending"]["by"] == "Ann"
    assert plan["pending"]["changes"][0]["after"]["description"] == "Changed"
    assert "fresh" not in plan["pending"]
    assert [(w.day, w.name) for w in _scheduled(aid)] == before  # still the approved plan
    # Sending it back drops the proposal; a new one can be approved.
    cobus.post(f"{url}/send-back", json={"note": "Not this week"})
    assert "pending" not in athlete.get(url).json()
    athlete.post(f"{url}/replan", json={})
    r = cobus.post(f"{url}/approve").json()
    assert r["changed"] >= 1 and "pending" not in r
    assert "Changed" in str(r["weeks"][0]["days"])
    assert [e["event"] for e in r["history"]] == [
        "created",
        "approved",
        "replan_proposed",
        "sent_back",
        "replan_proposed",
        "approved",
    ]


def test_coach_plans_and_coach_notes(team):
    athlete, cobus, aid, seen = team
    p = _create(cobus, who=aid, coach_notes="No intervals on Mondays")
    assert p["approval"] == "approved" and len(_scheduled(aid)) == 4  # the coach decides
    assert seen["facts"]["request"]["coach_notes"] == "No intervals on Mondays"
    assert p["history"][0]["coach_notes"] == "No intervals on Mondays"
    url = f"/api/athletes/{aid}/plans/{p['id']}"
    r = cobus.post(f"{url}/replan", json={"coach_notes": "Easier week 2"}).json()
    assert "pending" not in r and seen["facts"]["request"]["replan"]["coach_notes"] == "Easier week 2"
    # Coach's notes come from a coach only.
    assert athlete.post(f"{url}/replan", json={"coach_notes": "I'm the coach"}).status_code == 422
    r = athlete.post(
        "/api/athletes/me/plans",
        json={"title": "B", "goal": "x", "weeks": 1, "coach_notes": "Sneaky"},
    )
    assert r.status_code == 422


def test_no_coach_no_waiting(make_user, monkeypatch):
    async def fake_generate(db, viewer, athlete, facts):
        return {"summary_md": "Plan", "weeks": [_week()]}, "claude-test"

    monkeypatch.setattr("app.routers.plans.generate_plan", fake_generate)
    solo = make_user("s@example.com")
    p = _create(solo, weeks=1)
    assert p["approval"] == "approved" and p["can_approve"] is False


def test_last_coach_leaves(team):
    athlete, cobus, aid, _ = team
    p = _create(athlete)
    for g in athlete.get("/api/grants").json()["given"]:
        athlete.request("DELETE", f"/api/grants/{g['id']}")
    url = f"/api/athletes/me/plans/{p['id']}"
    assert athlete.get(url).json()["can_approve"] is True
    assert athlete.post(f"{url}/approve").json()["approval"] == "approved"
