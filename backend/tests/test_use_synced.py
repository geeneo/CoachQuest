"""Profile: "Use this" takes the synced value for one field (profile_sync.synced_values / use_synced)."""

from datetime import date, timedelta

from app import profile_sync
from app.db import SessionLocal, User, WellnessDay


def test_use_the_synced_weight_and_ftp(make_user):
    p = make_user("a@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    p.patch("/api/me", json={"weight_kg": 54.7, "ftp_watts": 213})
    assert p.get("/api/me/profile/synced").json() == {}
    assert p.post("/api/me/profile/use-synced", json={"field": "weight_kg"}).status_code == 404
    day = date.today() - timedelta(days=9)
    with SessionLocal() as db:
        db.add(WellnessDay(user_id=uid, day=day, weight_kg=73.7, source="garmin"))
        db.add(WellnessDay(user_id=uid, day=day - timedelta(days=20), weight_kg=75.0, source="garmin"))
        user = db.get(User, uid)
        profile_sync.apply_from_provider(db, user, "garmin", {"ftp_watts": 205})  # Garmin reported 205 W
        profile_sync.mark_manual(user, ["ftp_watts"])
        user.ftp_watts = 213  # then the athlete typed 213 again
        db.commit()
    synced = p.get("/api/me/profile/synced").json()
    assert synced["weight_kg"] == {"value": 73.7, "source": "Garmin", "provider": "garmin", "day": day.isoformat()}
    assert synced["ftp_watts"]["value"] == 205 and synced["ftp_watts"]["source"] == "Garmin"

    me = p.post("/api/me/profile/use-synced", json={"field": "weight_kg"}).json()
    assert me["weight_kg"] == 73.7 and me["weight_source"] == "garmin"
    me = p.post("/api/me/profile/use-synced", json={"field": "ftp_watts"}).json()
    assert me["ftp_watts"] == 205 and me["profile_sources"]["ftp_watts"]["source"] == "garmin"
    # Recorded like any other FTP change: from today on.
    assert {"field": "ftp_watts", "from": date.today().isoformat(), "value": 205} in me["threshold_history"]
    assert p.post("/api/me/profile/use-synced", json={"field": "goal"}).status_code == 422
