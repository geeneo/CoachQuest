"""Deleting a user deletes every row that belongs to them, unsigns what they wrote for others,
revokes CoachQuest's access at Strava and Intervals.icu, and emails them."""

from datetime import date, timedelta

from sqlalchemy import select
from test_phase3 import _create, planner  # noqa: F401  (fixture)

from app import accounts
from app.db import (
    Activity,
    Base,
    Connection,
    ExternalWorkout,
    ScheduledWorkout,
    SessionLocal,
    WellnessDay,
    utcnow,
)
from app.security import encrypt_json


def _everything(make_user):
    """An athlete with data in many tables, and a coach who wrote things for them."""
    admin = make_user("admin@example.com")
    a = make_user("a@example.com", "Ann")
    coach = make_user("c@example.com", "Coach")
    aid = a.get("/api/auth/me").json()["id"]
    cid = coach.get("/api/auth/me").json()["id"]
    g = a.post("/api/grants", json={"coach_email": "c@example.com", "scopes": ["activities", "plans"]}).json()
    coach.post(f"/api/grants/{g['id']}/accept")
    seg = a.post("/api/athletes/me/segments", json={"link": "https://www.strava.com/segments/1234567"}).json()
    a.patch(f"/api/athletes/me/segments/{seg['id']}", json={"shared": True})
    a.post("/api/races", json={"name": "DC", "target_date": (date.today() + timedelta(days=30)).isoformat()})
    a.request("PUT", "/api/me/health", json={"conditions": [{"id": "knee"}], "accept_disclaimer": True})
    with SessionLocal() as db:
        db.add(Activity(user_id=aid, source="strava", external_id="1", sport="Ride", start_time=utcnow()))
        db.add(WellnessDay(user_id=aid, day=date.today(), source="garmin", resting_hr=44))
        db.add(Connection(user_id=aid, provider="strava", token_enc=encrypt_json({"access_token": "s"})))
        db.add(Connection(user_id=aid, provider="intervals_icu", token_enc=encrypt_json({"access_token": "i"})))
        db.commit()
    return admin, a, coach, aid, cid


def _pointing_at(uid: int) -> dict[str, int]:
    """Rows in any table whose link to users is this user."""
    found = {}
    with SessionLocal() as db:
        for table in Base.metadata.sorted_tables:
            for fk in table.foreign_keys:
                if fk.column.table.name == "users":
                    n = len(db.execute(select(table).where(fk.parent == uid)).all())
                    if n:
                        found[f"{table.name}.{fk.parent.name}"] = n
    return found


def test_delete_removes_every_row_and_tells_the_apps(make_user, planner, monkeypatch):  # noqa: F811
    admin, a, coach, aid, cid = _everything(make_user)
    plan = _create(a)  # the athlete's own plan
    coach_plan = coach.post(
        f"/api/athletes/{aid}/plans",
        json={"title": "From coach", "goal": "x", "weeks": 2, "without_data": True},
    ).json()
    coach.post(f"/api/athletes/{aid}/plans/{coach_plan['id']}/comments", json={"body": "Easy now"})
    a.post(f"/api/athletes/me/plans/{plan['id']}/comments", json={"body": "Mine"})
    # A workout CoachQuest sent to Intervals.icu for next week, and one in the past.
    with SessionLocal() as db:
        future = db.scalars(select(ScheduledWorkout).where(ScheduledWorkout.athlete_id == aid)).first()
        db.add(
            ExternalWorkout(
                scheduled_workout_id=future.id,
                athlete_id=aid,
                provider="intervals_icu",
                external_id="cq-1",
                content_hash="h",
            )
        )
        db.commit()
        fid = future.id
        assert future.day >= date.today()
    assert _pointing_at(aid)

    calls = []

    async def fake_deauthorize(conn):
        calls.append(("strava", conn.provider))

    async def fake_delete(self, token, external_id):
        calls.append(("intervals-delete", external_id))

    async def fake_revoke(self, token):
        calls.append(("intervals-revoke", token["access_token"]))

    monkeypatch.setattr("app.providers.strava.deauthorize", fake_deauthorize)
    monkeypatch.setattr("app.delivery.intervals_icu.IntervalsIcu.delete", fake_delete)
    monkeypatch.setattr("app.delivery.intervals_icu.IntervalsIcu.revoke", fake_revoke)

    preview = admin.get(f"/api/admin/users/{aid}/delete-preview").json()
    assert preview["deleted"]["Activities"] == 1 and preview["deleted"]["Favourite routes and segments"] == 1
    assert preview["deleted"]["Training plans"] == 2 and set(preview["linked_apps"]) == {"strava", "intervals_icu"}

    r = admin.request("DELETE", f"/api/admin/users/{aid}", json={"confirm_email": "a@example.com"}).json()
    assert r["ok"] and r["deleted"]["Activities"] == 1
    assert ("strava", "strava") in calls and ("intervals-delete", "cq-1") in calls
    assert ("intervals-revoke", "i") in calls and r["revoked"]

    # Nothing anywhere still points at them, except the sign-in log's email kept for the audit
    # (its user_id is emptied), and nothing of theirs is left in tables without a link.
    assert _pointing_at(aid) == {}
    with SessionLocal() as db:
        assert db.get(ScheduledWorkout, fid) is None
        assert not db.scalars(select(ExternalWorkout).where(ExternalWorkout.athlete_id == aid)).all()
    assert a.get("/api/auth/me").status_code == 401
    assert admin.get("/api/shared-routes").json() == []
    # The coach and their account are untouched.
    assert coach.get("/api/auth/me").json()["id"] == cid


def test_what_they_wrote_for_others_stays_unsigned(make_user, planner):  # noqa: F811
    admin, a, coach, aid, cid = _everything(make_user)
    plan = _create(a)
    coach.post(f"/api/athletes/{aid}/plans/{plan['id']}/comments", json={"body": "Coach note"})
    # Delete the coach: the athlete's plan comment from them stays, without an author.
    preview = admin.get(f"/api/admin/users/{cid}/delete-preview").json()
    assert preview["kept_unsigned"]["Comments"] == 1
    admin.request("DELETE", f"/api/admin/users/{cid}", json={"confirm_email": "c@example.com"})
    comments = a.get(f"/api/athletes/me/plans/{plan['id']}/comments").json()
    assert [c["body"] for c in comments] == ["Coach note"]
    assert _pointing_at(cid) == {}
    # The athlete keeps everything of theirs; only the sharing with the coach is gone.
    assert a.get("/api/athletes/me/segments").json()["favourites"]


def test_plan_covers_every_link_to_users():
    """Every foreign key to users is either followed (delete) or emptied (unsign) by delete_account."""
    steps = accounts._steps(1)
    covered = {(t.name, c.name) for action, t, c, _ in steps if action == "unsign"}
    deleted = {t.name for action, t, _, _ in steps if action == "delete"}
    for table in Base.metadata.sorted_tables:
        for fk in table.foreign_keys:
            if fk.column.table.name == "users":
                assert table.name in deleted or (table.name, fk.parent.name) in covered, (table.name, fk.parent.name)
