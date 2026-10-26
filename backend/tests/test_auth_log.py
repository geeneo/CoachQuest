from datetime import timedelta

from conftest import SECRET

from app import auth_log, runtime
from app.db import AccessLog, AuthEvent, SessionLocal, User, utcnow

PW = "correct horse battery"
VIA_NGINX = {"X-Proxy-Secret": SECRET, "X-Real-IP": "41.13.2.7", "User-Agent": "Firefox on Windows"}


def _events(**where):
    with SessionLocal() as db:
        q = db.query(AuthEvent).order_by(AuthEvent.id)
        for k, v in where.items():
            q = q.filter(getattr(AuthEvent, k) == v)
        return [(e.event, e.email, e.ip, e.user_agent, e.detail, e.user_id) for e in q]


def test_sign_ins_are_logged_with_ip(make_user, client):
    p = make_user("rider@example.com", "Rider")
    uid = p.get("/api/auth/me").json()["id"]
    assert (
        p.post(
            "/api/auth/login", json={"email": "Rider@Example.com", "password": "nope-nope-nope"}, headers=VIA_NGINX
        ).status_code
        == 401
    )
    assert (
        p.post(
            "/api/auth/login", json={"email": "ghost@example.com", "password": "nope-nope-nope"}, headers=VIA_NGINX
        ).status_code
        == 401
    )
    assert (
        p.post("/api/auth/login", json={"email": "rider@example.com", "password": PW}, headers=VIA_NGINX).status_code
        == 200
    )
    ev = _events()
    assert ev[0][0] == "registered" and ev[0][5] == uid
    assert ev[1] == ("login_failed", "rider@example.com", "41.13.2.7", "Firefox on Windows", "", uid)
    assert ev[2] == ("login_failed", "ghost@example.com", "41.13.2.7", "Firefox on Windows", "", None)
    assert ev[3][0] == "login_ok" and ev[3][2] == "41.13.2.7"
    # Without nginx's secret, a made-up X-Real-IP isn't believed.
    client.post(
        "/api/auth/login",
        json={"email": "rider@example.com", "password": PW},
        headers={"X-Requested-With": "CoachQuest", "X-Real-IP": "6.6.6.6"},
    )
    assert _events()[-1][0] == "login_ok" and _events()[-1][2] != "6.6.6.6"


def test_account_events(make_user):
    p = make_user("rider@example.com", "Rider")
    p.post("/api/auth/password", json={"current_password": PW, "new_password": "another long password"})
    # The test proxy doesn't pass the session cookie to the API, so the change signs this session out too.
    p.post("/api/auth/login", json={"email": "rider@example.com", "password": "another long password"})
    p.post("/api/auth/forgot", json={"email": "rider@example.com"})
    p.post("/api/auth/forgot", json={"email": "nobody@example.com"})
    p.post("/api/auth/logout-all")
    kinds = [e[0] for e in _events()]
    assert kinds == ["registered", "password_changed", "login_ok", "reset_requested", "reset_requested", "logout_all"]
    assert _events(event="reset_requested")[1][4] == "no such account"
    q = make_user("other@example.com")
    q.post("/api/auth/logout", headers={"Cookie": f"cq_session={q.cookie}"})  # real nginx passes the cookie on
    assert _events()[-1][:2] == ("logout", "other@example.com")


def test_admin_actions_and_view(make_user):
    admin = make_user("admin@example.com", "Admin")
    rider = make_user("rider@example.com", "Rider")
    rid = rider.get("/api/auth/me").json()["id"]
    admin.post(f"/api/admin/users/{rid}/password", json={"new_password": "set by the admin 1"})
    admin.request("PATCH", f"/api/admin/users/{rid}", json={"is_active": False})
    assert (
        rider.post("/api/auth/login", json={"email": "rider@example.com", "password": "set by the admin 1"}).status_code
        == 403
    )
    admin.request("PATCH", f"/api/admin/users/{rid}", json={"is_active": True})
    admin.request("DELETE", f"/api/admin/users/{rid}", json={"confirm_email": "rider@example.com"})
    rows = [e for e in _events() if e[1] == "rider@example.com"]
    assert [e[0] for e in rows] == [
        "registered",
        "admin_password_set",
        "admin_disabled",
        "login_disabled",
        "admin_enabled",
        "admin_deleted",
    ]
    assert rows[1][4] == "by admin@example.com"
    assert all(e[5] is None for e in rows)  # the account is gone; the email stays for the audit trail
    log = admin.get("/api/admin/sign-ins?q=rider").json()
    assert log["events"][0]["event"] == "admin_deleted" and log["events"][0]["label"] == "Deleted by an admin"
    failed = admin.get("/api/admin/sign-ins?failed=true").json()["events"]
    assert [e["event"] for e in failed] == ["login_disabled"] and failed[0]["failed"]
    assert rider.get("/api/admin/sign-ins").status_code in (401, 403)


def test_my_sign_ins_are_only_mine(make_user):
    a = make_user("a@example.com")
    make_user("b@example.com")
    mine = a.get("/api/auth/sign-ins").json()
    assert {e["email"] for e in mine} == {"a@example.com"} and mine[0]["label"] == "Created an account"


def test_retention(make_user, monkeypatch):
    p = make_user("rider@example.com")
    uid = p.get("/api/auth/me").json()["id"]
    with SessionLocal() as db:
        old = utcnow() - timedelta(days=100)
        db.add(AuthEvent(user_id=uid, email="rider@example.com", event="login_ok", at=old))
        db.add(AccessLog(athlete_id=uid, viewer_id=uid, resource="plans", at=old))
        db.add(AccessLog(athlete_id=uid, viewer_id=uid, resource="plans", at=utcnow() - timedelta(days=20)))
        db.commit()
        assert auth_log.purge(db) == {"sign_ins": 1, "access": 1}
        assert db.query(AuthEvent).count() == 1  # "registered" from today stays
        monkeypatch.setitem(runtime._overrides, "access_log_days", "10")
        assert auth_log.purge(db)["access"] == 1
        monkeypatch.setitem(runtime._overrides, "auth_log_days", "0")
        monkeypatch.setitem(runtime._overrides, "access_log_days", "0")
        db.add(AuthEvent(user_id=uid, email="x", event="login_ok", at=utcnow() - timedelta(days=5000)))
        db.commit()
        assert auth_log.purge(db) == {}
        assert db.query(User).count() == 1


def test_retention_settings_are_numbers(make_user):
    admin = make_user("admin@example.com")
    r = admin.request("PUT", "/api/admin/settings", json={"values": {"auth_log_days": "abc"}})
    assert r.status_code == 422
    r = admin.request("PUT", "/api/admin/settings", json={"values": {"auth_log_days": "30"}})
    assert r.status_code == 200
