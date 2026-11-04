"""Product news emails from Admin → Email users (news_email.py)."""

from datetime import timedelta

from app import mailer, news_email
from app.db import Grant, NewsEmail, SessionLocal, User, utcnow
from app.db import Session as LoginSession


def _super(make_user, email="boss@example.com"):
    p = make_user(email, "Boss")
    with SessionLocal() as db:
        u = db.query(User).filter_by(email=email).one()
        u.is_admin = u.is_super_admin = True
        db.commit()
    return p


def _mail(monkeypatch):
    sent = []

    async def fake_send(to, subject, text, html=None):
        sent.append((to, subject, text, html))

    monkeypatch.setattr(mailer, "send", fake_send)
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(news_email, "PAUSE_S", 0)
    return sent


DRAFT = {"subject": "New: weather on your routes", "body": "The Weather page shows the wind on every stretch."}


def test_send_to_everyone_but_opted_out(make_user, monkeypatch):
    sent = _mail(monkeypatch)
    boss = _super(make_user)
    a = make_user("a@example.com", "Ann")
    make_user("b@example.com", "Bob")
    make_user("c@example.com", "Cid")
    a.request("PATCH", "/api/me", json={"notify_news": False})
    with SessionLocal() as db:
        db.query(User).filter_by(email="c@example.com").one().emails_disabled = True
        db.commit()
    info = boss.get("/api/admin/news-emails").json()
    assert {x["id"]: x["count"] for x in info["audiences"]}["all"] == 2  # boss and Bob
    r = boss.post("/api/admin/news-emails/test", json=DRAFT)
    assert r.json()["to"] == "boss@example.com" and sent[0][1] == "[Test] New: weather on your routes"
    r = boss.post("/api/admin/news-emails", json={**DRAFT, "audience": "all"})
    assert r.status_code == 200, r.text
    assert sorted(s[0] for s in sent[1:]) == ["b@example.com", "boss@example.com"]
    assert "Hi Bob" in sent[-1][2] or "Hi Bob" in sent[-2][2]
    assert 'Untick "Email me CoachQuest news"' in sent[-1][2]
    h = boss.get("/api/admin/news-emails").json()["history"][0]
    assert h["status"] == "sent" and h["recipients"] == 2 and h["sent"] == 2 and h["failed"] == 0


def test_audiences_and_who_may_send(make_user, monkeypatch):
    _mail(monkeypatch)
    boss = _super(make_user)
    make_user("coach@example.com", "Coach")
    make_user("old@example.com", "Old")
    with SessionLocal() as db:
        coach = db.query(User).filter_by(email="coach@example.com").one()
        old = db.query(User).filter_by(email="old@example.com").one()
        boss_id = db.query(User).filter_by(email="boss@example.com").one().id
        db.add(Grant(athlete_id=boss_id, coach_id=coach.id, scopes=["plans"], role="coach", status="active"))
        for s in db.query(LoginSession).filter_by(user_id=old.id):
            s.last_seen_at = utcnow() - timedelta(days=60)
        old.created_at = utcnow() - timedelta(days=90)
        db.commit()
        assert [u.email for u in news_email.recipients(db, "coaches")] == ["coach@example.com"]
        assert "old@example.com" not in [u.email for u in news_email.recipients(db, "active30")]
    other = make_user("x@example.com")
    assert other.get("/api/admin/news-emails").status_code == 403
    assert boss.post("/api/admin/news-emails", json={**DRAFT, "audience": "everybody"}).status_code == 422
    assert boss.post("/api/admin/news-emails", json={"subject": "Hi", "body": "short"}).status_code == 422
    with SessionLocal() as db:
        db.add(NewsEmail(subject="s", body="b" * 20, audience="all", status="sending"))
        db.commit()
    assert boss.post("/api/admin/news-emails", json={**DRAFT, "audience": "all"}).status_code == 409
