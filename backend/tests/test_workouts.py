import io
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app import localtime, workouts, zwo
from app.db import Activity, Connection, SessionLocal

STEPS = [
    {"kind": "warmup", "duration_s": 600, "power_start": 0.5, "power_end": 0.75, "text": "Easy spin"},
    {"kind": "intervals", "repeat": 5, "on_s": 60, "on_power": 1.2, "off_s": 60, "off_power": 0.5, "cadence": 100},
    {"kind": "steady", "duration_s": 1200, "power": 0.9, "cadence": 90},
    {"kind": "recovery", "duration_s": 300, "power": 0.5},
    {"kind": "ramp", "duration_s": 300, "power_start": 0.6, "power_end": 1.0},
    {"kind": "free", "duration_s": 300},
    {"kind": "cooldown", "duration_s": 600, "power_start": 0.7, "power_end": 0.4},
]


# ---- Model, power and estimates ----


def test_power_conversion():
    assert workouts.to_watts(0.75, 260) == 195
    assert workouts.to_fraction(195, 260) == 0.75
    assert workouts.to_watts(workouts.to_fraction(287, 265), 265) == 287
    with pytest.raises(ValueError):
        workouts.to_fraction(200, 0)


def test_intervals_expand_into_on_off_blocks():
    steps = workouts.validate_steps(STEPS)
    bl = workouts.blocks(steps)
    on = [b for b in bl if b["kind"] == "on"]
    assert len(on) == 5 and all(b["power_start"] == 1.2 and b["cadence"] == 100 for b in on)
    assert bl[1]["start_s"] == 600 and bl[2]["start_s"] == 660
    assert workouts.duration(steps) == 600 + 5 * 120 + 1200 + 300 + 300 + 300 + 600
    assert bl[-1]["start_s"] + bl[-1]["duration_s"] == workouts.duration(steps)


def test_estimate_tss_and_if():
    hour_at_ftp = workouts.estimate([{"kind": "steady", "duration_s": 3600, "power": 1.0}], ftp=250)
    assert hour_at_ftp["intensity_factor"] == 1.0 and hour_at_ftp["tss"] == 100
    assert hour_at_ftp["np_watts"] == 250 and hour_at_ftp["avg_watts"] == 250
    easy = workouts.estimate([{"kind": "steady", "duration_s": 3600, "power": 0.75}])
    assert easy["intensity_factor"] == 0.75 and easy["tss"] == 56 and "avg_watts" not in easy
    # Hard intervals push normalised power above average power.
    mixed = workouts.estimate(workouts.validate_steps(STEPS), ftp=250)
    assert mixed["free_ride_s"] == 300 and mixed["np_watts"] > mixed["avg_watts"]
    free_only = workouts.estimate([{"kind": "free", "duration_s": 600}])
    assert free_only["tss"] is None and free_only["intensity_factor"] is None


@pytest.mark.parametrize(
    "bad",
    [
        [],
        [{"kind": "sprint", "duration_s": 60}],
        [{"kind": "steady", "duration_s": 60, "power": 5}],
        [{"kind": "steady", "duration_s": 60, "power": 0.8, "watts": 200}],
        [{"kind": "intervals", "repeat": 0, "on_s": 60, "on_power": 1, "off_s": 60, "off_power": 0.5}],
        [{"kind": "steady", "duration_s": 6 * 3600, "power": 0.6}] * 2,
    ],
)
def test_bad_steps_are_refused(bad):
    with pytest.raises(ValueError):
        workouts.validate_steps(bad)


def test_zones():
    assert [workouts.zone(x) for x in (0.5, 0.7, 0.85, 1.0, 1.1, 1.5)] == ["Z1", "Z2", "Z3", "Z4", "Z5", "Z6"]


# ---- ZWO ----


