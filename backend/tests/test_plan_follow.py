"""The plan follows what was done: another session type that day, or the session on another day."""

from datetime import date, datetime, timedelta
from types import SimpleNamespace

from app import plan_follow
from app.plan_tracker import _blank_day, with_actuals

MON = date(2026, 10, 26)
TODAY = MON + timedelta(days=6)  # Sunday: the whole week is past or today


def _act(day: date, sport: str, minutes=60, indoor=False, override=None):
    return SimpleNamespace(
        start_time=datetime.combine(day, datetime.min.time()) + timedelta(hours=8),
        sport=sport,
        indoor=indoor,
        type_override=override,
        duration_s=minutes * 60,
        distance_m=20000,
        elevation_m=100,
        relative_effort=None,
        avg_power=None,
        avg_hr=None,
        name=sport,
    )


def _week(**sessions) -> list[dict]:
    """A week from MON; keyword = weekday (mon..sun) -> (type, minutes)."""
    days = []
    for i in range(7):
        d = _blank_day(MON + timedelta(days=i))
        if d["weekday"] in sessions:
            kind, minutes = sessions[d["weekday"]]
            d.update(type=kind, duration_min=minutes, description=f"Planned {kind}")
        days.append(d)
    return [{"start": MON.isoformat(), "phase": "Build", "focus": "", "status": "approved", "days": days}]


def _day(weeks, weekday):
    return next(d for d in weeks[0]["days"] if d["weekday"] == weekday)


def test_another_session_type_changes_the_plan_day():
    weeks = _week(sat=("Road", 240), tue=("Walk", 45), wed=("Zwift / indoor", 60))
    weeks[0]["days"][5]["segment_id"] = 7
    acts = [
        _act(MON + timedelta(days=5), "VirtualRide", 230),  # Saturday: Zwift instead of the road ride
        _act(MON + timedelta(days=1), "Run", 40),  # Tuesday: ran instead of walking
        _act(MON + timedelta(days=2), "VirtualRide", 60),  # Wednesday: as planned
    ]
    assert plan_follow.follow(weeks, acts, TODAY)
    sat, tue, wed = _day(weeks, "sat"), _day(weeks, "tue"), _day(weeks, "wed")
    assert sat["type"] == "Zwift / indoor" and sat["segment_id"] is None
    assert sat["changed_from"] == {"type": "Road", "description": "Planned Road", "duration_min": 240, "intensity": []}
    assert tue["type"] == "Outdoor run" and tue["changed_from"]["type"] == "Walk"
    assert wed["type"] == "Zwift / indoor" and "changed_from" not in wed
    status = {d["weekday"]: d["status"] for d in with_actuals(weeks, acts, TODAY)[0]["days"]}
    assert status["sat"] == "goal_met" and status["tue"] == "goal_met"
    assert not plan_follow.follow(weeks, acts, TODAY)  # nothing new the second time


def test_fixing_the_activity_type_puts_the_plan_back():
    weeks = _week(sat=("Road", 240))
    ride = _act(MON + timedelta(days=5), "Ride", 240, indoor=True)  # a trainer ride recorded as a ride
    plan_follow.follow(weeks, [ride], TODAY)
    assert _day(weeks, "sat")["type"] == "Zwift / indoor"
    ride.type_override = "Road"  # the athlete says it was outdoors after all
    plan_follow.follow(weeks, [ride], TODAY)
    assert _day(weeks, "sat")["type"] == "Road" and "changed_from" not in _day(weeks, "sat")


def test_kinds_that_count_as_the_plan():
    weeks = _week(mon=("Hill repeats", 60), tue=("Outdoor run", 40), wed=("Race", 90), thu=("Strength", 45))
    acts = [
        _act(MON, "GravelRide"),
        _act(MON + timedelta(days=1), "TrailRun"),
        _act(MON + timedelta(days=2), "Swim"),
        _act(MON + timedelta(days=3), "Workout"),
    ]
    assert not plan_follow.follow(weeks, acts, TODAY)


def test_extra_sessions_are_paired_too():
    weeks = _week(wed=("Zwift / indoor", 60))
    _day(weeks, "wed")["extra_sessions"] = [
        {"type": "Strength", "description": "", "duration_min": 30, "intensity": []}
    ]
    acts = [_act(MON + timedelta(days=2), "WeightTraining", 30), _act(MON + timedelta(days=2), "Ride", 70)]
    plan_follow.follow(weeks, acts, TODAY)
    wed = _day(weeks, "wed")
    assert wed["type"] == "Road" and wed["changed_from"]["type"] == "Zwift / indoor"
    assert wed["extra_sessions"][0]["type"] == "Strength" and "changed_from" not in wed["extra_sessions"][0]


def test_a_session_done_on_another_day_moves_there():
    weeks = _week(sat=("Road", 240), wed=("Zwift / indoor", 60))
    weeks[0]["days"][5]["segment_id"] = 7
    acts = [_act(MON + timedelta(days=6), "Ride", 245)]  # ridden on Sunday (a rest day) instead
    assert plan_follow.follow(weeks, acts, TODAY)
    sat, sun = _day(weeks, "sat"), _day(weeks, "sun")
    assert sun["type"] == "Road" and sun["duration_min"] == 240 and sun["segment_id"] == 7
    assert sun["moved_from"] == sat["date"] and sat["moved_to"] == sun["date"] and sat["type"] == "Rest"
    status = {d["weekday"]: d["status"] for d in with_actuals(weeks, acts, TODAY)[0]["days"]}
    assert status == {**status, "sat": "moved", "sun": "goal_met", "wed": "missed"}
    assert not plan_follow.follow(weeks, acts, TODAY)


def test_no_move_when_the_type_does_not_fit_or_the_day_is_locked():
    weeks = _week(sat=("Road", 240))
    acts = [_act(MON + timedelta(days=6), "Run", 45)]  # a run on Sunday isn't the long ride
    assert not plan_follow.follow(weeks, acts, TODAY)
    weeks = _week(sat=("Road", 240))
    _day(weeks, "sat")["locked"] = True
    acts = [_act(MON + timedelta(days=6), "Ride", 245), _act(MON + timedelta(days=5), "VirtualRide")]
    assert not plan_follow.follow(weeks, acts, TODAY)


def test_future_days_are_left_alone():
    weeks = _week(sat=("Road", 240))
    acts = [_act(MON + timedelta(days=5), "VirtualRide", 230)]
    assert not plan_follow.follow(weeks, acts, MON + timedelta(days=4))  # Saturday hasn't come yet
