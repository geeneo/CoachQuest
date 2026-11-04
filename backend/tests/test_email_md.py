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
