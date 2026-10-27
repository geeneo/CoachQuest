from test_approval import _login, _register
from test_mail import _configure, fake_smtp  # noqa: F401  (fixture)

from app import accounts
from app.db import SessionLocal, User

SUPER = {"values": {"signup_approval": "on"}}


def _id(admin, email):
    return next(u["id"] for u in admin.get("/api/admin/users").json() if u["email"] == email)


def _make_admin(boss, user):
    uid = user.get("/api/auth/me").json()["id"]
    assert boss.patch(f"/api/admin/users/{uid}", json={"is_admin": True}).status_code == 200
    return uid


def test_admin_emails_are_super_admins(make_user):
    boss = make_user("admin@example.com", "Boss")
    me = boss.get("/api/auth/me").json()
    assert me["is_admin"] and me["is_super_admin"]
    rider = make_user("rider@example.com")
    assert rider.get("/api/auth/me").json()["is_super_admin"] is False


def test_only_super_admins_switch_it_and_approve(client, make_user, fake_smtp):  # noqa: F811
    boss = make_user("admin@example.com", "Boss")
    _configure(boss)
    helper = make_user("helper@example.com", "Helper")
    _make_admin(boss, helper)
    # A regular admin can't turn it on (or off).
    assert helper.request("PUT", "/api/admin/settings", json=SUPER).status_code == 403
    assert boss.request("PUT", "/api/admin/settings", json=SUPER).status_code == 200
    setting = next(s for s in boss.get("/api/admin/settings").json()["settings"] if s["key"] == "signup_approval")
    assert setting["value"] == "on" and setting["super_only"] is True

    # Registration is still "open", but the new user waits; only the super admin is emailed.
    fake_smtp.clear()
    r = _register(client, "new@example.com")
    assert r.json()["pending"] is True
    told = {c[1] for msgs in fake_smtp for c in msgs if c[0] == "send"}
    assert told == {"admin@example.com"}
    assert _login(client, "new@example.com").status_code == 403

    uid = _id(boss, "new@example.com")
    assert helper.post(f"/api/admin/users/{uid}/approve").status_code == 403
    assert helper.post(f"/api/admin/users/{uid}/reject").status_code == 403
    assert boss.post(f"/api/admin/users/{uid}/approve").status_code == 200
    assert _login(client, "new@example.com").status_code == 200

    # Switched off: sign-ups go straight in again (registration is open).
    assert boss.request("PUT", "/api/admin/settings", json={"values": {"signup_approval": "off"}}).status_code == 200
    assert _register(client, "later@example.com").json().get("pending") is None


def test_regular_admins_cant_touch_super_admins(make_user):
    boss = make_user("admin@example.com", "Boss")
    helper = make_user("helper@example.com", "Helper")
    hid = _make_admin(boss, helper)
    bid = boss.get("/api/auth/me").json()["id"]
    assert helper.patch(f"/api/admin/users/{bid}", json={"is_admin": False}).status_code == 403
    assert helper.patch(f"/api/admin/users/{bid}", json={"is_active": False}).status_code == 403
    assert helper.post(f"/api/admin/users/{bid}/password", json={"new_password": "x" * 12}).status_code == 403
    assert helper.post(f"/api/admin/users/{bid}/reset-link").status_code == 403
    assert (
        helper.request("DELETE", f"/api/admin/users/{bid}", json={"confirm_email": "admin@example.com"}).status_code
        == 403
    )
    # Nor make themselves super admin.
    assert helper.patch(f"/api/admin/users/{hid}", json={"is_super_admin": True}).status_code == 403

    # A super admin can make another one, who then can't be demoted to plain user in one go.
    assert boss.patch(f"/api/admin/users/{hid}", json={"is_super_admin": True}).status_code == 200
    row = next(u for u in boss.get("/api/admin/users").json() if u["id"] == hid)
    assert row["is_super_admin"] and row["is_admin"]
    assert boss.patch(f"/api/admin/users/{hid}", json={"is_admin": False}).status_code == 400
    assert boss.patch(f"/api/admin/users/{hid}", json={"is_super_admin": False, "is_admin": False}).status_code == 200
    # Nobody removes their own super admin rights.
    assert boss.patch(f"/api/admin/users/{bid}", json={"is_super_admin": False}).status_code == 400


def test_only_super_admin_cant_pause_themselves(make_user):
    boss = make_user("admin@example.com", "Boss")
    helper = make_user("helper@example.com", "Helper")
    _make_admin(boss, helper)  # another admin, but not a super admin
    r = boss.post("/api/auth/pause", json={"confirm_email": "admin@example.com"})
    assert r.status_code == 400 and "super admin" in r.json()["detail"]


def test_super_admin_emails_promoted_at_start(make_user):
    make_user("admin@example.com")
    with SessionLocal() as db:
        u = db.query(User).filter_by(email="admin@example.com").one()
        u.is_admin = u.is_super_admin = False
        db.commit()
        accounts.promote_super_admins(db)
        db.refresh(u)
        assert u.is_admin and u.is_super_admin
