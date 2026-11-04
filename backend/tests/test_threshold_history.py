"""Each workout is scored with the FTP / LTHR of its own date, as TrainingPeaks does."""

from datetime import date, datetime
from types import SimpleNamespace

from app import profile_sync
from app.fitness import score, threshold_at


def ride(day, np=200, minutes=60):
    return SimpleNamespace(
        sport="Ride",
        start_time=datetime.combine(day, datetime.min.time()).replace(hour=8),
        duration_s=minutes * 60,
        norm_power=np,
        avg_power=np,
        avg_hr=None,
        relative_effort=None,
        trainer=False,
        type_override=None,
        indoor=False,
        name="",
        tss=None,
        tss_method=None,
    )


def user(**kw):
    base = dict(ftp_watts=250, run_ftp_watts=None, lthr_bpm=None, threshold_history=None, timezone=None)
    return SimpleNamespace(**{**base, **kw})


def test_no_history_uses_today():
    u = user()
    assert threshold_at(u, "ftp_watts", date(2026, 1, 1)) == 250


def test_value_of_the_date():
    u = user(
        threshold_history=[
            {"field": "ftp_watts", "from": None, "value": 200},
            {"field": "ftp_watts", "from": "2026-06-01", "value": 220},
            {"field": "ftp_watts", "from": "2026-11-04", "value": 250},
        ]
    )
    assert threshold_at(u, "ftp_watts", date(2026, 3, 1)) == 200
    assert threshold_at(u, "ftp_watts", date(2026, 6, 1)) == 220
    assert threshold_at(u, "ftp_watts", date(2026, 11, 5)) == 250
    assert score(ride(date(2026, 3, 1)), u) == (100.0, "power")  # 200 W at FTP 200
    assert score(ride(date(2026, 11, 5), np=250), u) == (100.0, "power")


def test_first_entry_counts_before_it():
    u = user(threshold_history=[{"field": "ftp_watts", "from": "2026-06-01", "value": 200}])
    assert threshold_at(u, "ftp_watts", date(2026, 1, 1)) == 200


def test_change_keeps_earlier_rides():
    u = user()
    profile_sync.record_change(u, "ftp_watts", 200, 250, date(2026, 11, 4))
    assert u.threshold_history == [
        {"field": "ftp_watts", "from": None, "value": 200},
        {"field": "ftp_watts", "from": "2026-11-04", "value": 250},
    ]
    assert score(ride(date(2026, 10, 1)), u)[0] == 100.0  # still FTP 200 then
    profile_sync.record_change(u, "ftp_watts", 250, 250, date(2026, 11, 5))  # unchanged: nothing
    profile_sync.record_change(u, "ftp_watts", 250, 260, date(2026, 11, 4))  # same day: replaced
    assert [h["value"] for h in u.threshold_history] == [200, 260]
    profile_sync.record_change(u, "max_hr_bpm", 180, 190)  # not a threshold for TSS
    assert len(u.threshold_history) == 2


