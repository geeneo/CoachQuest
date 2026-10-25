import copy
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from anthropic.types.beta import BetaMessage

from app import assessments, coach_chat
from app.db import AccessLog, Activity, AiCall, SessionLocal, WellnessDay


def _w(days_ago, hrv=70, rhr=48, sleep_h=7.5, bb=80):
    return SimpleNamespace(
        day=date.today() - timedelta(days=days_ago),
        hrv_ms=hrv,
        resting_hr=rhr,
        sleep_s=int(sleep_h * 3600),
        sleep_score=80,
        body_battery_max=bb,
    )


def test_readiness_go_easy_rest():
    base = [_w(i) for i in range(30, 0, -1)]
    assert assessments.readiness_verdict(base + [_w(0)], 0)[0] == "go"
    verdict, reasons, _ = assessments.readiness_verdict(base + [_w(0, hrv=63)], 0)
    assert verdict == "easy" and "HRV" in reasons[0]
    assert assessments.readiness_verdict(base + [_w(0, hrv=55)], 0)[0] == "rest"
    assert assessments.readiness_verdict(base + [_w(0, rhr=56)], 0)[0] == "rest"
    three = base + [_w(0, hrv=64, sleep_h=5, bb=30)]
    assert assessments.readiness_verdict(three, 0)[0] == "rest"
    verdict, reasons, numbers = assessments.readiness_verdict([], -35)
    assert verdict == "easy" and numbers["wellness"] == "no data from last night"


@pytest.fixture()
def athlete(make_user):
    p = make_user("a@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    with SessionLocal() as db:
        for i in range(40):
            db.add(
                WellnessDay(user_id=uid, day=date.today() - timedelta(days=i), hrv_ms=70 if i else 55, resting_hr=48)
            )
            if i % 2:
                db.add(
                    Activity(
                        user_id=uid,
                        source="strava",
                        external_id=str(i),
                        name=f"Ride {i}",
                        sport="Ride",
                        start_time=datetime.now() - timedelta(days=i),
                        duration_s=7200,
                        distance_m=60000,
                        elevation_m=700,
                        tss=90,
                        norm_power=200,
                    )
                )
        db.commit()
    return p, uid


def test_daily_assessment_uses_code_verdict(athlete, monkeypatch):
    p, uid = athlete
    seen = {}

    async def fake_ask(db, viewer, ath, system, content, output_format=None):
        seen["system"], seen["content"] = system, content
        return "**Rest today.** HRV is well down.", "claude-test"

    monkeypatch.setattr(assessments, "ask_claude", fake_ask)
    r = p.post("/api/athletes/me/coach/assessments", json={"kind": "daily"})
    assert r.status_code == 200, r.text
    assert r.json()["verdict"] == "rest" and '"verdict": "rest"' in seen["content"]
    overview = p.get("/api/athletes/me/coach").json()
    assert overview["latest_daily"]["verdict"] == "rest"
    assert overview["progress"]["ctl"]["now"] > 0


def test_weekly_assessment_facts(athlete, monkeypatch):
    p, _ = athlete
    seen = {}

    async def fake_ask(db, viewer, ath, system, content, output_format=None):
        seen["content"] = content
        return "## How the week went\nGood.", "claude-test"

    monkeypatch.setattr(assessments, "ask_claude", fake_ask)
    r = p.post("/api/athletes/me/coach/assessments", json={"kind": "weekly"})
    assert r.status_code == 200 and r.json()["kind"] == "weekly"
    assert '"volume"' in seen["content"] and '"wellness"' in seen["content"]


def test_monthly_limit(athlete, make_user):
    p, uid = athlete
    admin = make_user("admin@example.com")
    admin.request(
        "PUT",
        "/api/admin/settings",
        json={"values": {"ai_monthly_limit": "2", "anthropic_api_key": "sk-ant-" + "x" * 30}},
    )
    with SessionLocal() as db:
        for _ in range(2):
            db.add(AiCall(user_id=uid, athlete_id=uid, model="m", status="ok", latency_ms=1))
        db.commit()
    r = p.post("/api/athletes/me/coach/assessments", json={"kind": "daily"})
    assert r.status_code == 429 and "this month" in r.json()["detail"]
    usage = admin.get("/api/admin/ai-usage").json()
    assert usage["limit"] == 2 and usage["users"][0]["calls"] == 2


def _msg(content, stop):
    return BetaMessage.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-test",
            "content": content,
            "stop_reason": stop,
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
    )


