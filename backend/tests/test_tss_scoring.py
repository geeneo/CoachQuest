"""Training load by sport (fitness.score), as TrainingPeaks counts it."""

from types import SimpleNamespace

from app.fitness import rescore, score


def _a(sport, minutes=60, **kw):
    return SimpleNamespace(
        sport=sport,
        type_override=None,
        indoor=False,
        duration_s=minutes * 60,
        norm_power=kw.get("np"),
        avg_power=kw.get("ap"),
        avg_hr=kw.get("hr"),
        relative_effort=kw.get("re"),
        tss=None,
        tss_method=kw.get("method", "duration"),
    )


USER = SimpleNamespace(ftp_watts=212, lthr_bpm=160, run_ftp_watts=None)


def test_rides_by_power_against_ftp():
    assert score(_a("Ride", 60, np=170), USER) == (round((170 / 212) ** 2 * 100, 1), "power")
    assert score(_a("Ride", 60, hr=140), USER)[1] == "hr"


def test_runs_never_use_cycling_ftp():
    # Running power (here 330 W) against a 212 W cycling FTP was IF 1.56: about 240 TSS an hour.
    tss, how = score(_a("Run", 60, np=330, hr=150), USER)
    assert how == "hr" and tss == round((150 / 160) ** 2 * 100, 1)
    with_run_ftp = SimpleNamespace(ftp_watts=212, lthr_bpm=160, run_ftp_watts=300)
    assert score(_a("Run", 60, np=330), with_run_ftp) == (round((330 / 300) ** 2 * 100, 1), "power")


def test_walks_and_strength_by_heart_rate():
    hr = round((120 / 160) ** 2 * 100, 1)
    for sport in ("WeightTraining", "Yoga", "Workout", "strength_training"):
        assert score(_a(sport, 60, hr=120, re=40), USER) == (hr, "hr")
        assert score(_a(sport, 45, re=40), USER) == (0.0, "no heart rate")  # no estimate, as TrainingPeaks
    assert score(_a("Walk", 60, hr=120), USER) == (round(hr * 0.65, 1), "walk hr")
    assert score(_a("Walk", 30), USER) == (0.0, "no heart rate")


def test_rescore_keeps_intervals_load_for_rides_only():
    ride = _a("Ride", 60, np=170, method="intervals_icu")
    ride.tss = 77.0
    rescore(ride, USER)
    assert (ride.tss, ride.tss_method) == (77.0, "intervals_icu")
    walk = _a("Walk", 60, hr=110, method="intervals_icu")
    walk.tss = 48.0
    rescore(walk, USER)
    assert walk.tss_method == "walk hr"  # walks are CoachQuest's own scoring


def test_existing_activities_scored_again_once(make_user):
    from datetime import datetime

    from app import profile_sync
    from app.db import Activity, AppSetting, SessionLocal, User

    p = make_user("a@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    with SessionLocal() as db:
        u = db.get(User, uid)
        u.ftp_watts, u.lthr_bpm = 212, 160
        db.add(
            Activity(
                user_id=uid,
                source="strava",
                external_id="1",
                sport="WeightTraining",
                start_time=datetime(2026, 10, 1),
                duration_s=2400,
                avg_hr=120,
                tss=40,
                tss_method="hr",
            )
        )
        db.query(AppSetting).filter_by(key="tss_version").delete()
        db.commit()
        assert profile_sync.rescore_all_once(db) >= 1
        a = db.query(Activity).filter_by(user_id=uid).one()
        assert a.tss_method == "hr" and a.tss == round((120 / 160) ** 2 * 100 * 40 / 60, 1)
        assert profile_sync.rescore_all_once(db) == 0  # once
