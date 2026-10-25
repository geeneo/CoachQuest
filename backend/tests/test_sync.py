"""Workout delivery and the sync queue, against a fake Intervals.icu. Nothing real is called."""

import asyncio
import json
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app import runtime, sync_engine
from app.db import Connection, ExternalWorkout, ScheduledWorkout, SessionLocal, SyncJob, SyncLog, User, utcnow
from app.delivery import ADAPTERS
from app.delivery import intervals_icu as icu
from app.delivery.base import NotSupported
from app.security import encrypt_json

STEPS = [{"kind": "steady", "duration_s": 1800, "power": 0.75}]


class FakeIntervals:
    """Records requests; answers 200 unless a status is queued with `fail_next`."""

    def __init__(self):
        self.calls: list[tuple[str, str, object]] = []
        self.fail: list[httpx.Response] = []
        self.token_response = {
            "access_token": "tok-123",
            "token_type": "Bearer",
            "scope": "CALENDAR:WRITE",
            "athlete": {"id": "i4242", "name": "Test Rider"},
        }
        self.activities: list[dict] = []
        self.wellness: list[dict] = []

    def fail_next(self, status: int, headers: dict | None = None, body: str = "nope"):
        self.fail.append(httpx.Response(status, headers=headers or {}, text=body))

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = request.content.decode() if request.content else ""
        if request.url.path == "/api/oauth/token":
            self.calls.append(("TOKEN", request.url.path, parse_qs(body)))
            return httpx.Response(200, json=self.token_response)
        parsed = json.loads(body) if body.startswith(("[", "{")) else body
        self.calls.append((request.method, f"{request.url.path}?{request.url.query.decode()}", parsed))
        assert request.headers["Authorization"].startswith("Bearer ")
        if self.fail:
            return self.fail.pop(0)
        if request.method == "GET" and request.url.path.endswith("/activities"):
            return httpx.Response(200, json=self.activities)
        if request.method == "GET" and request.url.path.endswith("/wellness"):
            return httpx.Response(200, json=self.wellness)
        if request.url.path.endswith("/events/bulk"):
            return httpx.Response(200, json=[{"id": 9000 + i, **e} for i, e in enumerate(parsed)])
        return httpx.Response(200, json={})

    def upserts(self):
        return [c for c in self.calls if c[0] == "POST" and "/events/bulk" in c[1]]

    def deletes(self):
        return [c for c in self.calls if c[0] == "PUT" and c[1].startswith("/api/v1/athlete/0/events/bulk-delete")]


@pytest.fixture()
def fake(monkeypatch):
    f = FakeIntervals()
    monkeypatch.setattr(icu, "transport", httpx.MockTransport(f.handler))
    monkeypatch.setitem(runtime._overrides, "intervals_client_id", "cq-test-app")
    monkeypatch.setitem(runtime._overrides, "intervals_client_secret", "secret-secret")
    return f


def _connect(user_id: int, status: str = "active"):
    with SessionLocal() as db:
        db.add(
            Connection(
                user_id=user_id,
                provider="intervals_icu",
                external_id="i4242",
                token_enc=encrypt_json({"access_token": "tok-123", "scope": "CALENDAR:WRITE"}),
                status=status,
            )
        )
        db.commit()


def _athlete(make_user, fake, auto=True):
    a = make_user("rider@example.com", "Rider")
    uid = a.get("/api/auth/me").json()["id"]
    _connect(uid)
    if auto:
        r = a.request("PUT", "/api/me/platforms", json={"preferred": ["zwift"], "auto": {"intervals_icu": True}})
        assert r.status_code == 200, r.text
    return a, uid


def _schedule(a, days_ahead=2, name="Tempo"):
    day = (date.today() + timedelta(days=days_ahead)).isoformat()
    r = a.post("/api/athletes/me/workouts", json={"day": day, "name": name, "steps": STEPS})
    assert r.status_code == 200, r.text
    return r.json()


