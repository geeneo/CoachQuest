"""Several sessions on one day: weekday preferences, the AI coach's plan, editing, and the super admin limit."""

from test_phase3 import _create, _week, planner  # noqa: F401  (fixture)

from app import coach, plan_tracker

STRENGTH = {"type": "Strength", "description": "Core and legs", "duration_min": 30, "intensity": ["easy"]}


def _tuesday(plan):
    return next(d for d in plan["weeks"][0]["days"] if d["weekday"] == "tue")


def test_ai_answer_keeps_extra_sessions(make_user, planner):  # noqa: F811
    week = _week()
    week["days"][0]["extra_sessions"] = [STRENGTH, {"type": "Rest", "description": "x"}, {"type": "Walk"}]
    week["days"][2]["extra_sessions"] = []
    planner["value"] = [week, week]
    athlete = make_user("rider@example.com")
    plan = athlete.get(f"/api/athletes/me/plans/{_create(athlete)['id']}").json()
    tue = _tuesday(plan)
    # Rest is dropped; Strength and Walk stay (3 sessions a day by default).
    assert [e["type"] for e in tue["extra_sessions"]] == ["Strength", "Walk"]
    assert tue["extra_sessions"][0] == {**STRENGTH, "segment_id": None}
    assert plan["max_sessions_per_day"] == 3
    assert plan["weeks"][0]["summary"]["planned_minutes"] == 60 + 30 + 0 + 60 + 180
    assert "| + | Strength | Core and legs | 30 | easy |" in plan_tracker.markdown(plan["weeks"])


def test_schema_and_prompt_ask_for_every_session():
    day = coach.plan_schema()["schema"]["properties"]["weeks"]["items"]["properties"]["days"]["items"]
    assert "extra_sessions" in day["required"]
    assert "Rest" not in day["properties"]["extra_sessions"]["items"]["properties"]["type"]["enum"]
    assert "extra_sessions" in coach.day_schema()["schema"]["properties"]["day"]["required"]
    assert "does ALL of them that day" in coach.SYSTEM_PROMPT


def test_edit_a_days_sessions(make_user, planner):  # noqa: F811
    athlete = make_user("rider@example.com")
    plan = _create(athlete)
    url = f"/api/athletes/me/plans/{plan['id']}"
    day = _tuesday(athlete.get(url).json())["date"]
    r = athlete.patch(f"{url}/days/{day}", json={"extra_sessions": [STRENGTH, {"type": "Walk", "duration_min": 20}]})
    assert r.status_code == 200
    assert [e["type"] for e in _tuesday(r.json())["extra_sessions"]] == ["Strength", "Walk"]
    assert athlete.patch(f"{url}/days/{day}", json={"extra_sessions": [{"type": "Rest"}]}).status_code == 422
    too_many = [STRENGTH, STRENGTH, STRENGTH]
    assert athlete.patch(f"{url}/days/{day}", json={"extra_sessions": too_many}).status_code == 422
    # Making the day a rest day clears its other sessions.
    plan = athlete.patch(f"{url}/days/{day}", json={"type": "Rest"}).json()
    assert _tuesday(plan)["extra_sessions"] == []


def test_super_admin_sets_sessions_per_day(make_user):
    boss = make_user("admin@example.com")
    helper = make_user("helper@example.com")
    hid = helper.get("/api/auth/me").json()["id"]
    boss.patch(f"/api/admin/users/{hid}", json={"is_admin": True})
    two = {"values": {"max_sessions_per_day": "2"}}
    assert helper.request("PUT", "/api/admin/settings", json=two).status_code == 403
    rider = make_user("rider@example.com")
    three = {"weekday_prefs": {"tue": ["Zwift / indoor", "Strength", "Walk"]}}
    assert rider.request("PUT", "/api/me/preferences", json=three).status_code == 200
    assert boss.request("PUT", "/api/admin/settings", json=two).status_code == 200
    prefs = rider.get("/api/athletes/me/preferences").json()
    assert prefs["max_per_day"] == 2 and prefs["weekday_prefs"]["tue"] == ["Zwift / indoor", "Strength"]
    assert rider.request("PUT", "/api/me/preferences", json=three).status_code == 422


def test_approval_shows_all_sessions():
    from app import plan_approval

    before = {"date": "2030-01-08", "type": "Zwift / indoor", "description": "SS", "duration_min": 60}
    after = {**before, "extra_sessions": [STRENGTH]}
    week = lambda d: [{"days": [d]}]  # noqa: E731
    [c] = plan_approval.changes(week(before), week(after))
    assert c["after"] == {"type": "Zwift / indoor + Strength", "description": "SS · Core and legs", "duration_min": 90}
    assert plan_approval.changes(week(before), week({**before, "extra_sessions": []})) == []
