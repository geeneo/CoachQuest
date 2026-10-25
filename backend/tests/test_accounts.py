import re
from datetime import timedelta

from conftest import CSRF
from sqlalchemy import func, select
from test_mail import _configure, fake_smtp  # noqa: F401  (fixture)

from app.db import Activity, Grant, PasswordReset, SessionLocal, User, utcnow


def _login(client, email, password):
    return client.post("/api/auth/login", json={"email": email, "password": password}, headers=CSRF).status_code


def _reset_token(client, monkeypatch, email):
    """Ask for a reset and capture the link the email would contain."""
    sent = {}

    async def capture(user, link, ttl, by_admin):
        sent["link"] = link

    monkeypatch.setattr("app.accounts.email_reset_link", capture)
    r = client.post("/api/auth/forgot", json={"email": email}, headers=CSRF)
    assert r.status_code == 200
    return r.json(), (re.search(r"token=(.+)$", sent["link"]).group(1) if sent else None)


def test_forgot_gives_same_answer_for_unknown_email(client, make_user, monkeypatch):
    make_user("a@example.com")
    known, token = _reset_token(client, monkeypatch, "a@example.com")
    unknown, none = _reset_token(client, monkeypatch, "nobody@example.com")
    assert known == unknown and token and none is None


def test_reset_link_works_once_and_signs_out(client, make_user, monkeypatch):
    p = make_user("a@example.com")
    _, token = _reset_token(client, monkeypatch, "a@example.com")
    r = client.post("/api/auth/reset", json={"token": token, "new_password": "a brand new passphrase"}, headers=CSRF)
    assert r.status_code == 200
    assert p.get("/api/auth/me").status_code == 401  # old session gone
    assert _login(client, "a@example.com", "a brand new passphrase") == 200
    again = client.post("/api/auth/reset", json={"token": token, "new_password": "another passphrase!"}, headers=CSRF)
    assert again.status_code == 400


def test_expired_link_rejected(client, make_user, monkeypatch):
    make_user("a@example.com")
    _, token = _reset_token(client, monkeypatch, "a@example.com")
    with SessionLocal() as db:
        for r in db.scalars(select(PasswordReset)):
            r.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
    r = client.post("/api/auth/reset", json={"token": token, "new_password": "a brand new passphrase"}, headers=CSRF)
    assert r.status_code == 400


def test_forgot_email_is_sent_when_smtp_is_set(client, make_user, fake_smtp):  # noqa: F811
    admin = make_user("admin@example.com")
    _configure(admin)
    client.post("/api/auth/forgot", json={"email": "admin@example.com"}, headers=CSRF)
    assert any(c[0] == "send" and c[1] == "admin@example.com" for c in fake_smtp[-1])


def test_admin_sets_password(client, make_user):
    admin = make_user("admin@example.com")
    user = make_user("a@example.com")
    uid = user.get("/api/auth/me").json()["id"]
    assert user.get("/api/admin/users").status_code == 403
    r = admin.post(f"/api/admin/users/{uid}/password", json={"new_password": "set by the admin!"})
    assert r.status_code == 200
    assert user.get("/api/auth/me").status_code == 401
    assert _login(client, "a@example.com", "set by the admin!") == 200


def test_admin_reset_link_shown_without_smtp(client, make_user):
    admin = make_user("admin@example.com")
    uid = make_user("a@example.com").get("/api/auth/me").json()["id"]
    r = admin.post(f"/api/admin/users/{uid}/reset-link").json()
    assert r["link"].startswith("http://testserver/reset-password?token=")
    assert r["emailed"].startswith("Not emailed")
    token = r["link"].split("token=")[1]
    ok = client.post("/api/auth/reset", json={"token": token, "new_password": "from the admin link"}, headers=CSRF)
    assert ok.status_code == 200


def test_delete_user_removes_everything(client, make_user):
    admin = make_user("admin@example.com")
    athlete = make_user("a@example.com")
    uid = athlete.get("/api/auth/me").json()["id"]
    athlete.post("/api/grants", json={"coach_email": "admin@example.com", "scopes": ["activities"]})
    with SessionLocal() as db:
        db.add(Activity(user_id=uid, source="strava", external_id="1", start_time=utcnow()))
        db.commit()
    bad = admin.request("DELETE", f"/api/admin/users/{uid}", json={"confirm_email": "wrong@example.com"})
    assert bad.status_code == 400
    r = admin.request("DELETE", f"/api/admin/users/{uid}", json={"confirm_email": "A@example.com"})
    assert r.status_code == 200
    with SessionLocal() as db:
        assert db.get(User, uid) is None
        assert db.scalar(select(func.count()).select_from(Activity)) == 0
        assert db.scalar(select(func.count()).select_from(Grant)) == 0
    assert athlete.get("/api/auth/me").status_code == 401


def test_admin_cannot_delete_self(make_user):
    admin = make_user("admin@example.com")
    me = admin.get("/api/auth/me").json()["id"]
    r = admin.request("DELETE", f"/api/admin/users/{me}", json={"confirm_email": "admin@example.com"})
    assert r.status_code == 400


def test_storage_report(make_user):
    admin = make_user("admin@example.com")
    r = admin.get("/api/admin/storage").json()
    assert r["database_bytes"] > 0 and r["tables"]["Users"] == 1 and r["disk"]["free"] > 0
