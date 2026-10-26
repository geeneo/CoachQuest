from datetime import datetime, timedelta

from app.db import Activity, SessionLocal, WellnessDay


def _seed(athlete_id: int):
    db = SessionLocal()
    db.add(
        Activity(
            user_id=athlete_id,
            source="strava",
            external_id="1",
            name="Ride",
            sport="Ride",
            start_time=datetime.now() - timedelta(days=1),
            duration_s=3600,
            distance_m=30000,
            tss=60,
        )
    )
    db.add(WellnessDay(user_id=athlete_id, day=datetime.now().date(), resting_hr=48, hrv_ms=70))
    db.commit()
    db.close()


def _setup(make_user, scopes):
    athlete = make_user("athlete@example.com", "Athlete")
    coach = make_user("coach@example.com", "Coach")
    athlete_id = athlete.get("/api/auth/me").json()["id"]
    _seed(athlete_id)
    g = athlete.post("/api/grants", json={"coach_email": "coach@example.com", "scopes": scopes})
    assert g.status_code == 200, g.text
    return athlete, coach, athlete_id, g.json()["id"]


def test_pending_grant_gives_no_access(make_user):
    _, coach, athlete_id, _ = _setup(make_user, ["activities"])
    assert coach.get(f"/api/athletes/{athlete_id}/activities").status_code == 404


def test_coach_sees_only_granted_scopes(make_user):
    athlete, coach, athlete_id, grant_id = _setup(make_user, ["activities"])
    assert coach.post(f"/api/grants/{grant_id}/accept").status_code == 200
    r = coach.get(f"/api/athletes/{athlete_id}/activities")
    assert r.status_code == 200 and len(r.json()) == 1
    assert coach.get(f"/api/athletes/{athlete_id}/wellness").status_code == 404
    assert coach.get(f"/api/athletes/{athlete_id}/fitness").status_code == 404
    assert [a["id"] for a in coach.get("/api/athletes").json()] == [athlete_id]
    log = athlete.get("/api/grants/access-log").json()
    assert log[0]["viewer"] == "Coach" and log[0]["resource"] == "activities"


def test_athlete_changes_scopes_and_revokes(make_user):
    athlete, coach, athlete_id, grant_id = _setup(make_user, ["activities"])
    coach.post(f"/api/grants/{grant_id}/accept")
    assert coach.patch(f"/api/grants/{grant_id}", json={"scopes": ["wellness"]}).status_code == 403
    assert athlete.patch(f"/api/grants/{grant_id}", json={"scopes": ["wellness"]}).status_code == 200
    assert coach.get(f"/api/athletes/{athlete_id}/wellness").status_code == 200
    assert coach.get(f"/api/athletes/{athlete_id}/activities").status_code == 404
    athlete.delete(f"/api/grants/{grant_id}")
    assert coach.get(f"/api/athletes/{athlete_id}/wellness").status_code == 404


def test_unknown_scope_rejected(make_user):
    athlete = make_user("athlete@example.com")
    make_user("coach@example.com")
    r = athlete.post("/api/grants", json={"coach_email": "coach@example.com", "scopes": ["everything"]})
    assert r.status_code == 422


def test_stranger_cannot_read(make_user):
    _, _, athlete_id, _ = _setup(make_user, ["activities"])
    stranger = make_user("stranger@example.com")
    assert stranger.get(f"/api/athletes/{athlete_id}").status_code == 404
    assert stranger.get(f"/api/athletes/{athlete_id}/activities").status_code == 404


def test_plan_prompt_contains_only_shared_data(make_user, monkeypatch):
    seen = {}

    async def fake_generate(db, viewer, athlete, facts):
        seen.update(facts)
        return {"summary_md": "# Plan", "weeks": []}, "claude-test"

    monkeypatch.setattr("app.routers.plans.generate_plan", fake_generate)
    athlete, coach, athlete_id, grant_id = _setup(make_user, ["activities", "plans"])
    coach.post(f"/api/grants/{grant_id}/accept")
    r = coach.post(
        f"/api/athletes/{athlete_id}/plans",
        json={"without_data": True, "title": "Base", "goal": "Gran fondo", "weeks": 4},
    )
    assert r.status_code == 200, r.text
    assert "recent_activities" in seen
    assert "wellness" not in seen and "load" not in seen
    assert r.json()["content_md"].startswith("# Plan")
    assert len(athlete.get("/api/athletes/me/plans").json()) == 1


