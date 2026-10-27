from datetime import datetime

from app import coach, plan_tracker
from app.db import Activity, SessionLocal


def test_defaults_and_update(make_user):
    p = make_user("a@example.com")
    prefs = p.get("/api/athletes/me/preferences").json()
    assert prefs["weekday_prefs"]["mon"] == [] and "illness" in prefs["note_tags"]
    r = p.request(
        "PUT",
        "/api/me/preferences",
        json={
            "weekday_prefs": {"mon": ["Rest"], "sat": ["Road"]},
            "note_tags": ["Illness", "work-trip", "illness"],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["weekday_prefs"]["sat"] == ["Road"]
    assert body["note_tags"] == ["illness", "work-trip"]


def test_unknown_session_type_rejected(make_user):
    p = make_user("a@example.com")
    r = p.request("PUT", "/api/me/preferences", json={"weekday_prefs": {"mon": ["Underwater hockey"]}})
    assert r.status_code == 422


def test_rename_tag_updates_activities(make_user):
    p = make_user("a@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    with SessionLocal() as db:
        db.add(
            Activity(user_id=uid, source="strava", external_id="1", start_time=datetime(2026, 10, 1), note_tag="work")
        )
        db.commit()
    r = p.post("/api/me/note-tags/rename", json={"old": "work", "new": "work-trip"})
    assert "work-trip" in r.json()["note_tags"] and "work" not in r.json()["note_tags"]
    with SessionLocal() as db:
        assert db.query(Activity).one().note_tag == "work-trip"
    assert p.post("/api/me/note-tags/rename", json={"old": "solo", "new": "group"}).status_code == 409


def test_ai_coach_gets_weekday_preferences(make_user, monkeypatch):
    seen = {}

    async def fake_generate(db, viewer, athlete, facts):
        seen.update(facts)
        return {"summary_md": "# Plan", "weeks": []}, "claude-test"

    monkeypatch.setattr("app.routers.plans.generate_plan", fake_generate)
    p = make_user("a@example.com")
    prefs = {"mon": ["Rest"], "tue": ["Zwift / indoor"], "sat": ["Road", "Gravel", "MTB"]}
    p.request("PUT", "/api/me/preferences", json={"weekday_prefs": prefs})
    p.post("/api/athletes/me/plans", json={"without_data": True, "title": "t", "goal": "g"})
    assert seen["weekday_preferences"] == prefs  # several types: the AI coach picks one
    assert "With several, plan exactly one of them" in coach.SYSTEM_PROMPT


def test_coach_needs_plans_scope(make_user):
    athlete = make_user("a@example.com")
    coach = make_user("c@example.com")
    aid = athlete.get("/api/auth/me").json()["id"]
    g = athlete.post("/api/grants", json={"coach_email": "c@example.com", "scopes": ["activities"]}).json()
    coach.post(f"/api/grants/{g['id']}/accept")
    assert coach.get(f"/api/athletes/{aid}/preferences").status_code == 404


def test_walk_and_hike_are_session_types(make_user):
    p = make_user("w@example.com")
    r = p.request("PUT", "/api/me/preferences", json={"weekday_prefs": {"sun": ["Hike"], "sat": ["Walk"]}})
    assert r.status_code == 200 and r.json()["weekday_prefs"]["sun"] == ["Hike"]


def test_several_types_per_day(make_user):
    p = make_user("a@example.com")
    r = p.request("PUT", "/api/me/preferences", json={"weekday_prefs": {"sat": ["Road", "Gravel", "Road"]}})
    assert r.status_code == 200 and r.json()["weekday_prefs"]["sat"] == ["Road", "Gravel"]
    # Rest stands alone, and at most four types a day.
    assert p.request("PUT", "/api/me/preferences", json={"weekday_prefs": {"sun": ["Rest", "Walk"]}}).status_code == 422
    five = ["Road", "Gravel", "MTB", "E-MTB", "Walk"]
    assert p.request("PUT", "/api/me/preferences", json={"weekday_prefs": {"sun": five}}).status_code == 422


def test_apply_preferences_keeps_a_day_that_is_one_of_the_choices():
    from datetime import date

    weeks = plan_tracker.build_weeks([], date(2030, 1, 7), 1)  # a Monday, well after "today"
    sat = next(d for d in weeks[0]["days"] if d["weekday"] == "sat")
    sun = next(d for d in weeks[0]["days"] if d["weekday"] == "sun")
    sat.update(type="Gravel", duration_min=120)
    sun.update(type="Swim", duration_min=60)
    prefs = {"sat": ["Road", "Gravel"], "sun": ["Road", "MTB"]}
    changed, _ = plan_tracker.apply_preferences(weeks, prefs, date(2030, 1, 1))
    assert sat["type"] == "Gravel" and sun["type"] == "Road" and changed == 1
