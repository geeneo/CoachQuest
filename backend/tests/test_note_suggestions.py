"""AI-suggested athlete notes: the AI proposes, a person accepts (edited or not) or dismisses."""

import json

from test_ai_coach import FakeClient, _msg, athlete  # noqa: F401  (fixture)

from app import accounts, assessments, athlete_notes, coach_chat
from app.db import AthleteNote, NoteSuggestion, SessionLocal, User


def test_chat_suggests_a_note(athlete, monkeypatch):  # noqa: F811
    p, uid = athlete
    fake = FakeClient(
        [
            _msg(
                [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "suggest_note",
                        "input": {"category": "health", "note": "Left knee sore after long climbs"},
                    }
                ],
                "tool_use",
            ),
            _msg([{"type": "text", "text": "I've suggested a note about your knee."}], "end_turn"),
        ]
    )
    monkeypatch.setattr(coach_chat, "claude_client", lambda db, viewer: fake)
    r = p.post("/api/athletes/me/coach/chats", json={"question": "My knee hurts on long climbs"})
    assert r.status_code == 200, r.text
    result = fake.requests[1]["messages"][-1]["content"][0]
    assert not result["is_error"] and "Saved as a suggestion" in json.loads(result["content"])
    assert any(t["name"] == "suggest_note" for t in fake.requests[0]["tools"])
    assert "suggest a new athlete note" in fake.requests[0]["system"][0]["text"]
    s = p.get("/api/athletes/me/notes").json()["suggestions"]
    assert [(x["category"], x["body"], x["source"]) for x in s] == [
        ("health", "Left knee sore after long climbs", "chat")
    ]


def test_accept_edit_dismiss_and_no_repeats(make_user):
    a = make_user("a@example.com", "Ann")
    coach = make_user("c@example.com", "Cobus")
    viewer = make_user("v@example.com", "Vera")
    aid = a.get("/api/auth/me").json()["id"]
    for email, scopes, who in (("c@example.com", ["plans"], coach), ("v@example.com", ["activities"], viewer)):
        g = a.post("/api/grants", json={"coach_email": email, "scopes": scopes}).json()
        who.post(f"/api/grants/{g['id']}/accept")
    with SessionLocal() as db:
        ann = db.get(User, aid)
        assert "Saved" in athlete_notes.suggest(db, aid, ann, "equipment", "Power meter on road bike only", "weekly")
        assert "Saved" in athlete_notes.suggest(db, aid, ann, "life", "Night shifts every second week", "chat")
        assert "Saved" in athlete_notes.suggest(db, aid, ann, "works", "Loves long Z2 indoors", "chat")
        assert "already" in athlete_notes.suggest(db, aid, ann, "life", "night shifts  every second week.", "chat")
        assert "Not saved" in athlete_notes.suggest(db, aid, ann, "mood", "Happy", "chat")
    url = f"/api/athletes/{aid}/notes"
    s = coach.get(url).json()["suggestions"]
    assert len(s) == 3
    # Accept as is, accept edited, dismiss.
    coach.post(f"{url}/suggestions/{s[0]['id']}", json={"accept": True})
    r = a.post(
        f"/api/athletes/me/notes/suggestions/{s[1]['id']}",
        json={"accept": True, "body": "Night shifts every second week (Mon-Thu)", "category": "life"},
    ).json()
    r = a.post(f"/api/athletes/me/notes/suggestions/{s[2]['id']}", json={"accept": False}).json()
    assert r["suggestions"] == []
    assert sorted((n["body"], n["author"]) for n in r["notes"]) == [
        ("Night shifts every second week (Mon-Thu)", "Ann"),
        ("Power meter on road bike only", "Cobus"),
    ]
    assert coach.post(f"{url}/suggestions/{s[2]['id']}", json={"accept": True}).status_code == 404  # decided
    assert viewer.get(url).status_code in (403, 404)
    with SessionLocal() as db:
        # A dismissed suggestion isn't made again, and the AI is told about it.
        assert "already" in athlete_notes.suggest(db, aid, None, "works", "Loves long Z2 indoors", "chat")
        assert athlete_notes.dismissed_for_ai(db, aid) == ["Loves long Z2 indoors"]
        accounts.delete_account(db, db.get(User, aid))
        db.commit()
        assert db.query(NoteSuggestion).count() == 0 and db.query(AthleteNote).count() == 0


def test_too_many_waiting(make_user, monkeypatch):
    a = make_user("a@example.com")
    aid = a.get("/api/auth/me").json()["id"]
    monkeypatch.setattr(athlete_notes, "MAX_PENDING", 1)
    with SessionLocal() as db:
        athlete_notes.suggest(db, aid, None, "other", "First fact", "chat")
        assert "already waiting" in athlete_notes.suggest(db, aid, None, "other", "Second fact", "chat")


def test_weekly_review_suggests_notes(athlete, monkeypatch):  # noqa: F811
    p, uid = athlete
    seen = {}

    async def fake_ask(db, viewer, ath, system, content, output_format=None, kind=None):
        seen["format"], seen["system"] = output_format, system
        return (
            json.dumps(
                {
                    "review_md": "## How the week went\nGood.",
                    "note_suggestions": [{"category": "works", "note": "Responds well to sweet spot"}],
                }
            ),
            "claude-test",
        )

    monkeypatch.setattr(assessments, "ask_claude", fake_ask)
    r = p.post("/api/athletes/me/coach/assessments", json={"kind": "weekly"}).json()
    assert r["content_md"] == "## How the week went\nGood."
    assert seen["format"]["schema"]["required"] == ["review_md", "note_suggestions"]
    assert "`dismissed_note_suggestions`" in seen["system"]
    s = p.get("/api/athletes/me/notes").json()["suggestions"]
    assert [(x["body"], x["source"]) for x in s] == [("Responds well to sweet spot", "weekly")]
    assert assessments._weekly_answer("plain text") == ("plain text", [])
