"""Strength training: the exercise library, the athlete's options, and AI-written strength sessions."""

from test_friend_sharing import _friends
from test_phase3 import _create, _week, planner  # noqa: F401  (fixture)

from app import coach, strength
from app.db import SessionLocal, User

SQUAT = "Barbell_Squat"
HIP_THRUST = "Barbell_Hip_Thrust"


def test_library_is_text_only_and_useful():
    lib = strength.library()
    assert len(lib) > 700 and SQUAT in lib and HIP_THRUST in lib
    assert not any("images" in e for e in lib.values())
    assert {e["category"] for e in lib.values()} == {"strength", "plyometrics", "powerlifting", "stretching"}
    assert lib[SQUAT]["instructions"]


def test_shortlist_follows_equipment_level_and_sport():
    home = strength.shortlist(strength.DEFAULTS)  # bodyweight, beginner, cycling
    equipment = {x["equipment"] for x in home}
    assert equipment == {"body only"} and not any(x["kind"] == "plyometrics" for x in home)
    gym = {**strength.DEFAULTS, "equipment": list(strength.EQUIPMENT), "level": "expert", "sports": ["running"]}
    sl = strength.shortlist(gym)
    ids = {x["id"] for x in sl}
    assert SQUAT in ids and any(x["kind"] == "plyometrics" for x in sl)
    assert len(sl) <= sum(strength.SHARES.values())
    # Only legs, hips, trunk and back: no biceps curls.
    assert not any("biceps" in x["muscles"] and len(x["muscles"]) == 1 for x in sl)


def test_profile_options(make_user):
    p = make_user("rider@example.com")
    prefs = p.get("/api/athletes/me/preferences").json()
    assert prefs["strength"] == strength.DEFAULTS and "dumbbells" in prefs["strength_options"]["equipment"]
    body = {
        "equipment": ["dumbbells", "jetpack"],
        "level": "intermediate",
        "sports": ["running", "swimming"],
        "sessions_per_week": 9,
        "minutes": 40,
        "limits": "left knee",
    }
    saved = p.request("PUT", "/api/me/preferences", json={"strength": body}).json()["strength"]
    assert saved == {
        "equipment": ["dumbbells"],
        "level": "intermediate",
        "sports": ["running"],
        "sessions_per_week": 4,
        "minutes": 40,
        "limits": "left knee",
    }
    bad = {**body, "level": "legend"}
    assert p.request("PUT", "/api/me/preferences", json={"strength": bad}).status_code == 422


def test_ai_gets_options_and_shortlist(make_user):
    p = make_user("rider@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    with SessionLocal() as db:
        assert "strength" not in coach.build_facts(db, db.get(User, uid), {"plans"}, {})  # not asked for
    p.request("PUT", "/api/me/preferences", json={"weekday_prefs": {"wed": ["Strength"]}})
    with SessionLocal() as db:
        facts = coach.build_facts(db, db.get(User, uid), {"plans"}, {})
        assert facts["strength"]["options"]["level"] == "beginner" and facts["strength"]["exercises"]
    day = coach.plan_schema()["schema"]["properties"]["weeks"]["items"]["properties"]["days"]["items"]
    assert "strength" in day["required"] and "strength" in day["properties"]["extra_sessions"]["items"]["required"]
    assert "heavy strength twice a week" in coach.SYSTEM_PROMPT


def test_clean_keeps_only_library_exercises():
    raw = {
        "focus": "Heavy legs",
        "exercises": [
            {"id": SQUAT, "sets": 4, "reps": "5", "effort": "RPE 8", "rest_s": 180, "note": "Brace"},
            {"id": "Made_Up_Move", "sets": 3, "reps": "10", "effort": "", "rest_s": 60, "note": ""},
            {"id": HIP_THRUST, "sets": 99, "reps": "8", "effort": "RPE 7", "rest_s": 9999, "note": ""},
        ],
    }
    s = strength.clean(raw)
    assert s["focus"] == "Heavy legs" and [x["id"] for x in s["exercises"]] == [SQUAT, HIP_THRUST]
    assert s["exercises"][0]["name"] == "Barbell Squat"
    assert s["exercises"][1]["sets"] == 10 and s["exercises"][1]["rest_s"] == 600
    assert strength.clean({"exercises": [{"id": "Nope"}]}) is None and strength.clean(None) is None


def test_plan_days_carry_strength_sessions(make_user, planner):  # noqa: F811
    athlete = make_user("rider@example.com")
    session = {
        "focus": "Heavy legs",
        "exercises": [{"id": SQUAT, "sets": 4, "reps": "5", "effort": "RPE 8", "rest_s": 180, "note": ""}],
    }
    week = _week()
    week["days"][1].update(type="Strength", description="Heavy legs", duration_min=45, strength=session, workout=None)
    week["days"][0]["extra_sessions"] = [
        {
            "type": "Strength",
            "description": "Core",
            "duration_min": 20,
            "intensity": [],
            "segment_id": None,
            "strength": {
                "focus": "Core",
                "exercises": [{"id": "Plank", "sets": 3, "reps": "45 s", "effort": "easy", "rest_s": 30, "note": ""}],
            },
        }
    ]
    planner["value"] = [week, week]
    plan = athlete.get(f"/api/athletes/me/plans/{_create(athlete)['id']}").json()
    days = {d["weekday"]: d for d in plan["weeks"][0]["days"]}
    assert days["thu"]["strength"]["exercises"][0]["name"] == "Barbell Squat"
    extra = days["tue"]["extra_sessions"][0]["strength"]
    assert extra["exercises"][0]["id"] == "Plank"


def test_exercise_lookup(make_user):
    p = make_user("rider@example.com")
    found = p.get("/api/exercises?q=squat barbell").json()
    assert any(e["id"] == SQUAT for e in found) and "instructions" not in found[0]
    e = p.get(f"/api/exercises/{SQUAT}").json()
    assert e["instructions"] and e["equipment"] == "barbell"
    assert p.get("/api/exercises/Nope").status_code == 404


def test_exercise_photos_and_super_admin_switch(make_user):
    p = make_user("rider@example.com")
    assert p.get(f"/api/exercises/{SQUAT}").json()["photos"] == 2
    r = p.get(f"/api/exercises/{SQUAT}/photo/0")
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp" and len(r.content) < 40_000
    assert p.get(f"/api/exercises/{SQUAT}/photo/2").status_code == 404
    assert p.get("/api/exercises/..%2F..%2Fexercises.json/photo/0").status_code == 404

    boss = make_user("admin@example.com")
    assert boss.request("PUT", "/api/admin/settings", json={"values": {"exercise_photos": "off"}}).status_code == 200
    assert p.get(f"/api/exercises/{SQUAT}/photo/0").status_code == 404
    assert p.get(f"/api/exercises/{SQUAT}").json()["photos"] == 0
    boss.request("PUT", "/api/admin/settings", json={"values": {"exercise_photos": "on"}})


def test_friends_see_but_cannot_set_options(make_user):
    athlete, friend, aid = _friends(make_user)
    assert friend.get(f"/api/athletes/{aid}/preferences").json()["strength"]["level"] == "beginner"
