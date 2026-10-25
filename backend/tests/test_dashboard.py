from datetime import date, datetime, timedelta

from app.db import AccessLog, Activity, Assessment, SessionLocal

STEADY = [{"kind": "steady", "duration_s": 3600, "power": 0.8}]


def _share(athlete, coach, email, scopes):
    g = athlete.post("/api/grants", json={"coach_email": email, "scopes": scopes}).json()
    coach.post(f"/api/grants/{g['id']}/accept")


def _uid(p):
    return p.get("/api/auth/me").json()["id"]


def _past_day_this_week():
    """A day already gone in this week, or None early on a Monday."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return monday if today > monday else None


def test_rows_follow_what_is_shared(make_user):
    coach = make_user("coach@example.com", "Coach")
    ann = make_user("ann@example.com", "Ann")
    bob = make_user("bob@example.com", "Bob")
    _share(ann, coach, "coach@example.com", ["activities", "fitness", "plans"])
    _share(bob, coach, "coach@example.com", ["activities"])
    aid, bid = _uid(ann), _uid(bob)
    today = date.today()
    ann.post("/api/athletes/me/workouts", json={"day": today.isoformat(), "name": "Tempo", "steps": STEADY})
    past = _past_day_this_week()
    if past:
        ann.post("/api/athletes/me/workouts", json={"day": past.isoformat(), "name": "Missed one", "steps": STEADY})
    with SessionLocal() as db:
        db.add(
            Assessment(
                athlete_id=aid, kind="daily", period_start=today, verdict="rest", content_md="", facts={}, model="t"
            )
        )
        db.add(
            Activity(
                user_id=bid,
                source="strava",
                external_id="1",
                name="Ride",
                sport="Ride",
                start_time=datetime.combine(date.today(), datetime.min.time()) + timedelta(minutes=1),
                duration_s=3600,
                distance_m=30000,
            )
        )
        db.commit()
    rows = coach.get("/api/coach/dashboard").json()
    by = {r["name"]: r for r in rows}
    a, b = by["Ann"], by["Bob"]
    assert rows[0]["name"] == "Ann"  # needs attention first
    assert a["readiness"] == "rest" and "readiness: rest" in a["flags"]
    assert a["today_workouts"][0]["name"] == "Tempo" and a["week"]["scheduled"] == (2 if past else 1)
    if past:
        assert "1 missed" in a["flags"] and a["week"]["missed"] == 1
    assert "load" in a and "volume" in a
    # Bob shares activities only: volume, but no week, readiness or load.
    assert b["volume"]["activities"] == 1 and b["volume"]["minutes"] == 60
    assert "week" not in b and "readiness" not in b and "load" not in b
    with SessionLocal() as db:
        assert db.query(AccessLog).filter_by(viewer_id=_uid(coach), resource="dashboard").count() == 2


def test_comments_and_own_row(make_user):
    coach = make_user("coach@example.com", "Coach")
    ann = make_user("ann@example.com", "Ann")
    _share(ann, coach, "coach@example.com", ["plans"])
    aid = _uid(ann)
    w = ann.post(
        "/api/athletes/me/workouts",
        json={"day": (date.today() + timedelta(days=1)).isoformat(), "name": "Tempo", "steps": STEADY},
    ).json()
    url = f"/api/athletes/{aid}/comments"
    ann.post(url, json={"target": "workout", "target_id": w["id"], "body": "Can we move this?"})
    coach.post(url, json={"target": "workout", "target_id": w["id"], "body": "Yes"})
    rows = coach.get("/api/coach/dashboard?me=true").json()
    ann_row = next(r for r in rows if r["name"] == "Ann")
    assert ann_row["new_comments"] == 1  # the coach's own comment doesn't count
    assert any(r.get("is_me") for r in rows)


def test_only_active_shares(make_user):
    coach = make_user("coach@example.com", "Coach")
    ann = make_user("ann@example.com", "Ann")
    ann.post("/api/grants", json={"coach_email": "coach@example.com", "scopes": ["plans"]})  # not accepted
    assert coach.get("/api/coach/dashboard").json() == []
