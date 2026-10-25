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