def test_zwo_is_valid_and_complete():
    w = {
        "name": "Hills & <thresholds>",
        "description": "Kendal climb",
        "instructions": "Stay seated",
        "steps": workouts.validate_steps(STEPS),
    }
    root = ET.fromstring(zwo.zwo(w, "Coach Mike"))
    assert root.tag == "workout_file"
    assert root.findtext("name") == "Hills & <thresholds>"
    assert root.findtext("author") == "Coach Mike" and root.findtext("sportType") == "bike"
    assert root.findtext("description") == "Kendal climb\n\nStay seated"
    els = list(root.find("workout"))
    assert [e.tag for e in els] == [
        "Warmup",
        "IntervalsT",
        "SteadyState",
        "SteadyState",
        "Ramp",
        "FreeRide",
        "Cooldown",
    ]
    warm, ints, steady, _, _, _, cool = els
    assert warm.attrib == {"Duration": "600", "PowerLow": "0.5", "PowerHigh": "0.75"}
    assert warm.find("textevent").get("message") == "Easy spin"
    assert ints.attrib == {
        "Repeat": "5",
        "OnDuration": "60",
        "OffDuration": "60",
        "OnPower": "1.2",
        "OffPower": "0.5",
        "Cadence": "100",
    }
    assert steady.get("Power") == "0.9" and steady.get("Cadence") == "90"
    # Cool-downs go from PowerLow (start) to PowerHigh (end), as Zwift reads them.
    assert cool.get("PowerLow") == "0.7" and cool.get("PowerHigh") == "0.4"


def test_zip_has_instructions_and_unique_names():
    w = {"name": "VO2 / max", "steps": [{"kind": "steady", "duration_s": 600, "power": 0.6}]}
    data = zwo.plan_zip([(date(2026, 10, 27), w), (date(2026, 10, 27), w), (date(2026, 10, 29), w)])
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert names == [
        "HOW TO ADD TO ZWIFT.txt",
        "2026-10-27 VO2 max.zwo",
        "2026-10-27 VO2 max 2.zwo",
        "2026-10-29 VO2 max.zwo",
    ]
    assert zwo.filename("VO2 max 5×3") == "VO2 max 5x3.zwo"


# ---- Timezones ----


def test_local_days():
    jhb = localtime.zone("Africa/Johannesburg")
    assert localtime.local_date(datetime(2026, 10, 26, 23, 30), jhb) == date(2026, 10, 27)
    assert localtime.local_date(datetime(2026, 10, 26, 21, 0), jhb) == date(2026, 10, 26)
    user = SimpleNamespace(timezone="Pacific/Auckland")
    assert localtime.today(user, datetime(2026, 10, 26, 20, 0, tzinfo=UTC)) == date(2026, 10, 27)
    assert localtime.today(SimpleNamespace(timezone=None), datetime(2026, 10, 26, 20, 0, tzinfo=UTC)) == date(
        2026, 10, 26
    )
    assert localtime.valid("Africa/Johannesburg") and not localtime.valid("Mars/Base") and not localtime.valid("EST")


# ---- API ----


def _body(name="Threshold", steps=None):
    return {"name": name, "description": "2x20", "steps": steps or STEPS}


def _setup(make_user, scopes=("plans",)):
    athlete = make_user("athlete@example.com", "Athlete")
    coach = make_user("coach@example.com", "Coach")
    athlete_id = athlete.get("/api/auth/me").json()["id"]
    g = athlete.post("/api/grants", json={"coach_email": "coach@example.com", "scopes": list(scopes)}).json()
    assert coach.post(f"/api/grants/{g['id']}/accept").status_code == 200
    return athlete, coach, athlete_id


