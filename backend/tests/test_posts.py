"""News & guides: admins write and publish, everyone signed in reads what's published."""

from app import posts_seed
from app.db import AppSetting, Post, SessionLocal


def test_shipped_posts_are_added_once(make_user):
    admin = make_user("admin@example.com")
    rider = make_user("rider@example.com")
    listing = admin.get("/api/posts").json()
    assert len(listing["guides"]) == 7 and len(listing["news"]) == 3  # a fresh install gets them all
    drafts = [p["title"] for p in listing["guides"] + listing["news"] if not p["published"]]
    assert len(drafts) == len(posts_seed.FIRST_BATCH)  # the first batch waits for the admin
    assert listing["can_edit"] is True
    # Riders see only what's published (the later guides and news), not the drafts (even by id).
    seen = rider.get("/api/posts").json()
    assert [g["title"] for g in seen["guides"]] == [
        posts_seed.ZWIFT_GUIDE[0],
        posts_seed.ROUTES_GUIDE[0],
        posts_seed.STRENGTH_GUIDE[0],
    ]
    assert {n["title"] for n in seen["news"]} == {posts_seed.ROUTES_NEWS[0], posts_seed.STRENGTH_NEWS[0]}
    draft = next(p for p in listing["guides"] if not p["published"])
    assert rider.get(f"/api/posts/{draft['id']}").status_code == 404
    with SessionLocal() as db:
        posts_seed.seed(db)  # all added already: nothing new
        assert db.query(Post).count() == len(posts_seed.POSTS)


def test_an_existing_install_gets_only_the_new_posts(make_user):
    admin = make_user("admin@example.com")
    with SessionLocal() as db:
        # Like a server that had the first batch before keys were remembered, and deleted one guide.
        db.query(Post).delete()
        db.query(AppSetting).filter_by(key=posts_seed.SEEDED).delete()
        db.add(Post(kind="guide", title="Getting started (edited)", body_md="x"))
        db.commit()
        posts_seed.seed(db)
        titles = {p.title for p in db.query(Post)}
        shipped_later = {posts_seed.ROUTES_GUIDE[0], posts_seed.ROUTES_NEWS[0]}
        shipped_later |= {posts_seed.STRENGTH_GUIDE[0], posts_seed.STRENGTH_NEWS[0], posts_seed.ZWIFT_GUIDE[0]}
        assert titles == {"Getting started (edited)"} | shipped_later
        # Deleting a shipped post doesn't bring it back.
        db.query(Post).filter_by(title=posts_seed.ROUTES_NEWS[0]).delete()
        db.commit()
        posts_seed.seed(db)
        assert db.query(Post).filter_by(title=posts_seed.ROUTES_NEWS[0]).count() == 0
    assert admin.get("/api/posts").status_code == 200


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
    mine = [n for n in news if n["title"] == "New: dark mode"]
    assert len(mine) == 1 and "body_md" not in mine[0]
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
    titles = [g["title"] for g in rider.get("/api/posts").json()["guides"]]
    assert [t for t in titles if t in "ABC"] == ["C", "B", "A"]
