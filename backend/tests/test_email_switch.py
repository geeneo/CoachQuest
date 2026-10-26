"""Admin switch: no emails to a user, except what they need to get into their account."""

from test_mail import _configure, fake_smtp  # noqa: F401  (fixture)

from app.db import AuthEvent, SessionLocal


def test_admin_turns_off_emails_to_a_user(make_user, fake_smtp, monkeypatch):  # noqa: F811
    admin = make_user("admin@example.com", "Admin")
    _configure(admin)
    ann = make_user("ann@example.com", "Ann")
    coach = make_user("coach@example.com", "Cobus")
    aid = ann.get("/api/auth/me").json()["id"]
    sent = []

    async def capture(to, subject, text):
        sent.append((to, subject))

    monkeypatch.setattr("app.mailer.send", capture)
    admin.request("PATCH", f"/api/admin/users/{aid}", json={"emails_disabled": True})
    assert ann.get("/api/auth/me").json()["emails_disabled"] is True
    row = next(u for u in admin.get("/api/admin/users").json() if u["id"] == aid)
    assert row["emails_disabled"] is True and "emails off" in row["flags"]

    # A coach invitation to Ann's coach still goes out; Cobus inviting Ann as coach doesn't reach her.
    ann.post("/api/grants", json={"coach_email": "coach@example.com", "scopes": ["plans"]})
    coach.post("/api/grants", json={"coach_email": "ann@example.com", "scopes": ["plans"]})
    assert [to for to, _ in sent] == ["coach@example.com"]
    # Password reset links still reach her.
    ann.post("/api/auth/forgot", json={"email": "ann@example.com"})
    assert sent[-1][0] == "ann@example.com"

    admin.request("PATCH", f"/api/admin/users/{aid}", json={"emails_disabled": False})
    with SessionLocal() as db:
        events = [e.event for e in db.query(AuthEvent).filter(AuthEvent.event.like("admin_emails%"))]
    assert events == ["admin_emails_off", "admin_emails_on"]
    assert ann.request("PATCH", f"/api/admin/users/{aid}", json={"emails_disabled": True}).status_code in (401, 403)
