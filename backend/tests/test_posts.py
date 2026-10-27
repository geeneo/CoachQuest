"""News & guides: admins write and publish, everyone signed in reads what's published."""

from app import posts_seed
from app.db import Post, SessionLocal


def test_drafts_are_seeded_once(make_user):
    admin = make_user("admin@example.com")
    rider = make_user("rider@example.com")
    listing = admin.get("/api/posts").json()
    assert len(listing["guides"]) == len(posts_seed.GUIDES) and len(listing["news"]) == 1
    assert not any(p["published"] for p in listing["guides"] + listing["news"])  # drafts
    assert listing["can_edit"] is True
    # Riders don't see drafts, even by id.
    assert rider.get("/api/posts").json() == {"news": [], "guides": [], "can_edit": False}
    assert rider.get(f"/api/posts/{listing['guides'][0]['id']}").status_code == 404
    with SessionLocal() as db:
        posts_seed.seed(db)  # posts exist: nothing added
        assert db.query(Post).count() == len(posts_seed.GUIDES) + 1


def test_admin_writes_and_publishes(make_user):
    admin = make_user("admin@example.com")
    rider = make_user("rider@example.com")
    body = {"kind": "news", "title": "New: dark mode", "summary": "Top right.", "body_md": "## Hi\n\nText"}
    p = admin.post("/api/posts", json=body).json()
    assert p["published"] is False and p["published_at"] is None and p["author"] == "User"
    assert rider.post("/api/posts", json=body).status_code == 403
    p = admin.request("PUT", f"/api/posts/{p['id']}", json={**body, "published": True}).json()
    assert p["published"] and p["published_at"]
    news = rider.get("/api/posts?kind=news").json()["news"]
    assert [n["title"] for n in news] == ["New: dark mode"] and "body_md" not in news[0]
    assert rider.get(f"/api/posts/{p['id']}").json()["body_md"] == "## Hi\n\nText"
    assert rider.request("PUT", f"/api/posts/{p['id']}", json=body).status_code == 403
    assert rider.request("DELETE", f"/api/posts/{p['id']}").status_code == 403
    assert admin.post("/api/posts", json={**body, "kind": "blog"}).status_code == 422
    assert admin.request("DELETE", f"/api/posts/{p['id']}").status_code == 200
    assert rider.get(f"/api/posts/{p['id']}").status_code == 404


def test_guides_follow_their_position(make_user):
    admin = make_user("admin@example.com")
    for title, pos in (("B", 20), ("A", 30), ("C", 5)):
        admin.post("/api/posts", json={"kind": "guide", "title": title, "position": pos, "published": True})
    rider = make_user("rider@example.com")
    assert [g["title"] for g in rider.get("/api/posts").json()["guides"]] == ["C", "B", "A"]
