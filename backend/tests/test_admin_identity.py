"""Super admins fix a user's name and sign-in email (PATCH /api/admin/users/{id}/identity)."""

from test_approval import _login
from test_mail import _configure, fake_smtp  # noqa: F401  (fixture)


def test_super_admin_fixes_name_and_email(make_user, fake_smtp):  # noqa: F811
    boss = make_user("admin@example.com", "Boss")
    _configure(boss)
    rider = make_user("natalie@example.com", "natalie  van niekerk")
    rid = rider.get("/api/auth/me").json()["id"]
    url = f"/api/admin/users/{rid}/identity"

    r = boss.patch(url, json={"display_name": "Natalie  van Niekerk "}).json()
    assert r["changed"] == ["name"] and r["display_name"] == "Natalie van Niekerk"

    other = make_user("taken@example.com", "Taken")
    assert boss.patch(url, json={"email": "TAKEN@example.com"}).status_code == 409
    assert boss.patch(url, json={"email": "not an email"}).status_code == 422

    r = boss.patch(url, json={"email": "Natalie.vN@Example.com"}).json()
    assert r["changed"] == ["email"] and r["email"] == "natalie.vn@example.com"
    told = {c[1] for calls in fake_smtp for c in calls if c[0] == "send"}
    assert {"natalie@example.com", "natalie.vn@example.com"} <= told
    # She signs in with the new email; the old one no longer works.
    assert _login(rider.client, "natalie.vn@example.com").status_code == 200
    assert _login(rider.client, "natalie@example.com").status_code == 401
    log = boss.get("/api/admin/sign-ins?q=natalie.vn").json()
    assert any(e["event"] == "admin_email_changed" for e in log.get("events", log))

    # Plain admins can't.
    oid = other.get("/api/auth/me").json()["id"]
    assert boss.patch(f"/api/admin/users/{oid}", json={"is_admin": True}).status_code == 200
    assert other.patch(url, json={"display_name": "X"}).status_code == 403
