"""When no coach answers: after the waiting time (or when the day comes first) the athlete may decide."""

import asyncio
from datetime import date, timedelta

from test_mail import _configure, fake_smtp  # noqa: F401  (fixture)
from test_phase3 import _week

from app import plan_approval
from app.db import Plan, SessionLocal, User, utcnow


def _team(make_user, monkeypatch, start):
    async def fake_generate(db, viewer, athlete, facts):
        return {"summary_md": "Plan", "weeks": [_week(), _week()]}, "claude-test"

    monkeypatch.setattr("app.routers.plans.generate_plan", fake_generate)
    athlete = make_user("a@example.com", "Ann")
    cobus = make_user("c@example.com", "Cobus")
    aid = athlete.get("/api/auth/me").json()["id"]
    g = athlete.post("/api/grants", json={"coach_email": "c@example.com", "scopes": ["plans"]}).json()
    cobus.post(f"/api/grants/{g['id']}/accept")
    p = athlete.post(
        "/api/athletes/me/plans",
        json={"without_data": True, "title": "B", "goal": "g", "weeks": 2, "start_date": start.isoformat()},
    ).json()
    return athlete, cobus, aid, p


def _age(plan_id, hours):
    """Pretend the plan was made `hours` ago."""
    with SessionLocal() as db:
        p = db.get(Plan, plan_id)
        at = (utcnow() - timedelta(hours=hours)).isoformat(timespec="seconds")
        p.history = [{**h, "at": at} for h in p.history]
        db.commit()


def test_athlete_decides_after_the_waiting_time(make_user, monkeypatch):
    far = date.today() + timedelta(days=14 - date.today().weekday())  # well after 48 hours
    athlete, cobus, aid, p = _team(make_user, monkeypatch, far)
    url = f"/api/athletes/me/plans/{p['id']}"
    r = athlete.get(url).json()
    assert r["can_approve"] is False and r["athlete_decides_at"]
    assert athlete.post(f"{url}/approve").status_code == 403
    _age(p["id"], 49)
    r = athlete.get(url).json()
    assert r["can_approve"] is True
    r = athlete.post(f"{url}/approve").json()
    assert r["approval"] == "approved" and "by the athlete" in r["history"][-1]["note"]


def test_the_day_comes_first(make_user, monkeypatch):
    soon = date.today() + timedelta(days=1)  # starts before 48 hours are up
    athlete, cobus, aid, p = _team(make_user, monkeypatch, soon)
    assert athlete.get(f"/api/athletes/me/plans/{p['id']}").json()["can_approve"] is True


def test_never_and_coach_choice(make_user, monkeypatch):
    far = date.today() + timedelta(days=14 - date.today().weekday())
    athlete, cobus, aid, p = _team(make_user, monkeypatch, far)
    setting = f"/api/athletes/{aid}/plans/approval-setting"
    assert cobus.request("PUT", setting, json={"wait_hours": 5}).status_code == 422
    assert cobus.request("PUT", setting, json={"wait_hours": 0}).json()["wait_hours"] == 0
    _age(p["id"], 500)
    r = athlete.get(f"/api/athletes/me/plans/{p['id']}").json()
    assert r["can_approve"] is False and r["athlete_decides_at"] is None
    cobus.request("PUT", setting, json={"wait_hours": 24})
    assert athlete.get(f"/api/athletes/me/plans/{p['id']}").json()["can_approve"] is True


def test_coaches_reminded_halfway_once(make_user, monkeypatch, fake_smtp):  # noqa: F811
    far = date.today() + timedelta(days=14 - date.today().weekday())
    _configure(make_user("admin@example.com"))
    athlete, cobus, aid, p = _team(make_user, monkeypatch, far)
    sent = []

    async def capture(to, subject, text):
        sent.append((to, subject))

    monkeypatch.setattr("app.notifications.mailer.send", capture)
    asyncio.run(plan_approval.remind_job())
    assert sent == []  # not halfway yet
    _age(p["id"], 25)
    asyncio.run(plan_approval.remind_job())
    asyncio.run(plan_approval.remind_job())
    assert sent == [("c@example.com", "CoachQuest: Reminder: Ann's plan waits for your approval")]
    with SessionLocal() as db:
        assert db.get(User, aid).approval_wait_hours is None  # the default, 48 h
