"""Fewer AI tokens (caching, cheaper short jobs, no pointless calls) and the admin's per-user AI controls."""

import asyncio
import copy
from types import SimpleNamespace

from anthropic.types.beta import BetaMessage
from test_ai_coach import FakeClient, _msg, athlete  # noqa: F401  (fixture)

from app import assessments, coach, coach_chat, runtime
from app.db import AiCall, AuthEvent, SessionLocal, User, WellnessDay


def _usage_msg(text, read=0, write=0):
    m = _msg([{"type": "text", "text": text}], "end_turn")
    return BetaMessage.model_validate(
        {
            **m.model_dump(),
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_read_input_tokens": read,
                "cache_creation_input_tokens": write,
            },
        }
    )


class FakeStreamClient:
    """Stands in for client.beta.messages.stream(...) in ask_claude."""

    def __init__(self, text):
        self.text, self.requests = text, []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self.stream))

    def stream(self, **kw):
        self.requests.append(copy.deepcopy(kw))
        outer = self

        class Ctx:
            async def __aenter__(self):
                return SimpleNamespace(get_final_message=self.final)

            async def __aexit__(self, *a):
                return False

            async def final(self):
                return _usage_msg(outer.text, read=900, write=0)

        return Ctx()


def test_ask_claude_caches_and_uses_short_settings(athlete, monkeypatch):  # noqa: F811
    p, uid = athlete
    fake = FakeStreamClient("**Go.**")
    monkeypatch.setattr(coach, "claude_client", lambda db, viewer: fake)
    monkeypatch.setitem(runtime._overrides, "anthropic_model_short", "claude-haiku-5-5")
    monkeypatch.setitem(runtime._overrides, "anthropic_effort_short", "low")
    r = p.post("/api/athletes/me/coach/assessments", json={"kind": "daily"})
    assert r.status_code == 200, r.text
    req = fake.requests[0]
    assert req["model"] == "claude-haiku-5-5" and req["output_config"]["effort"] == "low"
    assert req["system"][0]["cache_control"] == {"type": "ephemeral"} and "readiness" in req["system"][0]["text"]
    assert "cache_control" not in req["system"][1]  # the per-viewer date format line isn't cached
    content = req["messages"][0]["content"]
    assert "\n" not in content and '"verdict":' in content  # compact JSON
    with SessionLocal() as db:
        call = db.query(AiCall).one()
        assert (call.kind, call.cache_read_tokens, call.input_tokens) == ("readiness", 900, 100)
    # Asking again with nothing new returns the same note without calling the AI.
    again = p.post("/api/athletes/me/coach/assessments", json={"kind": "daily"}).json()
    assert again["unchanged"] is True and again["id"] == r.json()["id"] and len(fake.requests) == 1
    # New data: a new note.
    with SessionLocal() as db:
        db.query(WellnessDay).filter_by(user_id=uid).delete()
        db.commit()
    p.post("/api/athletes/me/coach/assessments", json={"kind": "daily"})
    assert len(fake.requests) == 2


def test_plans_keep_the_main_settings(monkeypatch):
    monkeypatch.setitem(runtime._overrides, "anthropic_model", "claude-opus-5-5")
    monkeypatch.setitem(runtime._overrides, "anthropic_effort", "high")
    monkeypatch.setitem(runtime._overrides, "anthropic_model_short", "")
    assert coach.model_for("plan") == ("claude-opus-5-5", "high")
    assert coach.model_for("chat")[0] == "claude-opus-5-5"  # empty short model: same as plans


def test_chat_caches_and_has_a_length_cap(athlete, monkeypatch):  # noqa: F811
    p, uid = athlete
    fake = FakeClient([_usage_msg("Hi", read=0, write=3000)])
    monkeypatch.setattr(coach_chat, "claude_client", lambda db, viewer: fake)
    r = p.post("/api/athletes/me/coach/chats", json={"question": "Hello"})
    req = fake.requests[0]
    assert req["cache_control"] == {"type": "ephemeral"}
    assert req["system"][0]["text"] == coach_chat.SYSTEM and req["system"][0]["cache_control"]
    assert "Today is" in req["system"][1]["text"]
    with SessionLocal() as db:
        call = db.query(AiCall).one()
        assert call.kind == "chat" and call.cache_write_tokens == 3000
    chat_id = r.json()["id"]
    monkeypatch.setattr(coach_chat, "MAX_QUESTIONS", 1)
    r = p.post("/api/athletes/me/coach/chats", json={"question": "More?", "chat_id": chat_id})
    assert r.status_code == 409 and "new chat" in r.json()["detail"]


