"""Daily TSS is worked out once and kept until the athlete's data changes (queries.daily_load)."""

from datetime import date, datetime, timedelta

from app import queries
from app.db import Activity, Connection, SessionLocal, User


def _ride(db, uid, n, days_ago, tss, source="strava"):
    db.add(
        Activity(
            user_id=uid,
            source=source,
            external_id=f"{source}{n}",
            name="Ride",
            sport="Ride",
            start_time=datetime.combine(date.today() - timedelta(days=days_ago), datetime.min.time())
            + timedelta(hours=8),
            duration_s=3600,
            distance_m=30000,
            elevation_m=100,
            tss=tss,
        )
    )


def test_cache_follows_every_change(make_user, monkeypatch):
    p = make_user("a@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    calls = []
    real = queries.activities_since
    monkeypatch.setattr(queries, "activities_since", lambda *a, **k: calls.append(1) or real(*a, **k))
    with SessionLocal() as db:
        for i in range(30):
            _ride(db, uid, i, i + 1, 50)
        db.commit()
        first = queries.load_curve(db, uid, 30)[0][-1].ctl
        assert queries.load_curve(db, uid, 365)[0][-1].ctl == first and len(calls) == 1  # second time: cached

        _ride(db, uid, 99, 0, 200)  # a new ride
        db.commit()
        more = queries.load_curve(db, uid, 30)[0][-1].ctl
        assert more > first and len(calls) == 2

        a = db.query(Activity).filter_by(external_id="strava99").one()
        a.tss = 20  # rescored (a threshold changed)
        db.commit()
        rescored = queries.load_curve(db, uid, 30)[0][-1].ctl
        assert rescored < more and len(calls) == 3

        _ride(db, uid, 1, 1, 500, source="garmin")  # a copy from Garmin of yesterday's ride: counted once
        db.commit()
        assert queries.load_curve(db, uid, 30)[0][-1].ctl == rescored and len(calls) == 4

        db.add(Connection(user_id=uid, provider="strava", token_enc="", options={"activities": False}))
        db.commit()  # Strava's activities hidden: only the Garmin copy is left
        assert queries.load_curve(db, uid, 30)[0][-1].ctl < rescored and len(calls) == 5

        db.get(User, uid).timezone = "Pacific/Auckland"
        db.commit()
        queries.load_curve(db, uid, 30)
        assert len(calls) == 6

        # The same numbers as working it out from the period's activities, the way it used to be.
        curve = queries.load_curve(db, uid, 60)[0]
        warm = date.today() - timedelta(days=60 + queries.WARMUP_DAYS)
        acts = real(db, uid, datetime.combine(warm - timedelta(days=1), datetime.min.time()))
        tz = queries.localtime.zone("Pacific/Auckland")
        direct = queries.pmc(queries.daily_tss([(x.start_time, x.tss) for x in acts], tz), warm, date.today())
        assert [d.ctl for d in curve] == [d.ctl for d in direct[-60:]]


def test_whole_history_same_in_every_view(make_user):
    """The PMC starts at the first training day (as TrainingPeaks does), not 120 days before the period:
    every period shows the same values, and long-ago training still counts a little."""
    p = make_user("b@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    with SessionLocal() as db:
        for i in range(400):  # steady riding for 400 days
            _ride(db, uid, i, i + 1, 60)
        db.commit()
        week = queries.load_curve(db, uid, 7)[0]
        years = queries.load_curve(db, uid, 1825)[0]
        assert [d.ctl for d in week] == [d.ctl for d in years[-7:]]
        assert years[0].day == date.today() - timedelta(days=1824)  # the period as asked, zeros before
        # Starting from 0 only 120 days back would leave fitness about 5% short of the full history.
        warm = date.today() - timedelta(days=7 + queries.WARMUP_DAYS)
        short = queries.pmc(queries.daily_load(db, uid), warm, date.today())
        assert week[-1].ctl > short[-1].ctl * 1.04
    audit = p.get("/api/athletes/me/load-audit?days=30")
    assert audit.status_code == 200, audit.text
    days = {d["date"]: d["ctl"] for d in audit.json()["days"]}  # the audit's day table is the chart's
    assert days[date.today().isoformat()] == week[-1].ctl