def test_api_history_and_profile_change(make_user):
    from app.db import Activity, SessionLocal, User

    me = make_user("t@example.com")
    assert me.patch("/api/me", json={"ftp_watts": 200}).status_code == 200
    with SessionLocal() as db:
        u = db.query(User).filter_by(email="t@example.com").one()
        u.threshold_history = None  # set before any history existed
        db.add(
            Activity(
                user_id=u.id,
                source="manual",
                external_id="1",
                sport="Ride",
                name="r",
                start_time=datetime(2026, 1, 10, 8),
                duration_s=3600,
                norm_power=200,
            )
        )
        db.commit()
    out = me.patch("/api/me", json={"ftp_watts": 250}).json()
    assert [h["value"] for h in out["threshold_history"]] == [200, 250]
    with SessionLocal() as db:
        assert db.query(Activity).one().tss == 100.0  # the January ride keeps FTP 200

    r = me.request(
        "PUT",
        "/api/me/threshold-history",
        json={
            "entries": [
                {"field": "ftp_watts", "from": None, "value": 160},
                {"field": "ftp_watts", "from": "2026-03-01", "value": 240},
            ]
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["ftp_watts"] == 240  # today's value
    with SessionLocal() as db:
        assert db.query(Activity).one().tss == 156.2  # (200/160)^2 * 100

    bad = me.request(
        "PUT",
        "/api/me/threshold-history",
        json={"entries": [{"field": "ftp_watts", "from": "2099-01-01", "value": 200}]},
    )
    assert bad.status_code == 422


def _coach_and_athlete(make_user, scopes, role=None):
    athlete = make_user("ath@example.com", "Natalie")
    coach = make_user("c@example.com", "Coach Mike")
    aid = athlete.get("/api/auth/me").json()["id"]
    body = {"coach_email": "c@example.com", "scopes": scopes}
    if role:
        body["role"] = role
    g = athlete.post("/api/grants", json=body).json()
    coach.post(f"/api/grants/{g['id']}/accept")
    return athlete, coach, aid


def test_coach_sets_thresholds(make_user):
    from app.db import Activity, SessionLocal

    athlete, coach, aid = _coach_and_athlete(make_user, ["profile", "activities"])
    athlete.patch("/api/me", json={"ftp_watts": 200, "lthr_bpm": 170})
    with SessionLocal() as db:
        db.add(
            Activity(
                user_id=aid,
                source="manual",
                external_id="1",
                sport="Ride",
                name="r",
                start_time=datetime(2026, 1, 10, 8),
                duration_s=3600,
                norm_power=200,
            )
        )
        db.commit()
    r = coach.patch(f"/api/athletes/{aid}/thresholds", json={"run_ftp_watts": 190, "lthr_bpm": 181})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["run_ftp_watts"] == 190 and out["lthr_bpm"] == 181
    assert out["profile_sources"]["lthr_bpm"]["source"] == "coach"
    assert out["profile_sources"]["lthr_bpm"]["by"] == "Coach Mike"
    me = athlete.get("/api/auth/me").json()
    assert me["run_ftp_watts"] == 190 and me["profile_sources"]["run_ftp_watts"]["by"] == "Coach Mike"
    # The athlete saving the whole Profile form unchanged doesn't take the values over.
    athlete.patch("/api/me", json={"ftp_watts": 200, "lthr_bpm": 181, "run_ftp_watts": 190})
    assert athlete.get("/api/auth/me").json()["profile_sources"]["lthr_bpm"]["source"] == "coach"
    # History, by the coach: the January ride scored with the FTP of its date.
    h = coach.request(
        "PUT",
        f"/api/athletes/{aid}/threshold-history",
        json={
            "entries": [
                {"field": "ftp_watts", "from": None, "value": 160},
                {"field": "ftp_watts", "from": "2026-03-01", "value": 200},
            ]
        },
    )
    assert h.status_code == 200, h.text
    with SessionLocal() as db:
        assert db.query(Activity).filter_by(user_id=aid).one().tss == 156.2
    assert coach.get(f"/api/athletes/{aid}").json()["threshold_history"][0]["value"] == 160


def test_only_with_the_profile_share(make_user):
    _, coach, aid = _coach_and_athlete(make_user, ["activities"])
    assert coach.patch(f"/api/athletes/{aid}/thresholds", json={"ftp_watts": 250}).status_code == 404
    url = f"/api/athletes/{aid}/threshold-history"
    assert coach.request("PUT", url, json={"entries": []}).status_code == 404
    assert "ftp_watts" not in coach.get(f"/api/athletes/{aid}").json()


def test_a_correction_counts_for_earlier_workouts(make_user):
    from app.db import Activity, SessionLocal, User

    me = make_user("t@example.com")
    me.patch("/api/me", json={"ftp_watts": 160})
    me.patch("/api/me", json={"ftp_watts": 180})  # from today: history 160 before, 180 now
    with SessionLocal() as db:
        uid = db.query(User).filter_by(email="t@example.com").one().id
        db.add(
            Activity(
                user_id=uid,
                source="manual",
                external_id="1",
                sport="Ride",
                name="r",
                start_time=datetime(2026, 1, 10, 8),
                duration_s=3600,
                norm_power=200,
            )
        )
        db.commit()
    out = me.patch("/api/me", json={"ftp_watts": 200, "correct_history": True}).json()
    assert out["threshold_history"] == [] and out["ftp_watts"] == 200
    with SessionLocal() as db:
        assert db.query(Activity).one().tss == 100.0  # scored with 200, the corrected value

    athlete, coach, aid = _coach_and_athlete_2(make_user)
    athlete.patch("/api/me", json={"lthr_bpm": 170})
    athlete.patch("/api/me", json={"lthr_bpm": 175})
    r = coach.patch(f"/api/athletes/{aid}/thresholds", json={"lthr_bpm": 181, "correct_history": True})
    assert r.status_code == 200 and r.json()["threshold_history"] == []


def _coach_and_athlete_2(make_user):
    athlete = make_user("ath2@example.com", "A")
    coach = make_user("c2@example.com", "C")
    aid = athlete.get("/api/auth/me").json()["id"]
    g = athlete.post("/api/grants", json={"coach_email": "c2@example.com", "scopes": ["profile"]}).json()
    coach.post(f"/api/grants/{g['id']}/accept")
    return athlete, coach, aid