def _jobs(uid):
    with SessionLocal() as db:
        return db.query(SyncJob).filter(SyncJob.athlete_id == uid).order_by(SyncJob.id).all()


def _run():
    return asyncio.run(sync_engine.run_due())


# ---- OAuth ----


def test_connect_flow(make_user, fake):
    a = make_user("rider@example.com")
    url = a.post("/api/connections/intervals/authorize").json()["url"]
    q = parse_qs(urlparse(url).query)
    assert url.startswith("https://intervals.icu/oauth/authorize")
    assert q["scope"] == ["CALENDAR:WRITE,ACTIVITY:READ,WELLNESS:READ"]
    assert q["redirect_uri"][0].endswith("/api/connections/intervals/callback")
    r = a.get(f"/api/connections/intervals/callback?state={q['state'][0]}&code=abc", follow_redirects=False)
    assert r.headers["location"] == "/connections?connected=intervals#platforms"
    token_call = fake.calls[0]
    assert token_call[2]["code"] == ["abc"] and token_call[2]["client_secret"] == ["secret-secret"]
    p = {x["id"]: x for x in a.get("/api/athletes/me/platforms").json()}["intervals_icu"]
    assert p["status"] == "connected" and p["account"] == "i4242" and p["auto_sync_available"]
    # The token never reaches the browser.
    assert "tok-123" not in json.dumps(a.get("/api/athletes/me/platforms").json())
    assert "tok-123" not in a.get("/api/connections").text
    # A state from another flow, or a reused one, is refused.
    r = a.get(f"/api/connections/intervals/callback?state={q['state'][0]}&code=abc", follow_redirects=False)
    assert "error=state" in r.headers["location"]


def _link(a):
    state = parse_qs(urlparse(a.post("/api/connections/intervals/authorize").json()["url"]).query)["state"][0]
    return a.get(f"/api/connections/intervals/callback?state={state}&code=abc", follow_redirects=False)


def test_connect_with_no_access_fails(make_user, fake):
    fake.token_response["scope"] = ""
    a = make_user("rider@example.com")
    assert "error=intervals" in _link(a).headers["location"]
    p = {x["id"]: x for x in a.get("/api/athletes/me/platforms").json()}["intervals_icu"]
    assert p["status"] == "not_connected"


def test_connect_without_calendar_access_cannot_send(make_user, fake):
    fake.token_response["scope"] = "ACTIVITY:READ"
    a = make_user("rider@example.com")
    assert "connected=intervals" in _link(a).headers["location"]
    p = {x["id"]: x for x in a.get("/api/athletes/me/platforms").json()}["intervals_icu"]
    assert p["status"] == "connected" and not p["auto_sync_available"]
    assert a.request("PUT", "/api/me/platforms", json={"auto": {"intervals_icu": True}}).status_code == 409
    conn = next(c for c in a.get("/api/connections").json()["connections"] if c["provider"] == "intervals_icu")
    assert conn["scopes"] == ["ACTIVITY:READ"] and conn["options"] == {"activities": False, "wellness": False}


def test_not_configured_on_server(make_user):
    a = make_user("rider@example.com")
    assert a.post("/api/connections/intervals/authorize").status_code == 503
    p = {x["id"]: x for x in a.get("/api/athletes/me/platforms").json()}
    assert p["intervals_icu"]["status"] == "not_configured" and not p["intervals_icu"]["auto_sync_available"]


# ---- Delivery ----


def test_auto_send_needs_connection(make_user, fake):
    a = make_user("rider@example.com")
    r = a.request("PUT", "/api/me/platforms", json={"auto": {"intervals_icu": True}})
    assert r.status_code == 409
    r = a.request("PUT", "/api/me/platforms", json={"auto": {"zwift": True}})
    assert r.status_code == 409  # no direct Zwift delivery without partner approval