def test_library_is_private(make_user):
    a = make_user("a@example.com")
    b = make_user("b@example.com")
    w = a.post("/api/workouts", json=_body()).json()
    assert w["estimate"]["duration_s"] == workouts.duration(workouts.validate_steps(STEPS))
    assert [x["id"] for x in a.get("/api/workouts").json()] == [w["id"]]
    assert b.get(f"/api/workouts/{w['id']}").status_code == 404
    assert b.get("/api/workouts").json() == []
    assert b.request("PUT", f"/api/workouts/{w['id']}", json=_body("Mine")).status_code == 404
    bad = a.post("/api/workouts", json=_body(steps=[{"kind": "steady", "duration_s": 60, "power": 9}]))
    assert bad.status_code == 422 and "Step" in bad.json()["detail"]
    r = a.request("PUT", f"/api/workouts/{w['id']}", json=_body("Sweet spot"))
    assert r.json()["name"] == "Sweet spot"
    zwo_r = a.get(f"/api/workouts/{w['id']}/zwo")
    assert zwo_r.status_code == 200 and "Sweet spot.zwo" in zwo_r.headers["content-disposition"]
    ET.fromstring(zwo_r.text)


def test_preview_uses_ftp(make_user):
    a = make_user("a@example.com")
    a.patch("/api/me", json={"ftp_watts": 250})
    r = a.post("/api/workouts/preview", json={"steps": [{"kind": "steady", "duration_s": 3600, "power": 1.0}]})
    assert r.json()["estimate"]["np_watts"] == 250 and r.json()["blocks"][0]["duration_s"] == 3600
    r = a.post(
        "/api/workouts/preview", json={"ftp": 300, "steps": [{"kind": "steady", "duration_s": 600, "power": 1.0}]}
    )
    assert r.json()["estimate"]["avg_watts"] == 300


def test_coach_assigns_and_athlete_sees(make_user):
    athlete, coach, athlete_id = _setup(make_user)
    tpl = coach.post("/api/workouts", json=_body()).json()
    day = date.today() + timedelta(days=3)
    r = coach.post(f"/api/athletes/{athlete_id}/workouts", json={"day": day.isoformat(), "template_id": tpl["id"]})
    assert r.status_code == 200, r.text
    sw = r.json()
    assert sw["status"] == "planned" and sw["assigned_by"] == "Coach" and sw["delivery"] == []
    # The athlete can't use the coach's library, but sees the workout on their calendar.
    assert (
        athlete.post("/api/athletes/me/workouts", json={"day": day.isoformat(), "template_id": tpl["id"]}).status_code
        == 404
    )
    cal = athlete.get(f"/api/athletes/me/calendar?start={day}&end={day}").json()
    assert cal["days"][0]["workouts"][0]["name"] == "Threshold"
    # Editing the library workout later doesn't change what was assigned.
    coach.request("PUT", f"/api/workouts/{tpl['id']}", json=_body("Renamed"))
    cal = athlete.get(f"/api/athletes/me/calendar?start={day}&end={day}").json()
    assert cal["days"][0]["workouts"][0]["name"] == "Threshold"
    # Reschedule (drag to another day), then skip.
    new_day = day + timedelta(days=1)
    athlete.patch(f"/api/athletes/me/workouts/{sw['id']}", json={"day": new_day.isoformat()})
    cal = athlete.get(f"/api/athletes/me/calendar?start={day}&end={new_day}").json()
    assert cal["days"][0]["workouts"] == [] and cal["days"][1]["workouts"][0]["id"] == sw["id"]
    athlete.patch(f"/api/athletes/me/workouts/{sw['id']}", json={"status": "skipped"})
    cal = athlete.get(f"/api/athletes/me/calendar?start={new_day}&end={new_day}").json()
    assert cal["days"][0]["workouts"][0]["status"] == "skipped"


def test_access_needs_plans_scope(make_user):
    athlete, coach, athlete_id = _setup(make_user, scopes=("activities",))
    today = date.today().isoformat()
    assert coach.get(f"/api/athletes/{athlete_id}/calendar?start={today}&end={today}").status_code == 404
    r = coach.post(f"/api/athletes/{athlete_id}/workouts", json={"day": today, "name": "Sneaky", "steps": STEPS[:1]})
    assert r.status_code == 404
    assert coach.get(f"/api/athletes/{athlete_id}/platforms").status_code == 404
    other = make_user("other@example.com")
    sw = athlete.post("/api/athletes/me/workouts", json={"day": today, "name": "Mine", "steps": STEPS[:1]}).json()
    assert other.get(f"/api/athletes/{athlete_id}/workouts/{sw['id']}/zwo").status_code == 404
    assert other.delete(f"/api/athletes/{athlete_id}/workouts/{sw['id']}").status_code == 404


