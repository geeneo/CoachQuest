import asyncio
from datetime import datetime

from app.db import Activity, Connection, SessionLocal, User
from app.providers import garmin
from app.security import encrypt_json

HR_ZONES = [
    {"sport": "DEFAULT", "maxHeartRateUsed": 188, "lactateThresholdHeartRateUsed": 165},
    {"sport": "CYCLING", "maxHeartRateUsed": 185, "lactateThresholdHeartRateUsed": 162},
]


def test_parse_thresholds_prefers_cycling():
    t = garmin.parse_thresholds({"functionalThresholdPower": 265.4}, None, HR_ZONES)
    assert t == {"ftp_watts": 265, "lthr_bpm": 162, "max_hr_bpm": 185}


def test_parse_thresholds_falls_back_and_ignores_junk():
    zones = [{"sport": "CYCLING", "functionalThresholdPower": 240}]
    t = garmin.parse_thresholds([], zones, [{"sport": "DEFAULT", "maxHeartRateUsed": 190}])
    assert t == {"ftp_watts": 240, "lthr_bpm": None, "max_hr_bpm": 190}
    assert garmin.parse_thresholds(None, None, None) == {"ftp_watts": None, "lthr_bpm": None, "max_hr_bpm": None}
    assert garmin.parse_thresholds({"functionalThresholdPower": 5}, None, None)["ftp_watts"] is None


def _sync(monkeypatch, uid, thresholds):
    monkeypatch.setattr(garmin, "_fetch", lambda *a: ("{}", [], [], None, thresholds if a[4] else None))
    with SessionLocal() as db:
        conn = Connection(user_id=uid, provider="garmin", token_enc=encrypt_json({"tokens": "{}"}))
        db.add(conn)
        db.commit()
        asyncio.run(garmin.sync(db, conn))
        db.delete(conn)
        db.commit()
        return db.get(User, uid)


def test_garmin_thresholds_fill_profile_and_recalculate_tss(monkeypatch, make_user):
    p = make_user("a@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    with SessionLocal() as db:
        db.add(
            Activity(
                user_id=uid,
                source="strava",
                external_id="1",
                start_time=datetime(2026, 10, 1),
                duration_s=3600,
                norm_power=250,
                tss=50,
                tss_method="duration",
            )
        )
        db.commit()
    _sync(monkeypatch, uid, {"ftp_watts": 250, "lthr_bpm": 160, "max_hr_bpm": 185})
    me = p.get("/api/auth/me").json()
    assert (me["ftp_watts"], me["lthr_bpm"], me["max_hr_bpm"]) == (250, 160, 185)
    assert me["profile_sources"]["ftp_watts"]["source"] == "garmin"
    with SessionLocal() as db:
        act = db.query(Activity).one()
        assert (act.tss, act.tss_method) == (100.0, "power")


def test_manual_value_kept_until_garmin_changes(monkeypatch, make_user):
    p = make_user("a@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    _sync(monkeypatch, uid, {"ftp_watts": 250, "lthr_bpm": None, "max_hr_bpm": None})
    p.patch("/api/me", json={"ftp_watts": 270})
    user = _sync(monkeypatch, uid, {"ftp_watts": 250, "lthr_bpm": None, "max_hr_bpm": None})
    assert user.ftp_watts == 270  # Garmin unchanged: manual value stays
    user = _sync(monkeypatch, uid, {"ftp_watts": 262, "lthr_bpm": None, "max_hr_bpm": None})
    assert user.ftp_watts == 262 and user.profile_sources["ftp_watts"]["source"] == "garmin"
