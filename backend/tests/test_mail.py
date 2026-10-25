import smtplib

import pytest

from app import mailer

SENT = []


class FakeSMTP:
    def __init__(self, host, port, timeout=None, context=None):
        self.calls = [("connect", host, port)]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        SENT.append(self.calls)

    def starttls(self, context=None):
        self.calls.append(("starttls",))

    def login(self, user, password):
        if password != "app-password":
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")
        self.calls.append(("login", user))

    def send_message(self, msg):
        self.calls.append(("send", msg["To"], msg["Subject"], msg["From"]))


@pytest.fixture()
def fake_smtp(monkeypatch):
    SENT.clear()
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", FakeSMTP)
    return SENT


def _configure(admin, **extra):
    values = {
        "smtp_host": "smtp.example.com",
        "smtp_port": "587",
        "smtp_security": "starttls",
        "smtp_username": "coach@example.com",
        "smtp_password": "app-password",
        "smtp_from": "CoachQuest <coach@example.com>",
        **extra,
    }
    r = admin.request("PUT", "/api/admin/settings", json={"values": values})
    assert r.status_code == 200, r.text


def test_test_email_without_setup(make_user, fake_smtp):
    admin = make_user("admin@example.com")
    r = admin.post("/api/admin/settings/test-email", json={})
    assert r.json()["ok"] is False and "not set up" in r.json()["message"]


def test_test_email_sends_with_starttls_and_login(make_user, fake_smtp):
    admin = make_user("admin@example.com")
    _configure(admin)
    r = admin.post("/api/admin/settings/test-email", json={})
    assert r.json()["ok"] is True, r.json()
    calls = fake_smtp[0]
    assert ("starttls",) in calls and ("login", "coach@example.com") in calls
    assert ("send", "admin@example.com", "CoachQuest test email", "CoachQuest <coach@example.com>") in calls


def test_wrong_password_gives_clear_message(make_user, fake_smtp):
    admin = make_user("admin@example.com")
    _configure(admin, smtp_password="wrong")
    r = admin.post("/api/admin/settings/test-email", json={})
    assert r.json() == {"ok": False, "message": "The mail server rejected the username or password."}


def test_bad_from_address_rejected(make_user):
    admin = make_user("admin@example.com")
    r = admin.request("PUT", "/api/admin/settings", json={"values": {"smtp_from": "not an email"}})
    assert r.status_code == 422


def test_smtp_password_is_write_only(make_user):
    admin = make_user("admin@example.com")
    _configure(admin)
    assert "app-password" not in admin.get("/api/admin/settings").text
