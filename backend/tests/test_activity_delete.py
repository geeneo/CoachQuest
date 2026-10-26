from datetime import date, datetime, timedelta

from app.db import Activity, DeletedActivity, ScheduledWorkout, SessionLocal, User
from app.providers import strava

STEADY = [{"kind": "steady", "duration_s": 3600, "power": 0.8}]


def _uid(p):
    return p.get("/api/auth/me").json()["id"]


def _ride(uid, source, ext, start, km=30):
    with SessionLocal() as db:
        a = Activity(
            user_id=uid,
            source=source,
            external_id=ext,
            name=f"{source} ride",
            sport="Ride",
            start_time=start,
            duration_s=3600,
            distance_m=km * 1000,
            tss=60,
        )
        db.add(a)
        db.commit()
        return a.id


def _strava_item(ext, start):
    return {
        "id": int(ext),
        "name": "Back again?",
        "sport_type": "Ride",
        "start_date": start.isoformat() + "Z",
        "moving_time": 3600,
        "distance": 30000,
    }


def test_delete_hides_copies_and_survives_sync(make_user):
    p = make_user("rider@example.com")
    uid = _uid(p)
    start = datetime.combine(date.today() - timedelta(days=2), datetime.min.time()) + timedelta(hours=7)
    sid = _ride(uid, "strava", "111", start)
    _ride(uid, "garmin", "g1", start + timedelta(minutes=2))  # the same ride from Garmin, hidden by dedupe
    other = _ride(uid, "strava", "222", start - timedelta(days=1))
    assert len(p.get("/api/athletes/me/activities?days=7").json()) == 2
    load_before = p.get("/api/athletes/me/fitness?days=7").json()
    assert p.post("/api/activities/delete", json={"ids": [sid]}).json() == {"deleted": 1}
    acts = p.get("/api/athletes/me/activities?days=7").json()
    assert [a["id"] for a in acts] == [other]  # the Garmin copy didn't take its place
    assert p.get("/api/athletes/me/fitness?days=7").json() != load_before
    deleted = p.get("/api/activities/deleted").json()
    assert {d["source"] for d in deleted} == {"strava", "garmin"} and deleted[0]["distance_km"] == 30
    # The next Strava sync doesn't bring it back.
    with SessionLocal() as db:
        strava._upsert(db, db.get(User, uid), _strava_item("111", start))
        db.commit()
        assert db.query(Activity).filter_by(user_id=uid).count() == 1
    # Undo puts both back, and syncs update them again.
    r = p.post("/api/activities/deleted/restore", json={"ids": [d["id"] for d in deleted]})
    assert r.json() == {"restored": 2}
    assert len(p.get("/api/athletes/me/activities?days=7").json()) == 2
    with SessionLocal() as db:
        strava._upsert(db, db.get(User, uid), _strava_item("111", start))
        db.commit()
        assert db.query(DeletedActivity).count() == 0
        assert db.query(Activity).filter_by(external_id="111").one().name == "Back again?"


def test_only_own_activities(make_user):
    a = make_user("a@example.com", "Ann")
    coach = make_user("c@example.com", "Cobus")
    g = a.post("/api/grants", json={"coach_email": "c@example.com", "scopes": ["activities"]}).json()
    coach.post(f"/api/grants/{g['id']}/accept")
    aid = _ride(_uid(a), "strava", "1", datetime.now() - timedelta(days=1))
    assert coach.post("/api/activities/delete", json={"ids": [aid]}).json() == {"deleted": 0}
    assert coach.get("/api/activities/deleted").json() == []
    with SessionLocal() as db:
        assert db.get(Activity, aid) is not None
    assert a.post("/api/activities/delete", json={"ids": []}).status_code == 422


def test_workout_loses_its_ride(make_user):
    p = make_user("rider@example.com")
    uid = _uid(p)
    day = date.today() - timedelta(days=1)
    w = p.post("/api/athletes/me/workouts", json={"day": day.isoformat(), "name": "Tempo", "steps": STEADY}).json()
    rid = _ride(uid, "strava", "5", datetime.combine(day, datetime.min.time()) + timedelta(hours=10))
    with SessionLocal() as db:
        db.get(ScheduledWorkout, w["id"]).activity_id = rid
        db.get(ScheduledWorkout, w["id"]).match = "manual"
        db.commit()
    p.post("/api/activities/delete", json={"ids": [rid]})
    with SessionLocal() as db:
        sw = db.get(ScheduledWorkout, w["id"])
        assert sw.activity_id is None and sw.match == "auto"
