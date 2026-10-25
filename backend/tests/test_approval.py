from conftest import CSRF
from test_mail import _configure, fake_smtp  # noqa: F401  (fixture)


def _register(client, email):
    return client.post(
        "/api/auth/register",
        json={"email": email, "password": "correct horse battery", "display_name": "New Rider"},
        headers=CSRF,
    )


def _login(client, email):
    return client.post("/api/auth/login", json={"email": email, "password": "correct horse battery"}, headers=CSRF)


def test_approval_flow(client, make_user, fake_smtp):  # noqa: F811
    admin = make_user("admin@example.com")
    _configure(admin)
    admin.request("PUT", "/api/admin/settings", json={"values": {"registration_mode": "approval"}})

    r = _register(client, "new@example.com")
    assert r.status_code == 200 and r.json()["pending"] is True
    assert "cq_session" not in r.cookies
    assert any(c[0] == "send" and c[1] == "admin@example.com" for c in fake_smtp[-1])  # admin told

    r = _login(client, "new@example.com")
    assert r.status_code == 403 and "waiting" in r.json()["detail"]

    users = admin.get("/api/admin/users").json()
    waiting = users[0]
    assert waiting["email"] == "new@example.com" and waiting["approved"] is False  # listed first

    r = admin.post(f"/api/admin/users/{waiting['id']}/approve").json()
    assert r["emailed"] == "Emailed new@example.com."
    assert _login(client, "new@example.com").status_code == 200


def test_reject_removes_the_sign_up(client, make_user):
    admin = make_user("admin@example.com")
    admin.request("PUT", "/api/admin/settings", json={"values": {"registration_mode": "approval"}})
    _register(client, "spam@example.com")
    uid = next(u["id"] for u in admin.get("/api/admin/users").json() if u["email"] == "spam@example.com")
    assert admin.post(f"/api/admin/users/{uid}/reject").status_code == 200
    assert all(u["email"] != "spam@example.com" for u in admin.get("/api/admin/users").json())
    me = admin.get("/api/auth/me").json()["id"]
    assert admin.post(f"/api/admin/users/{me}/reject").status_code == 400  # approved accounts use Delete


def test_admin_emails_skip_approval(client, make_user):
    make_user("first@example.com")
    # Switching to approval mode needs an admin; ADMIN_EMAILS sign-ups are approved at once.
    r = _register(client, "admin@example.com")
    assert r.status_code == 200 and r.json().get("pending") is None
