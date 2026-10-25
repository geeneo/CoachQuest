from conftest import CSRF, SECRET


def test_register_login_and_me(make_user):
    p = make_user("a@example.com", "Ann")
    assert p.get("/api/auth/me").json()["display_name"] == "Ann"


def test_wrong_password(client, make_user):
    make_user("a@example.com")
    r = client.post("/api/auth/login", json={"email": "a@example.com", "password": "nope"}, headers=CSRF)
    assert r.status_code == 401


def test_short_password_rejected(client):
    r = client.post(
        "/api/auth/register", json={"email": "b@example.com", "password": "short", "display_name": "B"}, headers=CSRF
    )
    assert r.status_code == 422


def test_admin_flag_from_env(make_user):
    assert make_user("admin@example.com").get("/api/auth/me").json()["is_admin"] is True


def test_verify_requires_proxy_secret(client, make_user):
    p = make_user("a@example.com")
    r = client.get("/internal/auth/verify", cookies={"cq_session": p.cookie})
    assert r.status_code == 401
    r = client.get("/internal/auth/verify", headers={"X-Proxy-Secret": SECRET}, cookies={"cq_session": p.cookie})
    assert r.status_code == 200 and r.headers["X-Auth-User-Id"]


def test_forged_identity_header_is_rejected(client, make_user):
    make_user("a@example.com")
    # Someone reaching the API directly, pretending to be user 1
    assert client.get("/api/auth/me", headers={"X-Auth-User-Id": "1"}).status_code == 401
    assert client.get("/api/auth/me", headers={"X-Auth-User-Id": "1", "X-Proxy-Secret": "guess"}).status_code == 401


def test_csrf_header_required(make_user):
    p = make_user("a@example.com")
    r = p.client.patch(
        "/api/me",
        json={"ftp_watts": 250},
        headers={"X-Auth-User-Id": "1", "X-Proxy-Secret": SECRET},
    )
    assert r.status_code == 403


def test_logout_kills_session(make_user):
    p = make_user("a@example.com")
    cookie = p.cookie
    p.post("/api/auth/logout", cookies={"cq_session": cookie})
    p.cookie = cookie
    assert p.get("/api/auth/me").status_code == 401


def test_admin_endpoints_need_admin(make_user):
    assert make_user("a@example.com").get("/api/admin/stats").status_code == 403
    assert make_user("admin@example.com").get("/api/admin/stats").status_code == 200


def _session_count(user_email):
    from sqlalchemy import func, select

    from app.db import Session, SessionLocal, User

    with SessionLocal() as db:
        uid = db.scalar(select(User.id).where(User.email == user_email))
        return db.scalar(select(func.count()).where(Session.user_id == uid))


def test_change_password_signs_out_other_devices(client, make_user):
    laptop = make_user("a@example.com")
    # Sign in a second time, as if from another device.
    r = client.post(
        "/api/auth/login",
        json={"email": "a@example.com", "password": "correct horse battery"},
        headers=CSRF,
    )
    other_cookie = r.cookies["cq_session"]
    client.cookies.clear()
    assert _session_count("a@example.com") == 2

    r = laptop.post(
        "/api/auth/password",
        json={"current_password": "correct horse battery", "new_password": "a brand new passphrase"},
        cookies={"cq_session": laptop.cookie},
    )
    assert r.status_code == 200, r.text
    assert _session_count("a@example.com") == 1
    assert laptop.get("/api/auth/me").status_code == 200  # this device stays in
    laptop.cookie = other_cookie
    assert laptop.get("/api/auth/me").status_code == 401  # the other one is out

    ok = client.post(
        "/api/auth/login", json={"email": "a@example.com", "password": "a brand new passphrase"}, headers=CSRF
    )
    assert ok.status_code == 200


def test_change_password_needs_current_password(make_user):
    p = make_user("a@example.com")
    r = p.post("/api/auth/password", json={"current_password": "wrong", "new_password": "a brand new passphrase"})
    assert r.status_code == 400
    r = p.post("/api/auth/password", json={"current_password": "correct horse battery", "new_password": "short"})
    assert r.status_code == 422