def test_plans_need_plans_scope(make_user):
    _, coach, athlete_id, grant_id = _setup(make_user, ["activities"])
    coach.post(f"/api/grants/{grant_id}/accept")
    r = coach.post(f"/api/athletes/{athlete_id}/plans", json={"without_data": True, "title": "x", "goal": "y"})
    assert r.status_code == 404


def _profile_setup(make_user, scopes):
    athlete, coach, athlete_id, grant_id = _setup(make_user, scopes)
    athlete.patch("/api/me", json={"ftp_watts": 260, "weight_kg": 72.5, "goal": "Gran fondo"})
    coach.post(f"/api/grants/{grant_id}/accept")
    return athlete, coach, athlete_id


def test_profile_and_weight_hidden_by_default(make_user):
    _, coach, athlete_id = _profile_setup(make_user, ["activities", "plans"])
    summary = coach.get(f"/api/athletes/{athlete_id}").json()
    assert "ftp_watts" not in summary and "weight_kg" not in summary and "goal" not in summary


def test_profile_without_weight(make_user):
    _, coach, athlete_id = _profile_setup(make_user, ["activities", "profile"])
    summary = coach.get(f"/api/athletes/{athlete_id}").json()
    assert summary["ftp_watts"] == 260 and summary["goal"] == "Gran fondo"
    assert "weight_kg" not in summary


def test_ai_prompt_respects_profile_and_weight(make_user, monkeypatch):
    seen = {}

    async def fake_generate(db, viewer, athlete, facts):
        seen.update(facts)
        return {"summary_md": "# Plan", "weeks": []}, "claude-test"

    monkeypatch.setattr("app.routers.plans.generate_plan", fake_generate)
    _, coach, athlete_id = _profile_setup(make_user, ["profile", "plans"])
    coach.post(f"/api/athletes/{athlete_id}/plans", json={"without_data": True, "title": "t", "goal": "g"})
    assert seen["athlete"]["ftp_watts"] == 260
    assert "weight_kg" not in seen["athlete"]


def test_athlete_sees_own_weight(make_user):
    p = make_user("solo@example.com")
    p.patch("/api/me", json={"weight_kg": 70})
    assert p.get("/api/athletes/me").json()["weight_kg"] == 70


def test_admin_reads_any_athlete_but_cannot_change(make_user):
    admin = make_user("admin@example.com", "Admin")
    athlete = make_user("athlete@example.com", "Athlete")
    other = make_user("other@example.com", "Other")
    athlete_id = athlete.get("/api/auth/me").json()["id"]
    _seed(athlete_id)
    # Off by default: an admin is like any other user.
    assert admin.get(f"/api/athletes/{athlete_id}/activities").status_code == 404
    assert admin.get("/api/admin/users").json()[0]["can_view_data"] is False
    admin.request("PUT", "/api/admin/settings", json={"values": {"admin_view_data": "on"}})
    assert admin.get("/api/admin/users").json()[0]["can_view_data"] is True
    s = admin.get(f"/api/athletes/{athlete_id}").json()
    assert s["admin_view"] is True and set(s["scopes"]) >= {"activities", "wellness", "plans"}
    assert len(admin.get(f"/api/athletes/{athlete_id}/activities").json()) == 1
    assert admin.get(f"/api/athletes/{athlete_id}/wellness?days=7").status_code == 200
    log = athlete.get("/api/grants/access-log").json()
    assert {e["resource"] for e in log} >= {"activities", "wellness"} and log[0]["viewer"] == "Admin"
    # Read only: changing anything for the athlete still needs a grant.
    r = admin.post(f"/api/athletes/{athlete_id}/coach/chats", json={"question": "How is my training?"})
    assert r.status_code == 404
    assert admin.get("/api/athletes/9999").status_code == 404
    # Not for other users.
    assert other.get(f"/api/athletes/{athlete_id}/activities").status_code == 404
    assert athlete.get("/api/athletes/me").json()["admin_view"] is False
    admin.request("PUT", "/api/admin/settings", json={"values": {"admin_view_data": "off"}})
    assert admin.get(f"/api/athletes/{athlete_id}/activities").status_code == 404