class FakeClient:
    def __init__(self, replies):
        self.replies, self.requests = list(replies), []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    async def create(self, **kw):
        self.requests.append(copy.deepcopy(kw))  # the loop keeps appending to the same list
        return self.replies.pop(0)


def test_chat_uses_tools_within_scope(athlete, make_user, monkeypatch):
    p, uid = athlete
    coach = make_user("c@example.com")
    g = p.post("/api/grants", json={"coach_email": "c@example.com", "scopes": ["activities", "plans"]}).json()
    coach.post(f"/api/grants/{g['id']}/accept")
    fake = FakeClient(
        [
            _msg(
                [
                    {"type": "tool_use", "id": "t1", "name": "get_wellness", "input": {"days": 7}},
                    {"type": "tool_use", "id": "t2", "name": "get_volume_summary", "input": {"days": 7}},
                ],
                "tool_use",
            ),
            _msg([{"type": "text", "text": "You rode 4 times this week."}], "end_turn"),
        ]
    )
    monkeypatch.setattr(coach_chat, "claude_client", lambda db, viewer: fake)
    r = coach.post(f"/api/athletes/{uid}/coach/chats", json={"question": "How was my week?"})
    assert r.status_code == 200, r.text
    assert [m["text"] for m in r.json()["messages"]] == ["How was my week?", "You rode 4 times this week."]
    results = fake.requests[1]["messages"][-1]["content"]
    wellness, volume = results
    assert wellness["is_error"] and "not shared" in wellness["content"]  # coach has no wellness scope
    assert not volume["is_error"] and '"distance_km"' in volume["content"]
    with SessionLocal() as db:
        assert db.query(AccessLog).filter_by(viewer_id=coach.get("/api/auth/me").json()["id"]).count() >= 1

    # Continue the conversation: history (including the tool turns) is sent back unchanged.
    fake.replies = [_msg([{"type": "text", "text": "Keep Tuesday easy."}], "end_turn")]
    chat_id = r.json()["id"]
    r2 = coach.post(f"/api/athletes/{uid}/coach/chats", json={"question": "And next week?", "chat_id": chat_id})
    assert r2.json()["messages"][-1]["text"] == "Keep Tuesday easy."
    assert len(fake.requests[2]["messages"]) == 5  # q, tool_use, tool_result, answer, new q


def test_chat_is_private_to_the_viewer(athlete, make_user, monkeypatch):
    p, uid = athlete
    fake = FakeClient([_msg([{"type": "text", "text": "Hi"}], "end_turn")])
    monkeypatch.setattr(coach_chat, "claude_client", lambda db, viewer: fake)
    chat_id = p.post("/api/athletes/me/coach/chats", json={"question": "Hello"}).json()["id"]
    other = make_user("x@example.com")
    assert (
        other.post(f"/api/athletes/{uid}/coach/chats", json={"question": "Hi", "chat_id": chat_id}).status_code == 404
    )


def test_ai_settings(make_user):
    p = make_user("a@example.com")
    assert p.get("/api/athletes/me/coach").json()["ai_settings"] == {"daily": False, "weekly": False, "email": False}
    p.request("PUT", "/api/me/ai-settings", json={"daily": True, "weekly": True, "email": False})
    assert p.get("/api/athletes/me/coach").json()["ai_settings"]["daily"] is True
