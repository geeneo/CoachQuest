import asyncio
from urllib.parse import parse_qs, urlparse

import pytest

from app.db import Connection, SessionLocal
from app.providers import strava
from app.security import encrypt_json

SECRET = "ab" * 20


def _me(p):
    return p.get("/api/auth/me").json()["id"]


def test_no_app_anywhere_means_not_configured(make_user):
    p = make_user("a@example.com")
    body = p.get("/api/connections").json()
    assert body["strava_configured"] is False
    assert body["strava_app"]["own"] is False and body["strava_app"]["server_available"] is False
    assert p.post("/api/connections/strava/authorize").status_code == 503


def test_own_app_is_used_and_secret_not_returned(make_user):
    p = make_user("a@example.com")
    assert (
        p.request("PUT", "/api/connections/strava/app", json={"client_id": "777", "client_secret": SECRET}).status_code
        == 200
    )
    body = p.get("/api/connections").json()
    assert body["strava_configured"] is True
    assert body["strava_app"] == {**body["strava_app"], "own": True, "client_id": "777", "secret_hint": "…abab"}
    assert SECRET not in str(body)
    url = p.post("/api/connections/strava/authorize").json()["url"]
    assert parse_qs(urlparse(url).query)["client_id"] == ["777"]


def test_users_apps_are_separate(make_user):
    a, b = make_user("a@example.com"), make_user("b@example.com")
    a.request("PUT", "/api/connections/strava/app", json={"client_id": "111", "client_secret": SECRET})
    b.request("PUT", "/api/connections/strava/app", json={"client_id": "222", "client_secret": SECRET})
    assert parse_qs(urlparse(a.post("/api/connections/strava/authorize").json()["url"]).query)["client_id"] == ["111"]
    assert parse_qs(urlparse(b.post("/api/connections/strava/authorize").json()["url"]).query)["client_id"] == ["222"]


def test_bad_values_rejected(make_user):
    p = make_user("a@example.com")
    r = p.request("PUT", "/api/connections/strava/app", json={"client_id": SECRET, "client_secret": SECRET})
    assert r.status_code == 422 and "short number" in r.json()["detail"]


def test_falls_back_to_server_app(make_user):
    admin = make_user("admin@example.com")
    admin.request(
        "PUT", "/api/admin/settings", json={"values": {"strava_client_id": "999", "strava_client_secret": SECRET}}
    )
    p = make_user("a@example.com")
    url = p.post("/api/connections/strava/authorize").json()["url"]
    assert parse_qs(urlparse(url).query)["client_id"] == ["999"]
    p.request("PUT", "/api/connections/strava/app", json={"client_id": "777", "client_secret": SECRET})
    url = p.post("/api/connections/strava/authorize").json()["url"]
    assert parse_qs(urlparse(url).query)["client_id"] == ["777"]


def test_changed_app_asks_to_reconnect(make_user):
    p = make_user("a@example.com")
    p.request("PUT", "/api/connections/strava/app", json={"client_id": "777", "client_secret": SECRET})
    uid = _me(p)
    with SessionLocal() as db:
        conn = Connection(
            user_id=uid,
            provider="strava",
            token_enc=encrypt_json({"access_token": "a", "refresh_token": "r", "client_id": "555"}),
        )
        db.add(conn)
        db.commit()
        asyncio.run(strava.sync(db, conn))
        assert conn.status == "error" and "connect again" in conn.last_error


@pytest.mark.parametrize("stored, expected", [("777", "777"), (None, "999")])
def test_refresh_uses_issuing_app(make_user, stored, expected):
    admin = make_user("admin@example.com")
    admin.request(
        "PUT", "/api/admin/settings", json={"values": {"strava_client_id": "999", "strava_client_secret": SECRET}}
    )
    admin.request("PUT", "/api/connections/strava/app", json={"client_id": "777", "client_secret": SECRET})
    with SessionLocal() as db:
        assert strava._app_by_client_id(db, _me(admin), stored).client_id == expected
