from datetime import date, timedelta

import pytest
from test_mail import _configure, fake_smtp  # noqa: F401  (fixture)

from app import accounts, assessments, coach, instructions
from app.db import CoachInstruction, SessionLocal, User


@pytest.fixture()
def people(make_user):
    athlete = make_user("a@example.com", "Ann")
    cobus = make_user("c@example.com", "Cobus")
    viewer = make_user("v@example.com", "Vera")  # shares activities only
    aid = athlete.get("/api/auth/me").json()["id"]
    for email, scopes, who in (("c@example.com", ["plans"], cobus), ("v@example.com", ["activities"], viewer)):
        g = athlete.post("/api/grants", json={"coach_email": email, "scopes": scopes}).json()
        who.post(f"/api/grants/{g['id']}/accept")
    return athlete, cobus, viewer, aid, f"/api/athletes/{aid}/instructions"


def test_coach_and_athlete_manage_them(people):
    athlete, cobus, viewer, aid, url = people
    rows = cobus.post(url, json={"body": "No intervals on Mondays"}).json()
    assert rows[0]["author"] == "Cobus" and rows[0]["role"] == "coach" and rows[0]["current"]
    iid = rows[0]["id"]
    # The athlete sees and can change it; so can any coach with the plans scope.
    rows = athlete.request("PATCH", f"{url.replace(str(aid), 'me')}/{iid}", json={"active": False}).json()
    assert rows[0]["active"] is False and rows[0]["current"] is False and rows[0]["updated_by"] == "Ann"
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    rows = cobus.request("PATCH", f"{url}/{iid}", json={"active": True, "until": yesterday}).json()
    assert rows[0]["expired"] and not rows[0]["current"]
    # Without the plans scope: no access.
    assert viewer.get(url).status_code in (403, 404)
    assert viewer.post(url, json={"body": "Ride more"}).status_code in (403, 404)
    assert cobus.post(url, json={"body": "x"}).status_code == 422
    assert cobus.request("DELETE", f"{url}/{iid}").json() == []
    assert cobus.request("DELETE", f"{url}/{iid}").status_code == 404


def test_the_ai_gets_the_current_ones(people):
    athlete, cobus, viewer, aid, url = people
    cobus.post(url, json={"body": "Long rides under 4 h", "until": (date.today() + timedelta(days=30)).isoformat()})
    athlete.post(url, json={"body": "I can't train on Fridays"})
    paused = cobus.post(url, json={"body": "Paused one"}).json()[-1]["id"]
    cobus.request("PATCH", f"{url}/{paused}", json={"active": False})
    cobus.post(url, json={"body": "Old one", "until": (date.today() - timedelta(days=1)).isoformat()})
    with SessionLocal() as db:
        ann = db.get(User, aid)
        expected = [
            {
                "by": "coach",
                "instruction": "Long rides under 4 h",
                "until": (date.today() + timedelta(days=30)).isoformat(),
            },
            {"by": "athlete", "instruction": "I can't train on Fridays"},
        ]
        assert instructions.for_ai(db, aid, date.today()) == expected
        assert coach.build_facts(db, ann, {"plans"}, {})["coach_instructions"] == expected
        assert "coach_instructions" not in coach.build_facts(db, ann, {"activities"}, {})
        assert assessments.readiness_facts(db, ann, {"plans"}, date.today())["coach_instructions"] == expected
        monday = date.today() - timedelta(days=date.today().weekday() + 7)
        assert assessments.weekly_facts(db, ann, {"plans"}, monday)["coach_instructions"] == expected
    for prompt in (coach.SYSTEM_PROMPT, assessments.READINESS_PROMPT, assessments.WEEKLY_PROMPT):
        assert "`coach_instructions`" in prompt and "rank above your own judgement" in prompt


def test_emailed_and_cleaned_up(people, make_user, fake_smtp, monkeypatch):  # noqa: F811
    athlete, cobus, viewer, aid, url = people
    _configure(make_user("admin@example.com"))
    sent = []

    async def capture(to, subject, text):
        sent.append((to, subject, text))

    monkeypatch.setattr("app.notifications.mailer.send", capture)
    iid = cobus.post(url, json={"body": "Easy week"}).json()[0]["id"]
    cobus.request("PATCH", f"{url}/{iid}", json={"active": False})  # pausing alone emails nobody
    athlete.request("PATCH", f"{url}/{iid}", json={"body": "Easy week, then build"})
    assert [(t, s) for t, s, _ in sent] == [
        ("a@example.com", "CoachQuest: Cobus added a coach instruction for Ann"),
        ("c@example.com", "CoachQuest: Ann changed a coach instruction for Ann"),
    ]
    assert "Easy week" in sent[0][2]
    with SessionLocal() as db:
        accounts.delete_account(db, db.get(User, cobus.get("/api/auth/me").json()["id"]))
        db.commit()
        assert db.query(CoachInstruction).one().author_id is None
        accounts.delete_account(db, db.get(User, aid))
        db.commit()
        assert db.query(CoachInstruction).count() == 0
