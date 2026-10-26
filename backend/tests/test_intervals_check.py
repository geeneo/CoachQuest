import httpx

from app import runtime
from app.delivery import intervals_icu as icu


def _replies(status, body):
    def handler(request):
        assert request.url.path == "/api/oauth/token" and b"coachquest-connection-test" in request.content
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler)


def test_admin_checks_the_intervals_app(make_user, monkeypatch):
    admin = make_user("admin@example.com")
    url = "/api/admin/settings/test-intervals"
    monkeypatch.setitem(runtime._overrides, "intervals_client_id", "")
    monkeypatch.setitem(runtime._overrides, "intervals_client_secret", "")
    r = admin.post(url).json()
    assert r["ok"] is False and "Set the Client ID" in r["message"]
    monkeypatch.setitem(runtime._overrides, "intervals_client_id", "1534")
    monkeypatch.setitem(runtime._overrides, "intervals_client_secret", "s3cret")
    # Wrong ID or secret: what Intervals.icu really answers.
    monkeypatch.setattr(icu, "transport", _replies(404, {"status": 404, "error": "Client and/or secret not found"}))
    r = admin.post(url).json()
    assert r["ok"] is False and "doesn't know this Client ID" in r["message"]
    # Right ID and secret: only the made-up code is refused.
    monkeypatch.setattr(icu, "transport", _replies(400, {"status": 400, "error": "Invalid code"}))
    r = admin.post(url).json()
    assert r["ok"] is True and r["redirect_uri"].endswith("/api/connections/intervals/callback")
    assert r["redirect_uri"] in r["message"]
    monkeypatch.setattr(icu, "transport", _replies(503, {}))
    assert admin.post(url).json()["ok"] is False
    assert make_user("rider@example.com").post(url).status_code in (401, 403)
