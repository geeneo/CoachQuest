from datetime import date, timedelta

import pytest
from test_mail import _configure, fake_smtp  # noqa: F401  (fixture)

from app import accounts
from app.db import PlanComment, SessionLocal, User


def _week():
    return {
        "phase": "Build",
        "focus": "",
        "days": [{"weekday": "tue", "type": "Road", "description": "Tempo", "duration_min": 60, "intensity": []}],
    }


@pytest.fixture()
def setup(make_user, monkeypatch):
    seen = {}

    async def fake_generate(db, viewer, athlete, facts):
        seen.update(facts)
        return {"summary_md": "Plan", "weeks": [_week(), _week()]}, "claude-test"

    monkeypatch.setattr("app.routers.plans.generate_plan", fake_generate)
    athlete = make_user("a@example.com", "Ann")
    coach = make_user("c@example.com", "Cobus")
    aid = athlete.get("/api/auth/me").json()["id"]
    g = athlete.post("/api/grants", json={"coach_email": "c@example.com", "scopes": ["plans"]}).json()
    coach.post(f"/api/grants/{g['id']}/accept")
    monday = date.today() - timedelta(days=date.today().weekday())
    plan = athlete.post(
        "/api/athletes/me/plans",
        json={"title": "Block", "goal": "FTP", "weeks": 2, "start_date": monday.isoformat()},
    ).json()
    base = f"/api/athletes/{aid}/plans/{plan['id']}/comments"
    return athlete, coach, aid, plan, base, monday, seen


def test_coach_and_athlete_comment(setup):
    athlete, coach, aid, plan, base, monday, _ = setup
    tue = (monday + timedelta(days=1)).isoformat()
    r = coach.post(base, json={"body": "Keep Tuesday under 200 W, your knee needs a week.", "day": tue})
    assert r.status_code == 200, r.text
    r = athlete.post(base, json={"body": "Thanks, will do"})
    comments = r.json()
    assert [(c["author"], c["role"], c["day"]) for c in comments] == [("Cobus", "coach", tue), ("Ann", "athlete", None)]
    assert coach.post(base, json={"body": "x", "day": "2020-01-01"}).status_code == 404
    assert coach.post(base, json={"body": " "}).status_code in (200, 422)


def test_athlete_and_coach_can_edit_and_delete_any_comment(setup):
    athlete, coach, aid, plan, base, monday, _ = setup
    c = coach.post(base, json={"body": "First"}).json()[0]
    a = athlete.post(base, json={"body": "Mine"}).json()[1]
    assert all(x["can_edit"] and x["can_delete"] for x in coach.get(base).json())
    r = athlete.patch(f"{base}/{c['id']}", json={"body": "Fixed a typo"})
    edited = r.json()[0]
    assert edited["body"] == "Fixed a typo" and edited["edited_by"] == "Ann" and edited["author"] == "Cobus"
    assert coach.delete(f"{base}/{a['id']}").status_code == 200
    assert [x["body"] for x in athlete.get(base).json()] == ["Fixed a typo"]


def test_only_people_with_plan_access(setup, make_user):
    athlete, coach, aid, plan, base, monday, _ = setup
    other = make_user("o@example.com")
    assert other.get(base).status_code == 404 and other.post(base, json={"body": "hi"}).status_code == 404
    narrow = make_user("n@example.com")
    g = athlete.post("/api/grants", json={"coach_email": "n@example.com", "scopes": ["activities"]}).json()
    narrow.post(f"/api/grants/{g['id']}/accept")
    assert narrow.post(base, json={"body": "hi"}).status_code == 404


def test_comments_are_emailed(setup, make_user, fake_smtp, monkeypatch):  # noqa: F811
    athlete, coach, aid, plan, base, monday, _ = setup
    _configure(make_user("admin@example.com"))
    sent = []

    async def capture(to, subject, text):
        sent.append((to, subject, text))

    monkeypatch.setattr("app.notifications.mailer.send", capture)
    coach.post(base, json={"body": "Add a rest day"})
    athlete.post(base, json={"body": "OK"})
    assert [(t, s) for t, s, _ in sent] == [
        ("a@example.com", "CoachQuest: Cobus commented on Block"),
        ("c@example.com", "CoachQuest: Ann commented on Block"),
    ]
    assert "Add a rest day" in sent[0][2] and f"/athletes/{aid}/plans/{plan['id']}" in sent[0][2]
    # Comment emails have their own switch, separate from the sharing emails.
    athlete.patch("/api/me", json={"notify_comments": False})
    coach.post(base, json={"body": "One more thing"})
    assert len(sent) == 2
    assert athlete.get("/api/auth/me").json()["notify_sharing"] is True


def test_replan_reads_the_comments(setup):
    athlete, coach, aid, plan, base, monday, seen = setup
    coach.post(base, json={"body": "No intervals this week"})
    athlete.post(base, json={"body": "Travelling Thursday"})
    r = coach.post(f"/api/athletes/{aid}/plans/{plan['id']}/replan", json={"reason": ""})
    assert r.status_code == 200, r.text
    assert seen["request"]["replan"]["comments"] == [
        {"by": "coach", "day": None, "text": "No intervals this week"},
        {"by": "athlete", "day": None, "text": "Travelling Thursday"},
    ]


def test_cleanup(setup):
    athlete, coach, aid, plan, base, monday, _ = setup
    coach.post(base, json={"body": "Note"})
    cid = coach.get("/api/auth/me").json()["id"]
    with SessionLocal() as db:
        accounts.delete_account(db, db.get(User, cid))
        assert db.query(PlanComment).one().author_id is None  # stays on the athlete's plan, unsigned
    assert athlete.get(base).json()[0]["author"] == "Former user"
    athlete.delete(f"/api/athletes/me/plans/{plan['id']}")
    with SessionLocal() as db:
        assert db.query(PlanComment).count() == 0
