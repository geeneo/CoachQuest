"""'How is your week going?' (week_status.py), checked in code."""

from datetime import date, datetime, timedelta

from app.db import Activity, Assessment, Plan, Race, SessionLocal

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _plan(aid, start, sessions):
    """sessions: {day offset: (type, minutes)}; the rest are rest days."""
    days = []
    for i in range(7):
        kind, minutes = sessions.get(i, ("Rest", 0))
        days.append(
            {
                "date": (start + timedelta(days=i)).isoformat(),
                "weekday": WEEKDAYS[(start + timedelta(days=i)).weekday()],
                "type": kind,
                "description": "",
                "duration_min": minutes,
                "intensity": ["Z2"] if kind != "Rest" else [],
                "locked": False,
            }
        )
    with SessionLocal() as db:
        db.add(
            Plan(
                athlete_id=aid,
                author_id=aid,
                title="P",
                content_md="",
                model="m",
                start_date=start,
                approval="approved",
                weeks=[{"start": start.isoformat(), "phase": "Peak", "focus": "", "status": "draft", "days": days}],
            )
        )
        db.commit()


def _ride(aid, day, minutes, tss, sport="Ride"):
    with SessionLocal() as db:
        db.add(
            Activity(
                user_id=aid,
                source="strava",
                external_id=f"{day}{minutes}",
                name="Ride",
                sport=sport,
                start_time=datetime.combine(day, datetime.min.time()) + timedelta(hours=7),
                duration_s=minutes * 60,
                distance_m=minutes * 400,
                elevation_m=100,
                tss=tss,
            )
        )
        db.commit()


def test_on_track_then_concerns(make_user):
    p = make_user("a@example.com")
    aid = p.get("/api/auth/me").json()["id"]
    today = date.today()
    start = today - timedelta(days=3)  # a week that began three days ago
    _plan(aid, start, {0: ("Road", 120), 1: ("Zwift / indoor", 60), 2: ("Road", 60), 4: ("Road", 90)})
    _ride(aid, start, 120, 100)
    _ride(aid, start + timedelta(days=1), 60, 50, "VirtualRide")
    _ride(aid, start + timedelta(days=2), 60, 50)
    w = p.get("/api/athletes/me/coach/week").json()
    assert w["verdict"] in ("on", "watch") and w["points"][0] == {"level": "ok", "text": "3 of 3 sessions done so far."}
    assert any(x["text"].startswith("Time: 4h 00m of the 4h 00m planned so far (100%)") for x in w["points"])
    assert "the week ends at 5h 30m" in w["projection"]

    # A missed day, a readiness note saying REST with a session today, and a race too close for its target.
    other = make_user("b@example.com")
    bid = other.get("/api/auth/me").json()["id"]
    _plan(bid, start, {0: ("Road", 120), 1: ("Road", 60), 3: ("Road", 60)})
    _ride(bid, start, 120, 100)
    with SessionLocal() as db:
        db.add(
            Assessment(
                athlete_id=bid, kind="daily", period_start=today, verdict="rest", content_md="", facts={}, model="m"
            )
        )
        db.add(Race(user_id=bid, code="dc", name="DC", target_date=today + timedelta(days=17), target_ctl=65))
        db.commit()
    w = other.get("/api/athletes/me/coach/week").json()
    texts = " ".join(x["text"] for x in w["points"])
    assert w["verdict"] == "watch" and w["headline"].startswith("Mostly on track: 4 things")
    assert "1 of 2 sessions done before today: missed" in texts and "a little behind" in texts
    assert "readiness says REST" in texts
    assert "DC in 17 days" in texts and "arrive fresh" in texts


def test_no_current_plan(make_user):
    p = make_user("a@example.com")
    assert p.get("/api/athletes/me/coach/week").json() is None


def test_reviews_follow_the_plan_weeks(make_user):
    """A plan made with Saturday weeks keeps them, whatever Profile's "My week starts on" says now."""
    from app.assessments import this_week_start
    from app.db import User

    p = make_user("a@example.com")
    aid = p.get("/api/auth/me").json()["id"]
    today = date.today()
    saturday = today - timedelta(days=(today.weekday() - 5) % 7)
    _plan(aid, saturday, {0: ("Road", 120)})
    with SessionLocal() as db:
        u = db.get(User, aid)
        u.week_start = 0  # Monday in Profile
        db.commit()
        assert this_week_start(db, u, today) == saturday
        # Without a plan for this week: the Profile's day.
        assert this_week_start(db, u, today + timedelta(days=30)).weekday() == 0


def test_delete_a_review(make_user):
    p = make_user("a@example.com")
    aid = p.get("/api/auth/me").json()["id"]
    with SessionLocal() as db:
        a = Assessment(athlete_id=aid, kind="weekly", period_start=date.today(), content_md="x", facts={}, model="m")
        db.add(a)
        db.commit()
        rid = a.id
    other = make_user("b@example.com")
    assert other.request("DELETE", f"/api/athletes/{aid}/coach/assessments/{rid}").status_code == 404
    assert p.request("DELETE", f"/api/athletes/me/coach/assessments/{rid}").json() == {"ok": True}
    assert p.get("/api/athletes/me/coach").json()["weekly"] == []
