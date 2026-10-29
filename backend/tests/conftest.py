import os
import tempfile

from cryptography.fernet import Fernet

_tmp = tempfile.mkdtemp()
os.environ.update(
    # TEST_DATABASE_URL=postgresql+psycopg://... runs the suite on Postgres (an empty database).
    DATABASE_URL=os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_tmp}/test.db",
    PROXY_SHARED_SECRET="test-secret-" + "x" * 40,
    TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    PUBLIC_BASE_URL="http://testserver",
    ENABLE_SCHEDULER="false",
    COOKIE_SECURE="false",
    ADMIN_EMAILS="admin@example.com",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import SESSION_COOKIE  # noqa: E402
from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

SECRET = os.environ["PROXY_SHARED_SECRET"]
CSRF = {"X-Requested-With": "CoachQuest"}


class Proxy:
    """Plays nginx: runs auth_request against /internal/auth/verify, then forwards identity."""

    def __init__(self, client: TestClient):
        self.client = client
        self.cookie = None

    def _identity(self) -> dict:
        # Only this user's cookie: a test's own client.post (register, login) leaves its cookie in the
        # shared client, which would otherwise win over ours.
        self.client.cookies.clear()
        if not self.cookie:
            return {}
        r = self.client.get(
            "/internal/auth/verify",
            headers={"X-Proxy-Secret": SECRET},
            cookies={SESSION_COOKIE: self.cookie},
        )
        if r.status_code != 200:
            return {}
        return {"X-Auth-User-Id": r.headers["X-Auth-User-Id"], "X-Proxy-Secret": SECRET}

    def request(self, method: str, url: str, **kw):
        headers = {**CSRF, **self._identity(), **kw.pop("headers", {})}
        r = self.client.request(method, url, headers=headers, **kw)
        if SESSION_COOKIE in r.cookies:
            self.cookie = r.cookies[SESSION_COOKIE]
        self.client.cookies.clear()
        return r

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)

    def patch(self, url, **kw):
        return self.request("PATCH", url, **kw)

    def delete(self, url, **kw):
        return self.request("DELETE", url, **kw)


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def make_user(client):
    def _make(email: str, name: str = "User") -> Proxy:
        p = Proxy(client)
        r = p.post(
            "/api/auth/register", json={"email": email, "password": "correct horse battery", "display_name": name}
        )
        assert r.status_code == 200, r.text
        return p

    return _make
