"""app.movedb copies every table to another database and checks the counts; the source isn't touched."""

import os
import tempfile

import pytest
from sqlalchemy import create_engine, text

from app import movedb
from app.db import SessionLocal, User, engine


def test_copy_everything_and_refuse_a_full_target(make_user):
    a = make_user("rider@example.com")
    a.post("/api/athletes/me/segments", json={"link": "https://www.strava.com/segments/1234567", "name": "Climb"})
    target = f"sqlite:///{tempfile.mkdtemp()}/copy.db"
    source = os.environ["DATABASE_URL"]
    out = movedb.copy(source, target, log=lambda *_: None)
    assert out["ok"] and out["tables"]["users"] == (1, 1) and out["tables"]["segments"] == (1, 1)
    with create_engine(target).connect() as c:
        assert c.scalar(text("SELECT email FROM users")) == "rider@example.com"
        assert c.scalar(text("SELECT name FROM segments")) == "Climb"
    # A second copy into the same target is refused; --replace starts it over.
    try:
        movedb.copy(source, target, log=lambda *_: None)
        raise AssertionError("copied into a full target")
    except SystemExit as exc:
        assert "isn't empty" in str(exc)
    assert movedb.copy(source, target, replace=True, log=lambda *_: None)["ok"]
    try:
        movedb.copy(source, source, log=lambda *_: None)
        raise AssertionError("copied onto itself")
    except SystemExit as exc:
        assert "same database" in str(exc)


@pytest.mark.skipif(not os.environ["DATABASE_URL"].startswith("sqlite"), reason="Postgres refuses such data")
def test_fixes_what_sqlite_let_through(make_user):
    a = make_user("rider@example.com")
    uid = a.get("/api/auth/me").json()["id"]
    a.post("/api/athletes/me/segments", json={"link": "https://www.strava.com/segments/1234567", "name": "Climb"})
    with engine.begin() as c:  # SQLite doesn't check lengths or links
        c.execute(text("UPDATE users SET display_name = :n WHERE id = :i"), {"n": "x" * 150, "i": uid})
        c.execute(text("UPDATE segments SET added_by = 999"))
    out = movedb.copy(os.environ["DATABASE_URL"], f"sqlite:///{tempfile.mkdtemp()}/c.db", log=lambda *_: None)
    assert out["ok"]
    assert out["fixes"]["users.display_name: cut to 100 characters"] == 1
    assert out["fixes"]["segments.added_by: link to a missing users row emptied"] == 1
    with SessionLocal() as db:
        assert len(db.get(User, uid).display_name) == 150  # the source wasn't changed
