"""Planned vs done per day and week, with fitness and form, for the Plans strip and the Calendar."""

from datetime import date, datetime, timedelta

from app.db import Activity, Plan, SessionLocal
from app.plan_tracker import planned_tss

STEPS = [{"kind": "steady", "duration_s": 3600, "power": 0.75}]


def test_planned_tss():
    assert planned_tss({"type": "Road", "duration_min": 300, "intensity": ["Z2"]}) == round(5 * 0.68**2 * 100)
    assert planned_tss({"type": "Road", "duration_min": 60, "intensity": ["Z4 intervals", "Z2"]}) == 90
    assert planned_tss({"type": "Zwift / indoor", "duration_min": 60, "workout": {"name": "w", "steps": STEPS}}) == 56
    assert planned_tss({"type": "Strength", "duration_min": 45}) == 0
    assert planned_tss({"type": "Rest", "duration_min": 0}) == 0


def test_week_totals_and_load(make_user):
    p = make_user("a@example.com")
    aid = p.get("/api/auth/me").json()["id"]
    today = date.today()
    start = today - timedelta(days=today.weekday())
    with SessionLocal() as db:
        db.add(
            Activity(
                user_id=aid,
                source="strava",
                external_id="1",
                name="Long ride",
                sport="Ride",
                start_time=datetime.combine(start, datetime.min.time()) + timedelta(hours=7),
                duration_s=4 * 3600,
                distance_m=120000,
                elevation_m=1300,
                tss=230,
            )
        )
        days = []
        for i in range(7):
            d = start + timedelta(days=i)
            days.append(
                {
                    "date": d.isoformat(),
                    "weekday": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][i],
                    "type": "Road" if i in (0, 3) else "Rest",
                    "description": "",
                    "duration_min": 240 if i == 0 else 60 if i == 3 else 0,
                    "intensity": ["Z2"] if i == 0 else [],
                    "locked": False,
                }
            )
        plan = Plan(
            athlete_id=aid,
            author_id=aid,
            title="P",
            content_md="",
            model="m",
            start_date=start,
            approval="approved",
            weeks=[{"start": start.isoformat(), "phase": "Build", "focus": "", "status": "draft", "days": days}],
        )
        db.add(plan)
        db.commit()
        plan_id = plan.id
    out = p.get(f"/api/athletes/me/plans/{plan_id}").json()
    week = out["weeks"][0]
    mon = week["days"][0]
    assert mon["actual"]["tss"] == 230 and mon["planned_tss"] == round(4 * 0.68**2 * 100)
    s = week["summary"]
    assert s["logged_tss"] == 230 and s["logged_km"] == 120 and s["logged_elevation_m"] == 1300
    assert s["planned_tss"] == mon["planned_tss"] + round(0.68**2 * 100)
    assert out["load"][start.isoformat()]["ctl"] > 0
    # Planned km: 4 h at the usual 30 km/h (the one ride: 120 km in 4 h), and none for a rest day.
    assert mon["planned_km"] == 120 and mon["planned_from"] == "estimate"
    assert "planned_km" not in week["days"][1]
    cal = p.get(f"/api/athletes/me/calendar?start={start}&end={start + timedelta(days=6)}").json()
    first = cal["days"][0]
    assert first["plan"]["planned_tss"] == mon["planned_tss"] and first["load"]["ctl"] > 0


