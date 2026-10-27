from datetime import date, datetime, timedelta
from types import SimpleNamespace

from app.fitness import dedupe, estimate_tss, pmc, readiness_flags, weekly_volume


def test_one_hour_at_ftp_is_100_tss():
    assert estimate_tss(3600, norm_power=250, ftp=250) == (100.0, "power")


def test_hr_tss_used_without_power():
    tss, method = estimate_tss(3600, avg_hr=150, lthr=150)
    assert (tss, method) == (100.0, "hr")


def test_falls_back_to_effort_then_duration():
    assert estimate_tss(3600, relative_effort=72) == (72.0, "effort")
    assert estimate_tss(7200) == (100.0, "duration")
    assert estimate_tss(0) == (0.0, "none")


def test_pmc_constant_load_converges_and_tsb_uses_yesterday():
    start = date(2026, 1, 1)
    end = start + timedelta(days=299)
    curve = pmc({start + timedelta(days=i): 100 for i in range(300)}, start, end)
    assert curve[0].tsb == 0  # nothing before day one
    assert abs(curve[-1].ctl - 100) < 1
    assert abs(curve[-1].atl - 100) < 0.1
    assert curve[1].tsb == round(curve[0].ctl - curve[0].atl, 1)


def _act(source, minutes_offset, tss=50, duration=3600):
    return SimpleNamespace(
        source=source,
        start_time=datetime(2026, 10, 20, 8) + timedelta(minutes=minutes_offset),
        tss=tss,
        duration_s=duration,
        distance_m=30000,
    )


def test_dedupe_prefers_strava():
    acts = [_act("strava", 0), _act("garmin", 3), _act("garmin", 240)]
    kept = dedupe(acts)
    assert [a.source for a in kept] == ["strava", "garmin"]
    assert kept[1].start_time.hour == 12


def _ride(source, start_min, minutes, sport="VirtualRide", power=None, elevation=0):
    return SimpleNamespace(
        source=source,
        start_time=datetime(2026, 10, 27, 6) + timedelta(minutes=start_min),
        duration_s=minutes * 60,
        sport=sport,
        indoor=False,
        type_override=None,
        avg_power=power,
        norm_power=None,
        elevation_m=elevation,
    )


def test_dedupe_same_source_copies():
    # Zwift and a Garmin head unit both uploaded the same ride to Strava: shown once, the copy with power.
    zwift = _ride("strava", 0, 90, power=108, elevation=454)
    head_unit = _ride("strava", 2, 92)
    assert dedupe([head_unit, zwift]) == [zwift]


def test_dedupe_overlapping_copies_that_start_far_apart():
    # The watch was started 15 minutes before Zwift; most of the Zwift ride overlaps it.
    watch = _ride("garmin", 0, 47, sport="Ride")
    zwift = _ride("strava", 15, 32)
    assert dedupe([watch, zwift]) == [zwift]


def test_dedupe_keeps_separate_sessions():
    ride = _ride("strava", 0, 60)
    next_ride = _ride("strava", 55, 60)  # 5 minutes of overlap: a second ride, not a copy
    strength = _ride("garmin", 10, 40, sport="WeightTraining")  # another kind at the same time
    assert dedupe([ride, next_ride, strength]) == [ride, next_ride, strength]


def test_weekly_volume_buckets_by_monday():
    today = date(2026, 10, 25)  # Sunday
    weeks = weekly_volume([_act("strava", 0)], 2, today)
    assert [w["week_start"] for w in weeks] == ["2026-10-12", "2026-10-19"]
    assert weeks[1]["sessions"] == 1 and weeks[1]["tss"] == 50


def test_readiness_flags():
    load = [SimpleNamespace(day=None, tss=0, ctl=40 + i, atl=80, tsb=-35) for i in range(8)]
    wellness = [SimpleNamespace(hrv_ms=60, resting_hr=50, sleep_s=8 * 3600) for _ in range(23)]
    wellness += [SimpleNamespace(hrv_ms=45, resting_hr=58, sleep_s=6 * 3600) for _ in range(7)]
    flags = " ".join(readiness_flags(load, wellness, []))
    assert "High fatigue" in flags
    assert "HRV suppressed" in flags
    assert "Resting HR elevated" in flags
    assert "Short sleep" in flags
