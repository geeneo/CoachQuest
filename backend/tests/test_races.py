from datetime import date, timedelta


def _race(p, **kw):
    body = {"code": "k2c", "name": "Lions Karoo to Coast", "discipline": "Mountain bike", **kw}
    return p.post("/api/races", json=body)


def test_create_edit_delete_race(make_user):
    p = make_user("a@example.com")
    soon = (date.today() + timedelta(days=30)).isoformat()
    r = _race(p, target_date=soon, start_time="06:30", distance_km=100, elevation_m=1900, target_ctl=95)
    assert r.status_code == 200, r.text
    race = r.json()
    assert race["days_to_go"] == 30 and race["start_time"] == "06:30"
    assert _race(p).status_code == 409  # same code twice
    r = p.patch(f"/api/races/{race['id']}", json={"short_name": "K2C", "days": 2, "start_time": None})
    assert r.json()["short_name"] == "K2C" and r.json()["days"] == 2 and r.json()["start_time"] is None
    assert len(p.get("/api/athletes/me/races").json()) == 1
    assert p.delete(f"/api/races/{race['id']}").status_code == 200
    assert p.get("/api/athletes/me/races").json() == []


def test_validation(make_user):
    p = make_user("a@example.com")
    assert _race(p, code="K 2 C").status_code == 422
    assert _race(p, discipline="Underwater hockey").status_code == 422
    assert _race(p, code="run1", discipline="Trail run").status_code == 200


def test_coach_reads_with_plans_scope_only_and_cannot_edit(make_user):
    athlete = make_user("a@example.com")
    coach = make_user("c@example.com")
    aid = athlete.get("/api/auth/me").json()["id"]
    race_id = _race(athlete).json()["id"]
    g = athlete.post("/api/grants", json={"coach_email": "c@example.com", "scopes": ["activities"]}).json()
    coach.post(f"/api/grants/{g['id']}/accept")
    assert coach.get(f"/api/athletes/{aid}/races").status_code == 404
    athlete.patch(f"/api/grants/{g['id']}", json={"scopes": ["activities", "plans"]})
    assert coach.get(f"/api/athletes/{aid}/races").json()[0]["code"] == "k2c"
    assert coach.patch(f"/api/races/{race_id}", json={"name": "Hacked"}).status_code == 404


def test_upcoming_races_go_to_the_ai_coach(make_user, monkeypatch):
    seen = {}

    async def fake_generate(db, viewer, athlete, facts):
        seen.update(facts)
        return "# Plan", "claude-test"

    monkeypatch.setattr("app.routers.plans.generate_plan", fake_generate)
    p = make_user("a@example.com")
    _race(p, code="past", target_date=(date.today() - timedelta(days=5)).isoformat())
    _race(p, code="soon", target_date=(date.today() + timedelta(days=40)).isoformat(), target_ctl=90)
    _race(p, code="off", target_date=(date.today() + timedelta(days=50)).isoformat(), active=False)
    p.post("/api/athletes/me/plans", json={"title": "t", "goal": "g"})
    assert [r["code"] for r in seen["upcoming_races"]] == ["soon"]
    assert seen["upcoming_races"][0]["target_ctl"] == 90
