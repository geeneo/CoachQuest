"""Admin → Update CoachQuest: super admins only, password again, a request file for the server's agent."""

import os
from datetime import UTC, datetime
from pathlib import Path

from app import deploy_requests


def _agent(seen_ago_s: int = 10):
    d = deploy_requests.folder()
    d.mkdir(parents=True, exist_ok=True)
    seen = datetime.fromtimestamp(datetime.now(UTC).timestamp() - seen_ago_s, UTC)
    (d / "agent.txt").write_text(f"seen={seen:%Y-%m-%dT%H:%M:%SZ}\n")
    (d / "versions.txt").write_text(
        "checked=2026-10-29T10:00:00Z\nbranch=main\ndisk=abc1234\nremote=def5678\ndirty=0\n"
        "--- commits\ndef5678\t2026-10-29\tStrava notes\n"
    )
    for f in ("request.txt", "status.txt"):
        (d / f).unlink(missing_ok=True)


def test_only_super_admins_and_with_the_password(make_user):
    boss = make_user("admin@example.com")  # super admin (first admin)
    helper = make_user("helper@example.com")
    hid = helper.get("/api/auth/me").json()["id"]
    boss.patch(f"/api/admin/users/{hid}", json={"is_admin": True})
    _agent()
    assert helper.get("/api/admin/update").status_code == 403
    s = boss.get("/api/admin/update").json()
    assert s["agent"]["alive"] and s["versions"]["remote"] == "def5678"
    assert s["new_commits"] == [{"commit": "def5678", "date": "2026-10-29", "subject": "Strava notes"}]
    bad = boss.post("/api/admin/update/deploy", json={"target": "all", "password": "nope"})
    assert bad.status_code == 403
    r = boss.post("/api/admin/update/deploy", json={"target": "backend", "password": "correct horse battery"})
    assert r.status_code == 200 and r.json()["pending"]
    req = (deploy_requests.folder() / "request.txt").read_text()
    assert "kind=deploy\ntarget=backend\nby=admin@example.com" in req
    # A second one waits for the first.
    again = boss.post("/api/admin/update/deploy", json={"target": "all", "password": "correct horse battery"})
    assert again.status_code == 409
    from sqlalchemy import select

    from app.db import AuthEvent, SessionLocal

    with SessionLocal() as db:
        assert db.scalar(select(AuthEvent).where(AuthEvent.event == "admin_deploy")) is not None


def test_needs_a_live_agent_and_a_known_target(make_user):
    boss = make_user("admin@example.com")
    _agent(seen_ago_s=600)  # cron not installed or stopped
    s = boss.get("/api/admin/update").json()
    assert not s["agent"]["alive"]
    r = boss.post("/api/admin/update/deploy", json={"target": "all", "password": "correct horse battery"})
    assert r.status_code == 409 and "option 11" in r.json()["detail"]
    _agent()
    r = boss.post("/api/admin/update/deploy", json={"target": "everything", "password": "correct horse battery"})
    assert r.status_code == 422
    # Check for updates leaves a check request.
    boss.post("/api/admin/update/check")
    assert "kind=check" in (deploy_requests.folder() / "request.txt").read_text()


def test_state_reads_the_agents_files():
    _agent()
    d = deploy_requests.folder()
    (d / "status.txt").write_text("state=failed\ntarget=all\nby=a@b.c\nexit=1\n")
    (d / "deploy.log").write_text("\n".join(f"line {i}" for i in range(200)))
    (d / "history.log").write_text("one\ntwo\n")
    s = deploy_requests.state()
    assert s["status"]["state"] == "failed" and len(s["log"]) == 120 and s["log"][-1] == "line 199"
    assert s["history"] == ["two", "one"]
    assert Path(d).is_dir() and os.access(d, os.W_OK)
