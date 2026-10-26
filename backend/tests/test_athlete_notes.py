from datetime import date, timedelta

import pytest

from app import accounts, assessments, athlete_notes, coach
from app.db import AthleteNote, SessionLocal, User


@pytest.fixture()
def people(make_user):
    athlete = make_user("a@example.com", "Ann")
    cobus = make_user("c@example.com", "Cobus")
    viewer = make_user("v@example.com", "Vera")  # activities only
    aid = athlete.get("/api/auth/me").json()["id"]
    for email, scopes, who in (("c@example.com", ["plans"], cobus), ("v@example.com", ["activities"], viewer)):
        g = athlete.post("/api/grants", json={"coach_email": email, "scopes": scopes}).json()
        who.post(f"/api/grants/{g['id']}/accept")
    return athlete, cobus, viewer, aid, f"/api/athletes/{aid}/notes"


def test_shared_notes_with_history(people):
    athlete, cobus, viewer, aid, url = people
    r = athlete.post("/api/athletes/me/notes", json={"category": "health", "body": "Left knee sore after long climbs"})
    n = r.json()["notes"][0]
    assert n["role"] == "athlete" and n["current"]
    assert n["review_by"] == (date.today() + timedelta(weeks=6)).isoformat()  # health notes come up for review
    assert r.json()["categories"]["life"] == "Life & schedule"
    n = cobus.request("PATCH", f"{url}/{n['id']}", json={"body": "Left knee fine on the flat, sore on climbs"}).json()[
        "notes"
    ][0]
    assert n["updated_by"] == "Cobus" and n["history"][0]["body"] == "Left knee sore after long climbs"
    eq = cobus.post(url, json={"category": "equipment", "body": "Power meter on the road bike only"}).json()["notes"]
    assert eq[1]["review_by"] is None and eq[1]["role"] == "coach"
    assert cobus.post(url, json={"category": "mood", "body": "Happy"}).status_code == 422
    assert cobus.post(url, json={"category": "other", "body": "x" * 301}).status_code == 422
    assert viewer.get(url).status_code in (403, 404)  # no plans scope, no notes (health is sensitive)
    assert cobus.request("DELETE", f"{url}/{eq[1]['id']}").json()["notes"][0]["category"] == "health"


def test_review_by_and_confirm(people):
    athlete, cobus, viewer, aid, url = people
    old = (date.today() - timedelta(days=1)).isoformat()
    nid = cobus.post(url, json={"category": "health", "body": "Cold last week", "review_by": old}).json()["notes"][0][
        "id"
    ]
    cobus.post(url, json={"category": "life", "body": "Night shifts every second week"})
    with SessionLocal() as db:
        assert [n["note"] for n in athlete_notes.for_ai(db, aid, date.today())] == ["Night shifts every second week"]
    n = athlete.post(f"/api/athletes/me/notes/{nid}/confirm").json()["notes"][0]
    assert n["current"] and n["review_by"] == (date.today() + timedelta(weeks=6)).isoformat()
    with SessionLocal() as db:
        ai = athlete_notes.for_ai(db, aid, date.today())
    assert [n["category"] for n in ai] == ["Health", "Life & schedule"]  # grouped by category
    assert ai[0] == {"category": "Health", "note": "Cold last week", "by": "coach", "since": date.today().isoformat()}


def test_the_ai_gets_them(people):
    athlete, cobus, viewer, aid, url = people
    cobus.post(url, json={"category": "works", "body": "Responds well to sweet spot"})
    with SessionLocal() as db:
        ann = db.get(User, aid)
        expected = athlete_notes.for_ai(db, aid, date.today())
        assert coach.build_facts(db, ann, {"plans"}, {})["athlete_notes"] == expected
        assert "athlete_notes" not in coach.build_facts(db, ann, {"activities"}, {})
        assert assessments.readiness_facts(db, ann, {"plans"}, date.today())["athlete_notes"] == expected
        monday = date.today() - timedelta(days=date.today().weekday() + 7)
        assert assessments.weekly_facts(db, ann, {"plans"}, monday)["athlete_notes"] == expected
    for prompt in (coach.SYSTEM_PROMPT, assessments.READINESS_PROMPT, assessments.WEEKLY_PROMPT):
        assert "`athlete_notes`" in prompt and "context, not rules" in prompt


def test_limit_and_cleanup(people, monkeypatch):
    athlete, cobus, viewer, aid, url = people
    monkeypatch.setattr(athlete_notes, "MAX_CURRENT", 2)
    cobus.post(url, json={"category": "other", "body": "One"})
    athlete.post("/api/athletes/me/notes", json={"category": "other", "body": "Two"})
    assert cobus.post(url, json={"category": "other", "body": "Three"}).status_code == 409
    with SessionLocal() as db:
        accounts.delete_account(db, db.get(User, cobus.get("/api/auth/me").json()["id"]))
        db.commit()
        assert {n.author_id for n in db.query(AthleteNote)} == {None, aid}
        accounts.delete_account(db, db.get(User, aid))
        db.commit()
        assert db.query(AthleteNote).count() == 0
