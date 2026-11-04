"""News emails: the post's Markdown laid out as HTML, and clean plain text."""

from types import SimpleNamespace

from app import email_md, news_email

MD = """Training load that counts like **TrainingPeaks**.

## Training load

Your **fitness (CTL)** is closer:

- **Runs** are scored with a new
  **Run threshold power**.
- See *the guide* at https://example.com/news.
- [Profile](https://example.com/profile) <script>

1. First
2. Second
"""


def test_html():
    h = email_md.to_html(MD)
    assert "<strong>TrainingPeaks</strong>" in h
    assert '<h2 style="color:#032440' in h and ">Training load</h2>" in h
    assert h.count("<li") == 5 and "<ol" in h and "<ul" in h
    assert "<strong>Runs</strong> are scored with a new <strong>Run threshold power</strong>." in h  # joined
    assert "<em>the guide</em>" in h and '<a href="https://example.com/news"' in h
    assert '<a href="https://example.com/profile" style="color:#0b6fbf">Profile</a>' in h
    assert "<script>" not in h and "&lt;script&gt;" in h
    assert "**" not in h and "##" not in h


def test_text():
    t = email_md.to_text(MD)
    assert "**" not in t and "##" not in t
    assert "TRAINING LOAD" in t and "• Runs are scored with a new Run threshold power." in t
    assert "Profile (https://example.com/profile)" in t and "1. First" in t


def test_news_email_is_a_page():
    u = SimpleNamespace(display_name="Michael <Nel>")
    page = news_email.html_body(u, "What's new in CoachQuest", MD)
    assert page.startswith("<!doctype html>") and "Hi Michael &lt;Nel&gt;," in page
    assert "Open CoachQuest" in page and "/profile" in page
    assert "Hi Michael <Nel>," in news_email.text(u, MD) and "**" not in news_email.text(u, MD)


READINESS = """**Verdict: GO** for Wed 4 Nov 2026

Your recovery markers are in your normal range.

**Today:** Keep the session as planned: 3x10 min tempo at 165-175 W (Z3)."""


def test_every_email_is_laid_out(monkeypatch):
    import asyncio

    from app import mailer

    sent = {}
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(mailer, "_send", lambda to, subject, text, html=None: sent.update(text=text, html=html))
    asyncio.run(mailer.send("a@example.com", "Reset", "Hi Ann,\n\n**Click** below:\nhttps://x.example/reset?t=1"))
    assert "**" not in sent["text"] and "Click below:" in sent["text"]
    assert "<strong>Click</strong> below:<br>" in sent["html"]  # its own line breaks stay
    assert '<a href="https://x.example/reset?t=1"' in sent["html"] and "<h1" in sent["html"]


def test_ai_coach_email():
    from app.assessments import email_bodies

    text, page = email_bodies(SimpleNamespace(display_name="Natalie"), "Today: GO", READINESS)
    assert text.startswith("Hi Natalie,") and "**" not in text and "Verdict: GO for Wed 4 Nov 2026" in text
    assert "<strong>Verdict: GO</strong>" in page and "Open CoachQuest" in page


def test_logo_inside_the_email(monkeypatch):
    import asyncio

    from app import mailer, runtime

    got = {}

    class FakeSMTP:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, **kw):
            pass

        def login(self, *a):
            pass

        def send_message(self, msg):
            got["msg"] = msg

    settings = {"smtp_host": "mail.example", "smtp_from": "cq@example.com", "smtp_security": "starttls"}
    monkeypatch.setattr(runtime, "get", lambda k: settings.get(k))
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    asyncio.run(mailer.send("a@example.com", "Today: GO", "**Verdict: GO**"))
    msg = got["msg"]
    assert msg.get_content_type() == "multipart/alternative"
    plain, rich = msg.get_payload()
    assert plain.get_content_type() == "text/plain" and "**" not in plain.get_content()
    assert rich.get_content_type() == "multipart/related"
    html_part, logo = rich.get_payload()
    assert 'src="cid:logo@coachquest"' in html_part.get_content()
    assert logo.get_content_type() == "image/png" and logo["Content-ID"] == "<logo@coachquest>"
    assert logo.get_payload(decode=True)[:4] == b"\x89PNG"
