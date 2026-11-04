"""Data health per athlete (diagnostics.py)."""

import json
from datetime import date, datetime, timedelta

from app.db import Activity, Connection, SessionLocal, SyncJob, User, utcnow


def test_new_athlete_gets_pointers(make_user):
    p = make_user("a@example.com")
    d = p.get("/api/athletes/me/diagnostics").json()
    sections = {s["id"]: s for s in d["sections"]}
    assert d["status"] == "bad"
    assert sections["connections"]["status"] == "bad"
    assert sections["connections"]["items"][0]["link"] == "/connections"
    assert any("FTP not set" in i["text"] for i in sections["profile"]["items"])
    assert sections["activities"]["items"][0]["text"].startswith("No activities")


def test_connected_athlete(make_user):
    p = make_user("a@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    now = utcnow()
    with SessionLocal() as db:
        u = db.get(User, uid)
        u.ftp_watts, u.lthr_bpm, u.weight_kg, u.timezone = 220, 165, 70, "Africa/Johannesburg"
        db.add(
            Connection(
                user_id=uid, provider="strava", token_enc="x", status="active", last_sync_at=now - timedelta(hours=2)
            )
        )
        db.add(
            Connection(
                user_id=uid, provider="garmin", token_enc="x", status="error", last_error="Garmin rejected the sign-in"
            )
        )
        start = datetime.combine(date.today() - timedelta(days=3), datetime.min.time()) + timedelta(hours=6)
        for src, ext in (("strava", "1"), ("garmin", "2")):  # one ride from both: a copy
            db.add(
                Activity(
                    user_id=uid,
                    source=src,
                    external_id=ext,
                    name="Ride",
                    sport="Ride" if src == "strava" else "road_biking",
                    start_time=start,
                    duration_s=3600,
                    tss=60,
                    tss_method="power",
                    avg_power=180,
                )
            )
        db.add(
            SyncJob(
                athlete_id=uid,
                provider="intervals_icu",
                scheduled_workout_id=1,
                workout_name="Threshold",
                action="upsert",
                status="failed",
                last_error="401 Unauthorized",
            )
        )
        db.commit()
    d = p.get("/api/athletes/me/diagnostics").json()
    s = {x["id"]: x for x in d["sections"]}
    conns = " ".join(i["text"] for i in s["connections"]["items"])
    assert "Strava: connected, last synced 2 h ago." in conns and "Garmin rejected the sign-in" in conns
    assert s["connections"]["status"] == "bad"
    assert any("1 copies" in i["text"] for i in s["activities"]["items"])
    assert any("No main activity source" in i["text"] for i in s["activities"]["items"])
    assert s["profile"]["status"] == "ok" and any("measured" in i["text"] for i in s["profile"]["items"])
    plan = " ".join(i["text"] for i in s["plan"]["items"])
    assert "1 workout deliveries failed" in plan and "401 Unauthorized" in plan
    r = p.get("/api/athletes/me/diagnostics/report.json")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    body = json.loads(r.text)
    assert body["diagnostics"]["status"] == "bad" and len(body["training_load"]["days"]) == 90


def test_who_may_look(make_user):
    p = make_user("a@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    stranger = make_user("b@example.com")
    assert stranger.get(f"/api/athletes/{uid}/diagnostics").status_code in (403, 404)
