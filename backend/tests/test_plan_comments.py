import os
from datetime import date, timedelta

import pytest
from test_mail import _configure, fake_smtp  # noqa: F401  (fixture)

from app import accounts
from app.db import Comment, SessionLocal, User


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
        json={"without_data": True, "title": "Block", "goal": "FTP", "weeks": 2, "start_date": monday.isoformat()},
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
        ("a@example.com", 'CoachQuest: Cobus commented on the training plan "Block"'),
        ("c@example.com", 'CoachQuest: Ann commented on the training plan "Block"'),
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
        {"by": "coach", "about": "plan", "day": None, "text": "No intervals this week"},
        {"by": "athlete", "about": "plan", "day": None, "text": "Travelling Thursday"},
    ]


def test_cleanup(setup):
    athlete, coach, aid, plan, base, monday, _ = setup
    coach.post(base, json={"body": "Note"})
    cid = coach.get("/api/auth/me").json()["id"]
    with SessionLocal() as db:
        accounts.delete_account(db, db.get(User, cid))
        assert db.query(Comment).one().author_id is None  # stays on the athlete's plan, unsigned
    assert athlete.get(base).json()[0]["author"] == "Former user"
    athlete.delete(f"/api/athletes/me/plans/{plan['id']}")
    with SessionLocal() as db:
        assert db.query(Comment).count() == 0


# ---- Comments on AI coach notes and calendar workouts ----


def _note(aid, kind="weekly", start=None):
    from app.db import Assessment

    with SessionLocal() as db:
        a = Assessment(
            athlete_id=aid,
            kind=kind,
            period_start=start or date.today() - timedelta(days=7),
            content_md="Good week.",
            facts={},
            model="claude-test",
        )
        db.add(a)
        db.commit()
        return a.id


def test_comments_on_ai_notes_and_workouts(setup, make_user, monkeypatch):
    athlete, coach, aid, plan, base, monday, _ = setup
    sent = []

    async def capture(to, subject, text):
        sent.append((to, subject, text))

    _configure(make_user("admin@example.com"))
    monkeypatch.setattr("app.notifications.mailer.send", capture)
    note = _note(aid)
    url = f"/api/athletes/{aid}/comments"
    r = coach.post(url, json={"target": "assessment", "target_id": note, "body": "Agree, but add a rest day."})
    assert r.status_code == 200 and r.json()[0]["role"] == "coach"
    assert sent[-1][0] == "a@example.com" and "weekly review" in sent[-1][1]
    assert coach.get(f"/api/athletes/{aid}/coach").json()["weekly"][0]["comments"] == 1
    day = (date.today() + timedelta(days=2)).isoformat()
    w = athlete.post(
        "/api/athletes/me/workouts",
        json={"day": day, "name": "Tempo", "steps": [{"kind": "steady", "duration_s": 1800, "power": 0.8}]},
    ).json()
    r = athlete.post(url, json={"target": "workout", "target_id": w["id"], "body": "Legs heavy, can I swap?"})
    cid = r.json()[0]["id"]
    assert sent[-1][0] == "c@example.com" and "Tempo" in sent[-1][1]
    cal = coach.get(f"/api/athletes/{aid}/calendar?start={day}&end={day}").json()
    assert cal["days"][0]["workouts"][0]["comments"] == 1
    # Everyone there can edit and delete; the list comes back after each change.
    r = coach.patch(f"{url}/{cid}", json={"body": "Legs heavy, swapped to Thursday"})
    assert r.json()[0]["edited_by"] == "Cobus"
    assert coach.get(f"{url}?target=workout&target_id={w['id']}").json()[0]["body"].startswith("Legs heavy, swapped")
    # Day-level comments are for plans only; targets must belong to the athlete.
    assert coach.post(url, json={"target": "nope", "target_id": 1, "body": "x"}).status_code == 422
    other = make_user("o@example.com")
    assert (
        other.post(
            f"/api/athletes/{aid}/comments", json={"target": "assessment", "target_id": note, "body": "x"}
        ).status_code
        == 404
    )
    mine = other.get("/api/auth/me").json()["id"]
    assert coach.post(url, json={"target": "assessment", "target_id": _note(mine), "body": "x"}).status_code == 404
    # Deleting the workout removes its comments.
    athlete.delete(f"/api/athletes/me/workouts/{w['id']}")
    with SessionLocal() as db:
        assert db.query(Comment).filter_by(target="workout").count() == 0


def test_ai_reads_comments(setup):
    from app import assessments

    athlete, coach, aid, plan, base, monday, seen = setup
    note = _note(aid, start=monday - timedelta(days=7))
    url = f"/api/athletes/{aid}/comments"
    coach.post(url, json={"target": "assessment", "target_id": note, "body": "More zone 2 next week"})
    with SessionLocal() as db:
        user = db.get(User, aid)
        facts = assessments.weekly_facts(db, user, {"plans"}, monday)
    assert facts["comments"][0]["by"] == "coach" and facts["comments"][0]["text"] == "More zone 2 next week"
    assert "weekly note" in facts["comments"][0]["about"]
    assert "`comments`" in assessments.WEEKLY_PROMPT and "`comments`" in assessments.READINESS_PROMPT
    today_note = _note(aid, kind="daily", start=date.today() - timedelta(days=1))
    athlete.post(url, json={"target": "assessment", "target_id": today_note, "body": "Slept badly"})
    with SessionLocal() as db:
        daily = assessments.readiness_facts(db, db.get(User, aid), {"plans"}, date.today())
    assert daily["comments"][-1] == {
        "by": "athlete",
        "about": f"daily note {(date.today() - timedelta(days=1)).isoformat()}",
        "day": None,
        "text": "Slept badly",
    }


@pytest.mark.skipif(
    not os.environ["DATABASE_URL"].startswith("sqlite"), reason="a one-off move on old SQLite installs only"
)
def test_old_plan_comments_move_to_the_new_table(setup):
    from sqlalchemy import text

    from app.db import engine, init_db

    athlete, coach, aid, plan, base, monday, _ = setup
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE plan_comments (id INTEGER PRIMARY KEY, plan_id INTEGER, author_id INTEGER, "
                "day DATE, body TEXT, created_at DATETIME, edited_at DATETIME)"
            )
        )
        conn.execute(
            text(
                f"INSERT INTO plan_comments (plan_id, author_id, day, body, created_at) "
                f"VALUES ({plan['id']}, {aid}, NULL, 'from before', '2026-10-25 10:00:00')"
            )
        )
    init_db()
    assert [c["body"] for c in athlete.get(base).json()] == ["from before"]
    with engine.connect() as conn:
        assert not conn.execute(text("SELECT name FROM sqlite_master WHERE name='plan_comments'")).first()
