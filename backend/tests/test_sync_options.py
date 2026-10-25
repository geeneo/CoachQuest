from datetime import datetime, timedelta

from sqlalchemy import create_engine, inspect, text

from app.db import Activity, Connection, SessionLocal, WellnessDay


def _seed(user_id: int, garmin_options=None):
    db = SessionLocal()
    start = datetime.now() - timedelta(days=1)
    db.add(Connection(user_id=user_id, provider="strava", token_enc="x"))
    db.add(Connection(user_id=user_id, provider="garmin", token_enc="x", options=garmin_options))
    # Same morning ride from both sources, plus a Garmin-only walk later.
    db.add(Activity(user_id=user_id, source="strava", external_id="s1", name="Ride", start_time=start, tss=60))
    db.add(Activity(user_id=user_id, source="garmin", external_id="g1", name="Ride", start_time=start, tss=60))
    db.add(
        Activity(
            user_id=user_id,
            source="garmin",
            external_id="g2",
            name="Walk",
            start_time=start + timedelta(hours=5),
            tss=10,
        )
    )
    db.add(WellnessDay(user_id=user_id, day=datetime.now().date(), resting_hr=48))
    db.commit()
    db.close()


def _names(p):
    return sorted((a["source"], a["name"]) for a in p.get("/api/athletes/me/activities").json())


def test_defaults_import_everything_and_dedupe(make_user):
    p = make_user("a@example.com")
    _seed(p.get("/api/auth/me").json()["id"])
    assert _names(p) == [("garmin", "Walk"), ("strava", "Ride")]
    conns = {c["provider"]: c["options"] for c in p.get("/api/connections").json()["connections"]}
    assert conns == {
        "strava": {"activities": True},
        "garmin": {"activities": True, "wellness": True, "weight": True},
    }


def test_garmin_wellness_only_hides_garmin_activities(make_user):
    p = make_user("a@example.com")
    _seed(p.get("/api/auth/me").json()["id"])
    r = p.patch("/api/connections/garmin/options", json={"activities": False})
    assert r.status_code == 200 and r.json()["options"] == {"activities": False, "wellness": True, "weight": True}
    assert _names(p) == [("strava", "Ride")]
    assert len(p.get("/api/athletes/me/wellness").json()) == 1


def test_garmin_wellness_off_hides_wellness(make_user):
    p = make_user("a@example.com")
    _seed(p.get("/api/auth/me").json()["id"])
    p.patch("/api/connections/garmin/options", json={"wellness": False})
    assert p.get("/api/athletes/me/wellness").json() == []


def test_strava_off_uses_garmin_activities(make_user):
    p = make_user("a@example.com")
    _seed(p.get("/api/auth/me").json()["id"])
    p.patch("/api/connections/strava/options", json={"activities": False})
    assert _names(p) == [("garmin", "Ride"), ("garmin", "Walk")]


def test_unknown_option_and_delete_data(make_user):
    p = make_user("a@example.com")
    _seed(p.get("/api/auth/me").json()["id"])
    assert p.patch("/api/connections/strava/options", json={"wellness": False}).status_code == 422
    assert p.delete("/api/connections/garmin/data/activities").json() == {"deleted": 2}
    assert p.delete("/api/connections/strava/data/wellness").status_code == 404


def test_coach_sees_the_same_filtered_view(make_user):
    athlete = make_user("a@example.com")
    coach = make_user("c@example.com")
    aid = athlete.get("/api/auth/me").json()["id"]
    _seed(aid, garmin_options={"activities": False, "wellness": True})
    g = athlete.post("/api/grants", json={"coach_email": "c@example.com", "scopes": ["activities"]}).json()
    coach.post(f"/api/grants/{g['id']}/accept")
    names = [a["name"] for a in coach.get(f"/api/athletes/{aid}/activities").json()]
    assert names == ["Ride"]


def test_old_database_gets_options_column(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path}/old.db"
    old = create_engine(url)
    with old.begin() as c:
        c.execute(text("CREATE TABLE connections (id INTEGER PRIMARY KEY, user_id INTEGER, provider VARCHAR(20))"))
    import app.db as dbmod

    monkeypatch.setattr(dbmod, "engine", old)
    dbmod.init_db()
    assert "options" in {c["name"] for c in inspect(old).get_columns("connections")}
