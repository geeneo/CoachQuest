import asyncio

import httpx
import pytest

from app.db import SessionLocal, User
from app.providers import strava

SECRET = "ab" * 20


def _fake_strava(monkeypatch, status, body):
    real = httpx.AsyncClient

    def handler(request):
        return httpx.Response(status, json=body)

    monkeypatch.setattr(strava.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


def _exchange(user_id, scope="read,activity:read_all"):
    with SessionLocal() as db:
        return asyncio.run(strava.exchange_code(db, db.get(User, user_id), "code123", scope))


@pytest.fixture()
def user_with_app(make_user):
    p = make_user("a@example.com")
    p.request("PUT", "/api/connections/strava/app", json={"client_id": "777", "client_secret": SECRET})
    return p.get("/api/auth/me").json()["id"]


@pytest.mark.parametrize(
    "field, reason", [("client_secret", "secret"), ("client_id", "client_id"), ("code", "code"), ("other", "strava")]
)
def test_token_errors_are_classified(monkeypatch, user_with_app, field, reason):
    _fake_strava(
        monkeypatch,
        400,
        {"message": "Bad Request", "errors": [{"resource": "Application", "field": field, "code": "invalid"}]},
    )
    with pytest.raises(strava.StravaLinkError) as exc:
        _exchange(user_with_app)
    assert exc.value.reason == reason


def test_missing_activity_scope(user_with_app):
    with pytest.raises(strava.StravaLinkError) as exc:
        _exchange(user_with_app, scope="read")
    assert exc.value.reason == "scope"


def test_success_stores_issuing_client_id(monkeypatch, user_with_app):
    _fake_strava(
        monkeypatch, 200, {"access_token": "a", "refresh_token": "r", "expires_at": 4102444800, "athlete": {"id": 5}}
    )
    conn = _exchange(user_with_app)
    from app.security import decrypt_json

    assert conn.external_id == "5" and decrypt_json(conn.token_enc)["client_id"] == "777"


def test_unknown_strava_error_shows_stravas_message(monkeypatch, user_with_app):
    _fake_strava(
        monkeypatch,
        403,
        {"message": "Limit Exceeded", "errors": [{"resource": "Application", "field": "athletes", "code": "exceeded"}]},
    )
    with pytest.raises(strava.StravaLinkError) as exc:
        _exchange(user_with_app)
    assert exc.value.reason == "strava" and exc.value.public == "Strava said: Limit Exceeded athletes exceeded"


def test_callback_passes_server_error_detail(monkeypatch, make_user):
    from urllib.parse import parse_qs, urlparse

    p = make_user("b@example.com")
    p.request("PUT", "/api/connections/strava/app", json={"client_id": "777", "client_secret": SECRET})
    state = parse_qs(urlparse(p.post("/api/connections/strava/authorize").json()["url"]).query)["state"][0]

    async def boom(*a, **kw):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(strava, "exchange_code", boom)
    r = p.get(
        f"/api/connections/strava/callback?state={state}&code=c&scope=read,activity:read_all", follow_redirects=False
    )
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["error"] == ["strava"] and q["detail"] == ["Server error: RuntimeError: database is locked"]


def test_401_authorization_error_means_wrong_secret(monkeypatch, user_with_app):
    _fake_strava(
        monkeypatch,
        401,
        {"message": "Authorization Error", "errors": [{"resource": "Application", "field": "", "code": "invalid"}]},
    )
    with pytest.raises(strava.StravaLinkError) as exc:
        _exchange(user_with_app)
    assert exc.value.reason == "secret"
