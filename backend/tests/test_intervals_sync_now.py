"""Intervals.icu "Sync now": send every workout from today on again, then import."""

from test_sync import _athlete, _run, _schedule, fake  # noqa: F401  (fixture)

from app.db import Connection, SessionLocal


def test_sync_now_resends_unchanged_workouts(make_user, fake):  # noqa: F811
    a, uid = _athlete(make_user, fake)
    _schedule(a, 1, "Tempo")
    _schedule(a, 3, "Threshold")
    _run()
    assert len(fake.upserts()) == 2
    _run()  # nothing changed: nothing goes again by itself
    assert len(fake.upserts()) == 2
    r = a.post("/api/connections/intervals_icu/sync")
    assert r.status_code == 200, r.text
    assert r.json()["workouts"] == {"sent": 2, "deleted": 0, "failed": 0, "errors": []}
    assert len(fake.upserts()) == 4  # both sent again, unchanged
    # Once per 5 minutes.
    again = a.post("/api/connections/intervals_icu/sync")
    assert again.status_code == 429 and "5 minutes" in again.json()["detail"]


def test_sync_now_reports_failures_and_auto_off(make_user, fake):  # noqa: F811
    a, uid = _athlete(make_user, fake)
    _schedule(a, 1)
    _run()
    fake.fail_next(400, body="Bad workout")
    r = a.post("/api/connections/intervals_icu/sync").json()
    assert r["workouts"]["failed"] == 1 and r["workouts"]["errors"]
    # With sending switched off, only the import part runs.
    with SessionLocal() as db:
        db.query(Connection).filter_by(user_id=uid).one().options = {}
        db.commit()
    a.request("PUT", "/api/me/platforms", json={"preferred": ["zwift"], "auto": {"intervals_icu": False}})
    r = a.post("/api/connections/intervals_icu/sync").json()
    assert r["workouts"] is None and r["fetched"] == 0
