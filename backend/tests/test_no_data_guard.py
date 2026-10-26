"""No AI calls for an athlete with no synced data; and the admin sees what each recent call was for."""

from datetime import timedelta

from test_ai_coach import FakeClient, _msg, athlete  # noqa: F401  (fixture)

from app import coach_chat
from app.db import AiCall, Plan, SessionLocal, utcnow


def test_no_data_no_ai_call(make_user, monkeypatch):
    p = make_user("coach@example.com", "Mike")
    called = []

    async def fake_generate(db, viewer, ath, facts):
        called.append(facts)
        return {"summary_md": "Plan", "weeks": []}, "claude-test"

    monkeypatch.setattr("app.routers.plans.generate_plan", fake_generate)
    monkeypatch.setattr(coach_chat, "claude_client", lambda db, viewer: called.append("chat"))
    r = p.post("/api/athletes/me/coach/assessments", json={"kind": "daily"})
    assert r.status_code == 409 and "Connect Strava or Garmin" in r.json()["detail"]
    r = p.post("/api/athletes/me/coach/chats", json={"question": "How am I doing?"})
    assert r.status_code == 409
    r = p.post("/api/athletes/me/plans", json={"title": "t", "goal": "g", "weeks": 1})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_data"
    assert called == []  # nothing reached the AI
    # A plan from goal and hours alone, after the warning.
    r = p.post("/api/athletes/me/plans", json={"title": "t", "goal": "g", "weeks": 1, "without_data": True})
    assert r.status_code == 200 and "without_data" not in r.json()["request"] and len(called) == 1


def test_athletes_with_data_still_get_answers(athlete, monkeypatch):  # noqa: F811
    p, uid = athlete
    fake = FakeClient([_msg([{"type": "text", "text": "Hi"}], "end_turn")])
    monkeypatch.setattr(coach_chat, "claude_client", lambda db, viewer: fake)
    assert p.post("/api/athletes/me/coach/chats", json={"question": "Hello"}).status_code == 200


def test_admin_sees_recent_calls_with_guessed_kind(make_user):
    admin = make_user("admin@example.com", "Admin")
    mike = make_user("mike@example.com", "Mike")
    mid = mike.get("/api/auth/me").json()["id"]
    now = utcnow()
    with SessionLocal() as db:
        # An old call (no type recorded) at the moment Mike made a plan, and one new call.
        db.add(AiCall(user_id=mid, athlete_id=mid, model="claude-opus-5-5", status="ok", latency_ms=1, at=now))
        db.add(
            Plan(
                athlete_id=mid,
                author_id=mid,
                title="Mine",
                content_md="",
                model="m",
                created_at=now + timedelta(seconds=5),
            )
        )
        db.add(
            AiCall(
                user_id=mid,
                athlete_id=mid,
                model="claude-opus-5-5",
                status="ok",
                latency_ms=1,
                kind="chat",
                input_tokens=10,
                at=now + timedelta(hours=1),
            )
        )
        db.commit()
    recent = admin.get(f"/api/admin/users/{mid}/detail").json()["ai"]["recent"]
    assert [(r["kind"], r["guessed"], r["whose"]) for r in recent] == [
        ("chat", False, "themselves"),
        ("plan", True, "themselves"),
    ]


def test_old_chat_calls_are_recognised(make_user):
    admin = make_user("admin@example.com", "Admin")
    mike = make_user("mike@example.com", "Mike")
    mid = mike.get("/api/auth/me").json()["id"]
    with SessionLocal() as db:
        db.add(AiCall(user_id=mid, athlete_id=mid, model="m", status="tool_use", latency_ms=1))
        db.commit()
    recent = admin.get(f"/api/admin/users/{mid}/detail").json()["ai"]["recent"]
    assert (recent[0]["kind"], recent[0]["guessed"]) == ("chat", True)