def test_assign_sends_once_and_updates_in_place(make_user, fake):
    a, uid = _athlete(make_user, fake)
    sw = _schedule(a)
    ups = fake.upserts()
    assert len(ups) == 1
    method, path, events = ups[0]
    assert path == "/api/v1/athlete/0/events/bulk?upsert=true"
    e = events[0]
    assert e["external_id"] == f"cq-{sw['id']}" and e["category"] == "WORKOUT" and e["type"] == "Ride"
    assert e["start_date_local"] == f"{sw['date']}T00:00:00" and e["filename"].endswith(".zwo")
    assert "<workout_file>" in e["file_contents"] and 'Power="0.75"' in e["file_contents"]
    cal = a.get(f"/api/athletes/me/calendar?start={sw['date']}&end={sw['date']}").json()
    delivery = cal["days"][0]["workouts"][0]["delivery"]
    assert delivery[0]["provider"] == "intervals_icu" and delivery[0]["state"] == "sent"

    # A real change goes out again under the same external id: an update, not a duplicate.
    a.patch(f"/api/athletes/me/workouts/{sw['id']}", json={"name": "Tempo 2"})
    assert len(fake.upserts()) == 2 and fake.upserts()[1][2][0]["external_id"] == f"cq-{sw['id']}"
    # Saving without a change sends nothing.
    a.patch(f"/api/athletes/me/workouts/{sw['id']}", json={"name": "Tempo 2"})
    assert len(fake.upserts()) == 2
    with SessionLocal() as db:
        assert db.query(ExternalWorkout).count() == 1
        outcomes = [x.outcome for x in db.query(SyncLog).order_by(SyncLog.id)]
    assert outcomes == ["sent", "sent", "unchanged"]


def test_cancel_and_delete_remove_from_platform(make_user, fake):
    a, uid = _athlete(make_user, fake)
    sw = _schedule(a)
    a.patch(f"/api/athletes/me/workouts/{sw['id']}", json={"status": "cancelled"})
    assert fake.deletes()[-1][2] == [{"external_id": f"cq-{sw['id']}"}]
    a.patch(f"/api/athletes/me/workouts/{sw['id']}", json={"status": "planned"})
    assert len(fake.upserts()) == 2
    a.delete(f"/api/athletes/me/workouts/{sw['id']}")
    assert len(fake.deletes()) == 2
    with SessionLocal() as db:
        assert db.query(ExternalWorkout).count() == 0


def test_unsent_and_past_workouts_make_no_calls(make_user, fake):
    a, uid = _athlete(make_user, fake)
    past = _schedule(a, days_ahead=-3, name="Old")
    assert fake.upserts() == []
    a.delete(f"/api/athletes/me/workouts/{past['id']}")
    assert fake.deletes() == [] and _jobs(uid) == []


def test_turning_auto_on_sends_upcoming(make_user, fake):
    a, uid = _athlete(make_user, fake, auto=False)
    _schedule(a, 1, "One")
    _schedule(a, 3, "Two")
    _schedule(a, -2, "Past")
    assert fake.upserts() == []
    a.request("PUT", "/api/me/platforms", json={"auto": {"intervals_icu": True}})
    assert sorted(c[2][0]["name"] for c in fake.upserts()) == ["One", "Two"]


def test_changes_coalesce_into_one_job(make_user, fake):
    a, uid = _athlete(make_user, fake, auto=False)
    sw = _schedule(a)
    with SessionLocal() as db:
        user = db.get(User, uid)
        user.platform_prefs = {"auto": {"intervals_icu": True}}
        db.commit()
        row = db.get(ScheduledWorkout, sw["id"])
        for reason in ("assigned", "changed", "changed"):
            sync_engine.workout_changed(db, row, reason)
    jobs = _jobs(uid)
    assert len(jobs) == 1 and jobs[0].status == "queued" and jobs[0].reason == "changed"
    assert _run() == 1 and len(fake.upserts()) == 1


# ---- Errors, backoff and retries ----


def _queued_job(make_user, fake):
    a, uid = _athlete(make_user, fake, auto=False)
    sw = _schedule(a)
    with SessionLocal() as db:
        db.get(User, uid).platform_prefs = {"auto": {"intervals_icu": True}}
        db.commit()
        sync_engine.workout_changed(db, db.get(ScheduledWorkout, sw["id"]), "assigned")
    return a, uid, sw


