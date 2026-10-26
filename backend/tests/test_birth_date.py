import asyncio
from datetime import date

from app import profile_sync
from app.db import Connection, SessionLocal, User
from app.providers import garmin
from app.security import encrypt_json


def test_parse_birth_date():
    assert garmin.parse_birth_date({"userData": {"birthDate": "1980-05-17"}}) == date(1980, 5, 17)
    assert garmin.parse_birth_date(None, {"userInfo": {"birthDate": "1975-01-02T00:00:00"}}) == date(1975, 1, 2)
    assert garmin.parse_birth_date({"userData": {"birthDate": "nonsense"}}, {"birthDate": "1800-01-01"}) is None
    assert garmin.parse_birth_date({"userData": {"birthDate": date.today().isoformat()}}) is None  # not a real age


def test_age():
    assert profile_sync.age(date(1980, 5, 17), date(2026, 5, 16)) == 45
    assert profile_sync.age(date(1980, 5, 17), date(2026, 5, 17)) == 46
    assert profile_sync.age(None) is None


def _connect(uid):
    with SessionLocal() as db:
        db.add(Connection(user_id=uid, provider="garmin", token_enc=encrypt_json({"tokens": "{}"})))
        db.commit()


def test_birth_date_from_garmin_manual_and_privacy(monkeypatch, make_user):
    athlete = make_user("a@example.com", "Ann")
    uid = athlete.get("/api/auth/me").json()["id"]
    _connect(uid)
    found = {"ftp_watts": None, "lthr_bpm": None, "max_hr_bpm": None, "birth_date": date(1980, 5, 17)}
    monkeypatch.setattr(garmin, "_fetch", lambda *a: ("{}", [], [], None, dict(found)))
    r = athlete.post("/api/me/profile/pull-garmin").json()
    assert r["found"]["birth_date"] == "1980-05-17" and "birth_date" in r["changed"]
    me = athlete.get("/api/auth/me").json()
    assert me["birth_date"] == "1980-05-17" and me["age"] == profile_sync.age(date(1980, 5, 17))
    assert me["profile_sources"]["birth_date"]["source"] == "garmin"
    # Typed in by hand: kept until Garmin reports a different date.
    athlete.patch("/api/me", json={"birth_date": "1981-01-01"})
    with SessionLocal() as db:
        conn = db.query(Connection).filter_by(user_id=uid).one()
        asyncio.run(garmin.sync(db, conn))
        assert db.get(User, uid).birth_date == date(1981, 1, 1)
        found["birth_date"] = date(1980, 5, 18)
        asyncio.run(garmin.sync(db, db.query(Connection).filter_by(user_id=uid).one()))
        assert db.get(User, uid).birth_date == date(1980, 5, 18)
    assert athlete.patch("/api/me", json={"birth_date": "2030-01-01"}).status_code == 422
    # A coach with Profile sees the age, never the date; without Profile, neither.
    coach = make_user("c@example.com", "Coach")
    g = athlete.post("/api/grants", json={"coach_email": "c@example.com", "scopes": ["profile"]}).json()
    coach.post(f"/api/grants/{g['id']}/accept")
    view = coach.get(f"/api/athletes/{uid}").json()
    assert view["age"] == profile_sync.age(date(1980, 5, 18)) and "birth_date" not in view
    other = make_user("o@example.com", "Other")
    g = athlete.post("/api/grants", json={"coach_email": "o@example.com", "scopes": ["activities"]}).json()
    other.post(f"/api/grants/{g['id']}/accept")
    assert "age" not in other.get(f"/api/athletes/{uid}").json()


def test_garmin_profile_choices_can_be_switched(make_user):
    athlete = make_user("a@example.com")
    _connect(athlete.get("/api/auth/me").json()["id"])
    for kind in ("weight", "thresholds", "birth_date"):
        r = athlete.request("PATCH", "/api/connections/garmin/options", json={kind: False})
        assert r.status_code == 200 and r.json()["options"][kind] is False, (kind, r.text)


def test_deleting_garmin_thresholds_keeps_wellness(monkeypatch, make_user):
    from app.db import WellnessDay

    athlete = make_user("a@example.com")
    uid = athlete.get("/api/auth/me").json()["id"]
    _connect(uid)
    found = {"ftp_watts": 250, "lthr_bpm": 160, "max_hr_bpm": None}
    monkeypatch.setattr(garmin, "_fetch", lambda *a: ("{}", [], [], None, dict(found)))
    athlete.post("/api/me/profile/pull-garmin")
    athlete.patch("/api/me", json={"max_hr_bpm": 188})
    with SessionLocal() as db:
        db.add(WellnessDay(user_id=uid, day=date(2026, 10, 20), resting_hr=48, source="garmin"))
        db.commit()
    r = athlete.delete("/api/connections/garmin/data/thresholds")
    assert r.json()["deleted"] == 2
    me = athlete.get("/api/auth/me").json()
    assert (me["ftp_watts"], me["lthr_bpm"], me["max_hr_bpm"]) == (None, None, 188)
    with SessionLocal() as db:
        assert db.query(WellnessDay).filter_by(user_id=uid).count() == 1
