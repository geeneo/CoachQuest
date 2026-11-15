"""A session kept from Intervals.icu counts with CoachQuest's own scoring of its Garmin/Strava copy."""

from datetime import datetime, timedelta

from app import queries
from app.db import Activity, Connection, SessionLocal
from app.fitness import counted_tss, dedupe


def _act(uid, source, ext, tss, method, start, minutes=120):
    return Activity(
        user_id=uid,
        source=source,
        external_id=ext,
        name="MTB",
        sport="MountainBikeRide" if source != "intervals_icu" else "MountainBikeRide",
        start_time=start,
        duration_s=minutes * 60,
        distance_m=45000,
        elevation_m=300,
        avg_hr=140,
        tss=tss,
        tss_method=method,
    )


def test_counted_tss_prefers_our_scoring_of_a_copy():
    start = datetime(2026, 11, 14, 6, 10)
    icu = _act(1, "intervals_icu", "i1", 80, "intervals_icu", start)
    garmin = _act(1, "garmin", "g1", 120, "hr zones", start)
    copies: dict = {}
    kept = dedupe([icu, garmin], "intervals_icu", copies)
    assert kept == [icu]
    assert counted_tss(icu, copies) == (120, "hr zones (garmin copy)")
    # Only Intervals.icu has it: its own load stays.
    alone: dict = {}
    dedupe([icu], "intervals_icu", alone)
    assert counted_tss(icu, alone) == (80, "intervals_icu")
    # Power wins over heart rate when both copies are there.
    strava = _act(1, "strava", "s1", 100, "power", start)
    both: dict = {}
    dedupe([icu, garmin, strava], "intervals_icu", both)
    assert counted_tss(icu, both) == (100, "power (strava copy)")


def test_fitness_and_audit_use_the_copy(make_user):
    p = make_user("a@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    day = datetime.now() - timedelta(days=1)
    with SessionLocal() as db:
        main = {"activities": True, "primary": True}  # Intervals.icu is the athlete's main source
        db.add(Connection(user_id=uid, provider="intervals_icu", token_enc="", options=main))
        db.add(Connection(user_id=uid, provider="garmin", token_enc=""))
        db.add(_act(uid, "intervals_icu", "i1", 80, "intervals_icu", day))
        db.add(_act(uid, "garmin", "g1", 120, "hr zones", day))
        db.commit()
        by_day = queries.daily_load(db, uid)
    assert sum(by_day.values()) == 120
    audit = p.get("/api/athletes/me/load-audit?days=7").json()
    counted = [a for a in audit["activities"] if a["status"] == "counted"]
    assert len(counted) == 1 and counted[0]["counted_tss"] == 120
    assert counted[0]["method"] == "hr zones (garmin copy)"
    assert any("Garmin copy" in m["label"] for m in audit["summary"]["by_method"])