def test_review_written_mid_week_knows_the_new_week(make_user):
    from app import assessments
    from app.db import User

    p = make_user("a@example.com")
    aid = p.get("/api/auth/me").json()["id"]
    today = date.today()
    this_monday = today - timedelta(days=today.weekday())
    last_monday = this_monday - timedelta(days=7)
    weekdays = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

    def week(start):
        return {
            "start": start.isoformat(),
            "phase": "Build",
            "focus": "",
            "status": "draft",
            "days": [
                {
                    "date": (start + timedelta(days=i)).isoformat(),
                    "weekday": weekdays[i],
                    "type": "Road",
                    "description": "",
                    "duration_min": 60,
                    "intensity": ["Z2"],
                    "locked": False,
                }
                for i in range(7)
            ],
        }

    with SessionLocal() as db:
        db.add(
            Plan(
                athlete_id=aid,
                author_id=aid,
                title="P",
                content_md="",
                model="m",
                start_date=last_monday,
                weeks=[week(last_monday), week(this_monday)],
            )
        )
        db.commit()
        user = db.get(User, aid)
        written = this_monday + timedelta(days=3)  # Thursday of the new week
        facts = assessments.weekly_facts(db, user, {"plans", "fitness"}, last_monday, written)
        assert (
            facts["written_on"] == written.isoformat()
            and facts["load"]["as_of"] == (this_monday - timedelta(days=1)).isoformat()
        )
        assert facts["load_today"]["date"] == written.isoformat()
        cw = facts["current_week"]
        # Thursday has nothing logged: it's still to come, with Friday to Sunday.
        assert [d["date"] for d in cw["so_far"]] == [(this_monday + timedelta(days=i)).isoformat() for i in range(3)]
        assert len(cw["still_to_come"]) == 4 and cw["still_to_come"][0]["minutes"] == 60
        # Written on the new week's first day: all of it still to come; today's load is the week's end.
        facts = assessments.weekly_facts(db, user, {"plans", "fitness"}, last_monday, this_monday)
        assert facts["current_week"]["so_far"] == [] and len(facts["current_week"]["still_to_come"]) == 7
        assert "load_today" not in facts
    assert "never contradict them" in assessments.WEEKLY_PROMPT
    assert "Never advise a date before\n`written_on`" in assessments.WEEKLY_PROMPT


def test_planned_distance_from_a_route():
    from app.ride_info import planned_distance

    route = {"kind": "route", "distance_m": 128500, "elevation_m": 1288}
    day = {"type": "Road", "duration_min": 316, "segment": route}
    assert planned_distance(day, 25) == {"planned_km": 128.5, "planned_elevation_m": 1288, "planned_from": "route"}
    climb = {"kind": "segment", "distance_m": 700, "elevation_m": 45}
    assert planned_distance({"type": "Road", "duration_min": 60, "segment": climb}, 25)["planned_from"] == "estimate"
    assert planned_distance({"type": "Zwift / indoor", "duration_min": 60}, 25) == {}


def test_review_sees_the_planned_sessions_and_the_following_week(make_user):
    """The days ahead carry their description and route, and the plan's next week comes along."""
    from app import assessments
    from app.db import Segment, User

    p = make_user("a@example.com")
    aid = p.get("/api/auth/me").json()["id"]
    today = date.today()
    this_sat = today - timedelta(days=(today.weekday() - 5) % 7)
    last_sat = this_sat - timedelta(days=7)
    names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    with SessionLocal() as db:
        seg = Segment(athlete_id=aid, strava_id=9, kind="route", name="OuMeul Out and Back", distance_m=86400)
        db.add(seg)
        db.flush()

        def week(start, long_ride=False):
            days = []
            for i in range(7):
                d = start + timedelta(days=i)
                day = {
                    "date": d.isoformat(),
                    "weekday": names[d.weekday()],
                    "type": "Rest",
                    "description": "",
                    "duration_min": 0,
                    "intensity": [],
                    "locked": False,
                }
                if long_ride and i == 0:
                    day.update(
                        type="Road",
                        duration_min=212,
                        description="OuMeul as planned: 2x15 min tempo.",
                        segment_id=seg.id,
                    )
                days.append(day)
            return {
                "start": start.isoformat(),
                "phase": "Peak",
                "focus": "Last quality week",
                "status": "draft",
                "days": days,
            }

        db.add(
            Plan(
                athlete_id=aid,
                author_id=aid,
                title="P",
                content_md="",
                model="m",
                start_date=last_sat,
                approval="approved",
                weeks=[week(last_sat), week(this_sat), week(this_sat + timedelta(days=7), long_ride=True)],
            )
        )
        db.commit()
        user = db.get(User, aid)
        facts = assessments.weekly_facts(db, user, {"plans"}, last_sat, this_sat + timedelta(days=2))
        nxt = facts["current_week"]["following_week"]
        sat = nxt["days"][0]
        assert nxt["focus"] == "Last quality week"
        assert sat["route"] == "OuMeul Out and Back, 86.4 km" and sat["description"].startswith("OuMeul as planned")
