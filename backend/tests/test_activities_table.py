from datetime import datetime, timedelta

from app.db import Activity, SessionLocal


def _seed(uid):
    now = datetime.now()
    with SessionLocal() as db:
        db.add(
            Activity(
                user_id=uid,
                source="strava",
                external_id="1",
                name="Ride",
                sport="Ride",
                start_time=now - timedelta(days=2),
                distance_m=100000,
                avg_speed_ms=7.5,
                avg_cadence=84.6,
                kilojoules=2000,
                relative_effort=150,
            )
        )
        db.add(
            Activity(
                user_id=uid,
                source="strava",
                external_id="2",
                name="Old",
                sport="Ride",
                start_time=datetime(2024, 3, 10, 7),
                distance_m=50000,
            )
        )
        db.commit()
        return db.query(Activity).filter_by(external_id="1").one().id


def test_rich_fields_and_month_view(make_user):
    p = make_user("a@example.com")
    _seed(p.get("/api/auth/me").json()["id"])
    recent = p.get("/api/athletes/me/activities?days=30").json()
    assert len(recent) == 1
    a = recent[0]
    assert (a["category"], a["avg_speed_kmh"], a["avg_cadence"], a["calories"]) == ("Road", 27.0, 85, 2000)
    march = p.get("/api/athletes/me/activities?since=2024-03-01&until=2024-03-31").json()
    assert [x["name"] for x in march] == ["Old"]


def test_edit_type_race_and_note(make_user):
    p = make_user("a@example.com")
    act_id = _seed(p.get("/api/auth/me").json()["id"])
    race_id = p.post("/api/races", json={"code": "dc", "name": "Double Century"}).json()["id"]
    r = p.patch(f"/api/activities/{act_id}", json={"type_override": "E-MTB", "race_id": race_id, "note_tag": "Group"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["category"], body["race_id"], body["note_tag"], body["is_race"]) == ("E-MTB", race_id, "group", True)
    r = p.patch(f"/api/activities/{act_id}", json={"type_override": None, "race_id": None, "note_tag": None})
    assert r.json()["category"] == "Road" and r.json()["race_id"] is None
    assert p.patch(f"/api/activities/{act_id}", json={"type_override": "Spaceship"}).status_code == 422
    assert p.patch(f"/api/activities/{act_id}", json={"note_tag": "not-a-tag"}).status_code == 422


def test_only_owner_can_edit(make_user):
    owner = make_user("a@example.com")
    other = make_user("b@example.com")
    act_id = _seed(owner.get("/api/auth/me").json()["id"])
    assert other.patch(f"/api/activities/{act_id}", json={"note_tag": "group"}).status_code == 404
    other_race = other.post("/api/races", json={"code": "x", "name": "X"}).json()["id"]
    assert owner.patch(f"/api/activities/{act_id}", json={"race_id": other_race}).status_code == 422