def test_backoff_schedule():
    assert [int(sync_engine.backoff(n).total_seconds() // 60) for n in range(1, 9)] == [1, 2, 4, 8, 16, 32, 60, 60]


def test_transient_errors_back_off_then_give_up(make_user, fake):
    a, uid, sw = _queued_job(make_user, fake)
    for _ in range(sync_engine.MAX_ATTEMPTS):
        fake.fail_next(503)
    with SessionLocal() as db:
        job = db.query(SyncJob).one()
        start = utcnow()
        assert asyncio.run(sync_engine.process(db, job, now=start)) == "retrying"
        assert job.status == "queued" and job.attempts == 1
        assert job.next_attempt_at == start + timedelta(minutes=1)
        # Not due yet: the queue leaves it alone.
        assert asyncio.run(sync_engine.run_due()) == 0
        for _ in range(sync_engine.MAX_ATTEMPTS - 1):
            outcome = asyncio.run(sync_engine.process(db, job, now=start))
        assert outcome == "failed" and job.status == "failed" and "Gave up after 6 tries" in job.last_error
    hist = a.get("/api/athletes/me/sync").json()
    assert hist["open"][0]["status"] == "failed" and hist["log"][0]["outcome"] == "failed"
    # Retry starts over and succeeds.
    r = a.post(f"/api/athletes/me/sync/{hist['open'][0]['id']}/retry")
    assert r.status_code == 200 and len([c for c in fake.upserts()]) == sync_engine.MAX_ATTEMPTS + 1
    assert a.get("/api/athletes/me/sync").json()["open"] == []


def test_network_error_is_transient(make_user, fake, monkeypatch):
    a, uid, sw = _queued_job(make_user, fake)

    def boom(request):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(icu, "transport", httpx.MockTransport(boom))
    assert _run() == 1
    job = _jobs(uid)[0]
    assert job.status == "queued" and job.attempts == 1 and "Could not reach" in job.last_error


def test_rate_limit_waits_without_using_attempts(make_user, fake):
    a, uid, sw = _queued_job(make_user, fake)
    fake.fail_next(429, {"Retry-After": "120"})
    with SessionLocal() as db:
        job = db.query(SyncJob).one()
        now = utcnow()
        assert asyncio.run(sync_engine.process(db, job, now=now)) == "rate_limited"
        assert job.status == "queued" and job.attempts == 0
        assert job.next_attempt_at == now + timedelta(seconds=120)


def test_lost_authorisation_blocks_until_reconnect(make_user, fake):
    a, uid, sw = _queued_job(make_user, fake)
    fake.fail_next(401)
    _run()
    job = _jobs(uid)[0]
    assert job.status == "blocked" and "Reconnect" in job.last_error
    p = {x["id"]: x for x in a.get("/api/athletes/me/platforms").json()}["intervals_icu"]
    assert p["status"] == "error"
    # Not retried automatically, and Retry is refused until reconnecting.
    calls = len(fake.calls)
    _run()
    assert len(fake.calls) == calls
    assert a.post(f"/api/athletes/me/sync/{job.id}/retry").status_code == 409
    # Another workout doesn't hit the platform either: blocked straight away.
    _schedule(a, 4, "Second")
    assert len(fake.calls) == calls
    # Reconnecting re-queues blocked work and sends it.
    state = parse_qs(urlparse(a.post("/api/connections/intervals/authorize").json()["url"]).query)["state"][0]
    a.get(f"/api/connections/intervals/callback?state={state}&code=new", follow_redirects=False)
    assert sorted(c[2][0]["name"] for c in fake.upserts()[1:]) == ["Second", "Tempo"]  # [0] was the 401
    assert all(j.status == "done" for j in _jobs(uid))


def test_rejected_workout_is_not_retried(make_user, fake):
    a, uid, sw = _queued_job(make_user, fake)
    fake.fail_next(422, body="bad workout")
    _run()
    job = _jobs(uid)[0]
    assert job.status == "failed" and "bad workout" in job.last_error
    _run()
    assert len(fake.upserts()) == 1
    # Changing the workout queues it again.
    a.patch(f"/api/athletes/me/workouts/{sw['id']}", json={"name": "Fixed"})
    assert fake.upserts()[-1][2][0]["name"] == "Fixed" and _jobs(uid)[0].status == "done"


def test_disconnect_revokes_and_forgets(make_user, fake):
    a, uid = _athlete(make_user, fake)
    _schedule(a)
    assert a.delete("/api/connections/intervals").status_code == 200
    assert ("DELETE", "/api/v1/disconnect-app?", "") in fake.calls
    p = {x["id"]: x for x in a.get("/api/athletes/me/platforms").json()}["intervals_icu"]
    assert p["status"] == "not_connected" and not p["auto_sync"]
    with SessionLocal() as db:
        assert db.query(ExternalWorkout).count() == 0
    assert a.get("/api/athletes/me/sync").json()["log"][0]["outcome"] == "disconnected"


def test_coach_sees_sync_history_only_with_plans(make_user, fake):
    a, uid = _athlete(make_user, fake)
    _schedule(a)
    coach = make_user("coach@example.com", "Coach")
    other = make_user("other@example.com", "Other")
    g = a.post("/api/grants", json={"coach_email": "coach@example.com", "scopes": ["plans"]}).json()
    coach.post(f"/api/grants/{g['id']}/accept")
    assert coach.get(f"/api/athletes/{uid}/sync").json()["log"][0]["outcome"] == "sent"
    assert other.get(f"/api/athletes/{uid}/sync").status_code == 404
    # A coach's assignment is delivered to the athlete's platform too.
    coach.post(
        f"/api/athletes/{uid}/workouts",
        json={"day": (date.today() + timedelta(5)).isoformat(), "name": "Coach set", "steps": STEPS},
    )
    assert fake.upserts()[-1][2][0]["name"] == "Coach set"


def test_unapproved_adapters_do_nothing():
    zwift, mywhoosh = ADAPTERS["zwift"], ADAPTERS["mywhoosh"]
    assert not zwift.available() and not mywhoosh.available()
    assert zwift.operations == () and mywhoosh.operations == ()
    with pytest.raises(NotSupported):
        asyncio.run(zwift.upsert({}, "cq-1", {"name": "x", "steps": STEPS}, date.today()))
    with pytest.raises(NotSupported):
        asyncio.run(mywhoosh.delete({}, "cq-1"))


def test_linking_a_different_account_sends_everything_again(make_user, fake):
    a, uid = _athlete(make_user, fake)
    _schedule(a)
    assert len(fake.upserts()) == 1
    fake.token_response["athlete"] = {"id": "i9999", "name": "Other account"}
    state = parse_qs(urlparse(a.post("/api/connections/intervals/authorize").json()["url"]).query)["state"][0]
    a.get(f"/api/connections/intervals/callback?state={state}&code=x", follow_redirects=False)
    assert len(fake.upserts()) == 2
    # Same account again: nothing changed, nothing sent.
    state = parse_qs(urlparse(a.post("/api/connections/intervals/authorize").json()["url"]).query)["state"][0]
    a.get(f"/api/connections/intervals/callback?state={state}&code=y", follow_redirects=False)
    assert len(fake.upserts()) == 2


def test_deleting_an_account_removes_workouts_and_sync_data(make_user, fake):
    from app import accounts

    a, uid = _athlete(make_user, fake)
    a.post("/api/workouts", json={"name": "Lib", "steps": STEPS})
    _schedule(a)
    with SessionLocal() as db:
        accounts.delete_account(db, db.get(User, uid))
        for model in (ScheduledWorkout, ExternalWorkout, SyncJob, SyncLog):
            assert db.query(model).count() == 0, model
        from app.db import Workout

        assert db.query(Workout).count() == 0
