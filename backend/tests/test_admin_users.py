from datetime import timedelta

from app.db import AccessLog, Activity, AuthEvent, Connection, Session, SessionLocal, SyncJob, utcnow
from app.security import encrypt_json


def _uid(p):
    return p.get("/api/auth/me").json()["id"]


def _seed(uid):
    now = utcnow()
    with SessionLocal() as db:
        for i, source in enumerate(("strava", "strava", "garmin")):
            db.add(
                Activity(
                    user_id=uid,
                    source=source,
                    external_id=str(i),
                    sport="Ride",
                    start_time=now - timedelta(days=10 - i),
                )
            )
        err = "401 token revoked"
        db.add(Connection(user_id=uid, provider="strava", token_enc="x", status="error", last_error=err))
        db.add(Connection(user_id=uid, provider="garmin", token_enc="x", last_sync_at=now - timedelta(days=5)))
        db.add(
            SyncJob(athlete_id=uid, provider="intervals_icu", scheduled_workout_id=1, action="upsert", status="failed")
        )
        db.commit()


def test_overview_counts_and_flags(make_user):
    admin = make_user("admin@example.com", "Admin")
    rider = make_user("rider@example.com", "Rider")
    rid = _uid(rider)
    _seed(rid)
    rows = admin.get("/api/admin/users").json()
    r = next(x for x in rows if x["id"] == rid)
    assert r["attention"] >= 6  # the page can sort sync problems first
    assert r["activities"]["total"] == 3 and r["activities"]["by_source"] == {"strava": 2, "garmin": 1}
    assert r["connections"]["strava"]["status"] == "error"
    assert r["connections"]["strava"]["last_error"] == "401 token revoked"
    assert r["delivery"]["failed"] == 1
    assert {"Strava sync error", "Garmin not synced lately", "workout delivery failed"} <= set(r["flags"])
    assert r["storage_bytes"] > 0 and r["last_seen_at"]
    me = next(x for x in rows if x["email"] == "admin@example.com")
    assert me["activities"]["total"] == 0 and me["flags"] == []
    assert rider.get("/api/admin/users").status_code == 403


def test_detail_is_logged_for_the_user(make_user):
    admin = make_user("admin@example.com", "Admin")
    rider = make_user("rider@example.com", "Rider")
    rid = _uid(rider)
    _seed(rid)
    d = admin.get(f"/api/admin/users/{rid}/detail").json()
    assert d["sports"] == [{"sport": "Ride", "count": 3}]
    assert d["sign_ins"][0]["event"] == "registered"
    log = rider.get("/api/grants/access-log").json()
    assert log[0]["viewer"] == "Admin" and log[0]["resource"] == "admin overview"
    admin.get(f"/api/admin/users/{_uid(admin)}/detail")  # looking at yourself isn't logged
    with SessionLocal() as db:
        assert db.query(AccessLog).filter_by(resource="admin overview").count() == 1
    assert admin.get("/api/admin/users/9999/detail").status_code == 404
    assert rider.get(f"/api/admin/users/{rid}/detail").status_code == 403


def test_sync_now_for_a_user(make_user):
    admin = make_user("admin@example.com", "Admin")
    rider = make_user("rider@example.com", "Rider")
    rid = _uid(rider)
    assert admin.post(f"/api/admin/users/{rid}/sync/strava").status_code == 404  # not connected
    with SessionLocal() as db:
        db.add(Connection(user_id=rid, provider="garmin", token_enc="x", last_sync_at=utcnow()))
        db.commit()
    assert admin.post(f"/api/admin/users/{rid}/sync/garmin").status_code == 429  # synced just now


def _strava(uid, client_id):
    tokens = {"access_token": "a", "refresh_token": "r"} | ({"client_id": client_id} if client_id else {})
    with SessionLocal() as db:
        db.add(Connection(user_id=uid, provider="strava", token_enc=encrypt_json(tokens), last_sync_at=utcnow()))
        db.commit()


def test_shows_which_strava_app_holds_each_link(make_user):
    admin = make_user("admin@example.com", "Admin")
    admin.request(
        "PUT", "/api/admin/settings", json={"values": {"strava_client_id": "999", "strava_client_secret": "ab" * 20}}
    )
    people = {n: make_user(f"{n}@example.com", n) for n in ("own", "shared", "legacy", "old", "idle")}
    people["own"].request("PUT", "/api/connections/strava/app", json={"client_id": "777", "client_secret": "ab" * 20})
    ids = {n: _uid(p) for n, p in people.items()}
    _strava(ids["own"], "777")
    _strava(ids["shared"], "999")
    _strava(ids["legacy"], None)  # saved before client_id was recorded: the shared app
    _strava(ids["old"], "555")
    _strava(ids["idle"], "999")
    long_ago = utcnow() - timedelta(days=60)
    with SessionLocal() as db:
        db.query(Session).filter_by(user_id=ids["idle"]).update({"last_seen_at": long_ago})
        db.query(AuthEvent).filter_by(user_id=ids["idle"]).update({"at": long_ago})
        db.commit()

    rows = {r["id"]: r for r in admin.get("/api/admin/users").json()}
    apps = {n: rows[i]["connections"]["strava"]["app"] for n, i in ids.items()}
    assert apps == {"own": "own", "shared": "shared", "legacy": "shared", "old": "old", "idle": "shared"}
    assert "idle on shared Strava app" in rows[ids["idle"]]["flags"]
    assert "idle on shared Strava app" not in rows[ids["shared"]]["flags"]
    assert admin.get("/api/admin/stats").json()["strava_shared"] == 3