def _ride(user_id, start_utc, minutes, ext, **kw):
    with SessionLocal() as db:
        db.add(
            Activity(
                user_id=user_id,
                source="strava",
                external_id=ext,
                name="Zwift - Threshold",
                sport=kw.pop("sport", "VirtualRide"),
                start_time=start_utc,
                duration_s=minutes * 60,
                distance_m=30000,
                **kw,
            )
        )
        db.commit()


def test_calendar_status_and_timezone(make_user):
    a = make_user("a@example.com")
    uid = a.get("/api/auth/me").json()["id"]
    a.patch("/api/me", json={"timezone": "Africa/Johannesburg", "ftp_watts": 250})
    assert a.patch("/api/me", json={"timezone": "Nowhere/Land"}).status_code == 422
    today = date.today()
    past = today - timedelta(days=5)
    one_hour = [{"kind": "steady", "duration_s": 3600, "power": 0.8}]
    for d in (past, past + timedelta(days=1), past + timedelta(days=2)):
        a.post("/api/athletes/me/workouts", json={"day": d.isoformat(), "name": "Endurance", "steps": one_hour})
    # 23:30 UTC the evening before = 01:30 in Johannesburg on `past`.
    _ride(
        uid,
        datetime.combine(past - timedelta(days=1), datetime.min.time()) + timedelta(hours=23, minutes=30),
        58,
        "1",
        avg_power=200,
        norm_power=210,
        avg_hr=140,
    )
    _ride(uid, datetime.combine(past + timedelta(days=1), datetime.min.time()) + timedelta(hours=8), 20, "2")
    # A run that day doesn't count towards a bike workout.
    _ride(
        uid, datetime.combine(past + timedelta(days=2), datetime.min.time()) + timedelta(hours=8), 60, "3", sport="Run"
    )
    cal = a.get(f"/api/athletes/me/calendar?start={past}&end={past + timedelta(days=2)}").json()
    assert cal["timezone"] == "Africa/Johannesburg"
    done, partial, missed = (d["workouts"][0] for d in cal["days"])
    assert done["status"] == "done"
    assert done["actual"]["completion_pct"] == 97 and done["actual"]["intensity_factor"] == 0.84
    assert done["actual"]["avg_hr"] == 140 and done["estimate"]["avg_watts"] == 200
    assert partial["status"] == "partial" and partial["actual"]["avg_power"] is None
    assert missed["status"] == "missed" and cal["days"][2]["activities"][0]["type"] == "Run"
    assert a.get(f"/api/athletes/me/calendar?start={today}&end={today - timedelta(days=1)}").status_code == 422


def test_calendar_shows_plan_days(make_user, monkeypatch):
    async def fake_generate(db, viewer, athlete, facts):
        days = [
            {"weekday": "tue", "type": "Zwift / indoor", "description": "Hills", "duration_min": 60, "intensity": []}
        ]
        return {"summary_md": "", "weeks": [{"phase": "Build", "focus": "", "days": days}]}, "claude-test"

    monkeypatch.setattr("app.routers.plans.generate_plan", fake_generate)
    a = make_user("a@example.com")
    monday = date.today() - timedelta(days=date.today().weekday())
    plan = a.post(
        "/api/athletes/me/plans",
        json={"without_data": True, "title": "DC", "goal": "DC", "weeks": 1, "start_date": monday.isoformat()},
    ).json()
    cal = a.get(f"/api/athletes/me/calendar?start={monday}&end={monday + timedelta(days=6)}").json()
    assert cal["days"][1]["plan"]["type"] == "Zwift / indoor" and cal["days"][0]["plan"]["type"] == "Rest"
    # Whole-plan ZIP: the workouts scheduled inside the plan's dates.
    assert a.get(f"/api/athletes/me/workouts/export.zip?plan_id={plan['id']}").status_code == 404
    a.post(
        "/api/athletes/me/workouts", json={"day": (monday + timedelta(1)).isoformat(), "name": "Hills", "steps": STEPS}
    )
    gone = a.post(
        "/api/athletes/me/workouts", json={"day": (monday + timedelta(3)).isoformat(), "name": "Old", "steps": STEPS}
    ).json()
    a.patch(f"/api/athletes/me/workouts/{gone['id']}", json={"status": "cancelled"})
    r = a.get(f"/api/athletes/me/workouts/export.zip?plan_id={plan['id']}")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert names == ["HOW TO ADD TO ZWIFT.txt", f"{(monday + timedelta(1)).isoformat()} Hills.zwo"]


