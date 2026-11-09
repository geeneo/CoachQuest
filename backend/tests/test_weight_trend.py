"""Weight from occasional weigh-ins: the trend, the tile, and the weigh-in reminder (weight.py)."""

import json
from datetime import date, timedelta

from app import assessments, evening, weight
from app.db import SessionLocal, User, WellnessDay


def test_trend_follows_changes_and_ignores_swings():
    d = date(2026, 9, 1)
    # A kilo of water up and down, with gaps: the trend barely moves.
    t = weight.trend([(d, 74.0), (d + timedelta(days=2), 75.5), (d + timedelta(days=3), 73.8)])
    assert 74.0 <= t[d + timedelta(days=3)] <= 74.4
    # A weigh-in a week later counts for more than one a day later.
    late = weight.trend([(d, 74.0), (d + timedelta(days=7), 72.0)])[d + timedelta(days=7)]
    soon = weight.trend([(d, 74.0), (d + timedelta(days=1), 72.0)])[d + timedelta(days=1)]
    assert late < soon < 74.0
    assert weight.trend([]) == {}


def _weigh(uid, days_ago, kg, **other):
    with SessionLocal() as db:
        db.add(WellnessDay(user_id=uid, day=date.today() - timedelta(days=days_ago), weight_kg=kg, **other))
        db.commit()


def test_trend_on_the_chart_and_the_tile(make_user):
    p = make_user("a@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    assert p.get("/api/athletes/me/weight").json() is None
    for days_ago, kg in ((60, 76.0), (40, 75.4), (20, 74.6), (9, 73.7)):
        _weigh(uid, days_ago, kg)
    for days_ago in (6, 3, 0):
        _weigh(uid, days_ago, None, resting_hr=44)
    rows = p.get("/api/athletes/me/wellness?days=7").json()
    # No weigh-in in these 7 days: the trend as it stood still spans the period.
    assert rows[0]["weight_trend"] == rows[-1]["weight_trend"] and rows[0]["weight_trend"] is not None
    rows = p.get("/api/athletes/me/wellness?days=30").json()
    assert [r["weight_trend"] is not None for r in rows if r["weight_kg"]] == [True, True]
    tile = p.get("/api/athletes/me/weight").json()
    assert tile["latest_kg"] == 73.7 and tile["days_since"] == 9 and tile["weigh_ins_30d"] == 2
    assert tile["change_30d"] < 0 and 73.7 < tile["trend_kg"] < 76


def test_weigh_in_reminder(make_user, monkeypatch):
    p = make_user("a@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    today = date.today()
    s = p.get("/api/athletes/me/coach").json()["ai_settings"]
    p.request("PUT", "/api/me/ai-settings", json={**s, "weigh_day": today.weekday()})
    with SessionLocal() as db:
        user = db.get(User, uid)
        assert weight.reminder(db, user, today).startswith("Weigh-in day")
        assert weight.reminder(db, user, today + timedelta(days=1)).startswith("Yesterday's weigh-in was missed")
        assert weight.reminder(db, user, today + timedelta(days=2)) is None
    _weigh(uid, 0, 74.0)
    with SessionLocal() as db:
        user = db.get(User, uid)
        assert weight.reminder(db, user, today) is None  # weighed already
        assert weight.reminder(db, user, today + timedelta(days=1)) is None
    # In the morning note's facts, and the night before in the evening preview.
    p.request("PUT", "/api/me/ai-settings", json={**s, "weigh_day": (today.weekday() + 1) % 7})
    seen = {}

    async def fake_ask(db, viewer, ath, system, content, output_format=None, kind=None):
        seen["facts"] = json.loads(content)
        return "**Go.**", "claude-test"

    monkeypatch.setattr(assessments, "ask_claude", fake_ask)
    with SessionLocal() as db:
        user = db.get(User, uid)
        facts = assessments.readiness_facts(db, user, {"plans", "wellness", "fitness"}, today + timedelta(days=8))
        assert "Weigh-in day" in facts["weigh_in"]
        assert "Tomorrow is weigh-in day" in evening.markdown(evening.preview(db, user, today), user)