def test_smaller_lookups(athlete):  # noqa: F811
    p, uid = athlete
    with SessionLocal() as db:
        acts = coach_chat.run_tool(db, db.get(User, uid), uid, "get_activities", {"days": 30})
        assert set(acts[0]) <= {"date", "type", "name", "min", "km", "elev_m", "tss", "avg_hr", "np_w", "note", "race"}
        rows = coach_chat.run_tool(db, db.get(User, uid), uid, "get_fitness", {"days": 365})
    daily = [r for r in rows if "day" in r]
    weekly = [r for r in rows if "week_from" in r]
    assert len(daily) == coach_chat.DAILY_FITNESS_DAYS and 40 <= len(weekly) <= 46  # not 365 rows


def test_scheduled_notes_skip_accounts_without_data(athlete, make_user, monkeypatch):  # noqa: F811
    p, uid = athlete
    coach_only = make_user("coach@example.com")
    paused = make_user("paused@example.com")
    for who in (p, coach_only, paused):
        who.request("PUT", "/api/me/ai-settings", json={"daily": True, "weekly": False, "email": False})
    with SessionLocal() as db:
        db.query(User).filter_by(email="paused@example.com").one().ai_disabled = True
        db.commit()
    called = []

    async def fake_create(db, viewer, ath, kind, scheduled=False):
        called.append(viewer.email)
        return SimpleNamespace(verdict="go", content_md="")

    monkeypatch.setattr(assessments, "create", fake_create)
    asyncio.run(assessments.run_scheduled("daily"))
    assert called == ["a@example.com"]


def test_admin_turns_ai_off_and_sets_a_limit(athlete, make_user, monkeypatch):  # noqa: F811
    p, uid = athlete
    admin = make_user("admin@example.com", "Admin")
    monkeypatch.setitem(runtime._overrides, "anthropic_api_key", "sk-ant-" + "x" * 30)
    monkeypatch.setitem(runtime._overrides, "ai_monthly_limit", "200")
    url = f"/api/admin/users/{uid}"
    admin.request("PATCH", url, json={"ai_disabled": True})
    r = p.post("/api/athletes/me/coach/assessments", json={"kind": "daily"})
    assert r.status_code == 403 and "paused the AI coach" in r.json()["detail"]
    admin.request("PATCH", url, json={"ai_disabled": False, "ai_monthly_limit": 1})
    with SessionLocal() as db:
        db.add(AiCall(user_id=uid, athlete_id=uid, model="claude-opus-5-5", status="ok", latency_ms=1, kind="plan"))
        db.commit()
    r = p.post("/api/athletes/me/coach/assessments", json={"kind": "daily"})
    assert r.status_code == 429 and "1 AI coach requests" in r.json()["detail"]
    row = next(u for u in admin.get("/api/admin/users").json() if u["id"] == uid)
    assert row["ai_monthly_limit"] == 1 and row["ai_limit"] == 1 and "AI limit nearly used" in row["flags"]
    admin.request("PATCH", url, json={"ai_monthly_limit": None})  # back to the site's limit
    row = next(u for u in admin.get("/api/admin/users").json() if u["id"] == uid)
    assert row["ai_monthly_limit"] is None and row["ai_limit"] == 200
    with SessionLocal() as db:
        events = [e.event for e in db.query(AuthEvent).filter(AuthEvent.event.like("admin_ai%"))]
    assert events == ["admin_ai_off", "admin_ai_on", "admin_ai_limit", "admin_ai_limit"]
    assert p.request("PATCH", url, json={"ai_disabled": True}).status_code in (401, 403)


def test_admin_sees_ai_use_by_kind_and_athlete(make_user):
    admin = make_user("admin@example.com", "Admin")
    mike = make_user("mike@example.com", "Mike")
    ann = make_user("ann@example.com", "Ann")
    mid, aid = (x.get("/api/auth/me").json()["id"] for x in (mike, ann))
    with SessionLocal() as db:
        for kind, athlete_id, status in (("plan", aid, "ok"), ("chat", aid, "end_turn"), ("chat", mid, "api_500")):
            db.add(
                AiCall(
                    user_id=mid,
                    athlete_id=athlete_id,
                    model="claude-opus-5-5",
                    status=status,
                    latency_ms=1,
                    kind=kind,
                    input_tokens=1_000_000,
                    output_tokens=0,
                    cache_read_tokens=1_000_000,
                )
            )
        db.commit()
    row = next(u for u in admin.get("/api/admin/users").json() if u["id"] == mid)
    assert row["ai_month"] == {"calls": 3, "tokens": 6_000_000, "for_others": 2}
    ai = admin.get(f"/api/admin/users/{mid}/detail").json()["ai"]
    assert ai["by_kind"]["chat"]["calls"] == 2 and ai["by_kind"]["chat"]["failed"] == 1
    assert ai["by_athlete"]["Ann"]["calls"] == 2 and ai["by_athlete"]["themselves"]["calls"] == 1
    assert ai["cost_usd"] == 13.2 and ai["cost_complete"]  # 3 x ($4 input + $0.40 cache reads)
