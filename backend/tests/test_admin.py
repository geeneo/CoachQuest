from app import runtime
from app.db import AppSetting, SessionLocal

KEY = "sk-ant-api03-" + "a" * 40 + "WXYZ"


def test_non_admin_cannot_touch_settings(make_user):
    p = make_user("a@example.com")
    assert p.get("/api/admin/settings").status_code == 403
    assert p.request("PUT", "/api/admin/settings", json={"values": {"registration_mode": "closed"}}).status_code == 403


def test_secret_is_write_only_and_encrypted(make_user):
    admin = make_user("admin@example.com")
    r = admin.request("PUT", "/api/admin/settings", json={"values": {"anthropic_api_key": KEY}})
    assert r.status_code == 200, r.text
    item = next(s for s in r.json()["settings"] if s["key"] == "anthropic_api_key")
    assert item == {**item, "source": "web", "is_set": True, "hint": "…WXYZ"}
    assert "value" not in item
    assert KEY not in admin.get("/api/admin/settings").text
    with SessionLocal() as db:
        assert KEY not in db.get(AppSetting, "anthropic_api_key").value_enc
    assert runtime.get("anthropic_api_key") == KEY


def test_clearing_falls_back_to_env(make_user):
    admin = make_user("admin@example.com")
    admin.request("PUT", "/api/admin/settings", json={"values": {"anthropic_effort": "max"}})
    assert runtime.get("anthropic_effort") == "max"
    admin.request("PUT", "/api/admin/settings", json={"values": {"anthropic_effort": ""}})
    assert runtime.get("anthropic_effort") == "high"  # the .env default


def test_invalid_values_rejected_and_nothing_saved(make_user):
    admin = make_user("admin@example.com")
    r = admin.request(
        "PUT", "/api/admin/settings", json={"values": {"registration_mode": "closed", "anthropic_effort": "turbo"}}
    )
    assert r.status_code == 422
    assert runtime.get("registration_mode") == "open"
    r = admin.request("PUT", "/api/admin/settings", json={"values": {"proxy_shared_secret": "x" * 40}})
    assert r.status_code == 422


def test_closing_registration_from_ui(client, make_user):
    admin = make_user("admin@example.com")
    admin.request("PUT", "/api/admin/settings", json={"values": {"registration_mode": "closed"}})
    r = client.post(
        "/api/auth/register",
        json={"email": "new@example.com", "password": "correct horse battery", "display_name": "N"},
        headers={"X-Requested-With": "CoachQuest"},
    )
    assert r.status_code == 403


def test_promote_and_disable_users(make_user):
    admin = make_user("admin@example.com")
    user = make_user("a@example.com")
    uid = user.get("/api/auth/me").json()["id"]
    assert admin.patch(f"/api/admin/users/{uid}", json={"is_admin": True}).status_code == 200
    assert user.get("/api/admin/settings").status_code == 200
    assert admin.patch(f"/api/admin/users/{uid}", json={"is_active": False}).status_code == 200
    assert user.get("/api/auth/me").status_code == 401  # signed out everywhere


def test_admin_cannot_demote_self(make_user):
    admin = make_user("admin@example.com")
    me = admin.get("/api/auth/me").json()["id"]
    assert admin.patch(f"/api/admin/users/{me}", json={"is_admin": False}).status_code == 400