def test_platforms(make_user):
    athlete, coach, athlete_id = _setup(make_user)
    with SessionLocal() as db:
        db.add(
            Connection(
                user_id=athlete_id,
                provider="strava",
                external_id="12345",
                token_enc="x",
                status="error",
                last_error="Strava said 401",
            )
        )
        db.commit()
    mine = {p["id"]: p for p in athlete.get("/api/athletes/me/platforms").json()}
    assert mine["zwift"]["status"] == "export_only" and mine["zwift"]["capabilities"][0]["id"] == "export_files"
    assert mine["mywhoosh"]["experimental"] and mine["mywhoosh"]["status"] == "not_available"
    assert mine["strava"]["status"] == "error" and mine["strava"]["last_error"] == "Strava said 401"
    assert mine["strava"]["account"] == "12345" and mine["garmin"]["status"] == "not_connected"
    assert not any(p["auto_sync_available"] for p in mine.values())
    theirs = {p["id"]: p for p in coach.get(f"/api/athletes/{athlete_id}/platforms").json()}
    assert theirs["strava"]["status"] == "error" and theirs["strava"]["last_error"] is None
    # No integration can deliver workouts yet, so automatic delivery is refused.
    r = athlete.request("PUT", "/api/me/platforms", json={"preferred": ["zwift"], "auto": {"zwift": True}})
    assert r.status_code == 409
    r = athlete.request("PUT", "/api/me/platforms", json={"preferred": ["zwift"], "auto": {}})
    assert {p["id"]: p for p in r.json()}["zwift"]["preferred"]
    assert athlete.request("PUT", "/api/me/platforms", json={"preferred": ["peloton"]}).status_code == 422


def test_coach_with_plans_only_sees_no_watts_or_ride_details(make_user):
    athlete, coach, athlete_id = _setup(make_user, scopes=("plans",))
    athlete.patch("/api/me", json={"ftp_watts": 300})
    past = date.today() - timedelta(days=3)
    one_hour = [{"kind": "steady", "duration_s": 3600, "power": 0.8}]
    athlete.post("/api/athletes/me/workouts", json={"day": past.isoformat(), "name": "Endurance", "steps": one_hour})
    start = datetime.combine(past, datetime.min.time()) + timedelta(hours=10)
    _ride(athlete_id, start, 60, "9", avg_power=240, norm_power=250, avg_hr=150)
    url = f"/api/athletes/{athlete_id}/calendar?start={past}&end={past}"
    day = coach.get(url).json()["days"][0]
    w = day["workouts"][0]
    assert w["status"] == "done" and w["actual"]["completion_pct"] == 100
    assert "avg_watts" not in w["estimate"] and "avg_power" not in w["actual"]
    assert day["activities"] == [] and coach.get(url).json()["ftp_watts"] is None
    mine = athlete.get(f"/api/athletes/me/calendar?start={past}&end={past}").json()["days"][0]
    assert mine["workouts"][0]["estimate"]["avg_watts"] == 240 and mine["workouts"][0]["actual"]["avg_hr"] == 150
