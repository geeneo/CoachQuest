"""The information page: off until an admin switches it on, only through its private link, noindex."""

import base64

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64).decode()


def test_private_link_on_off_and_new_link(client, make_user):
    boss = make_user("admin@example.com")
    page = boss.get("/api/admin/welcome").json()
    assert page["enabled"] is False and "/welcome/" in page["link"] and "## How it works" in page["body_md"]
    key = page["key"]
    assert client.get(f"/api/welcome/{key}").status_code == 404  # off by default
    boss.request("PUT", "/api/admin/welcome", json={"enabled": True, "title": "Meet CoachQuest"})
    r = client.get(f"/api/welcome/{key}")  # no sign-in needed
    assert r.status_code == 200 and r.json()["title"] == "Meet CoachQuest" and r.json()["signup"] is True
    bad = client.get("/api/welcome/guess")
    assert bad.status_code == 404 and "noindex" in bad.headers["x-robots-tag"]
    # A new link: the old one stops working.
    new = boss.post("/api/admin/welcome/new-link").json()["key"]
    assert new != key and client.get(f"/api/welcome/{key}").status_code == 404
    assert client.get(f"/api/welcome/{new}").status_code == 200


def test_screenshots_and_admins_only(client, make_user):
    boss = make_user("admin@example.com")
    rider = make_user("rider@example.com")
    assert rider.get("/api/admin/welcome").status_code == 403
    assert (
        boss.post("/api/admin/welcome/images", json={"data_b64": base64.b64encode(b"<svg/>").decode()}).status_code
        == 422
    )
    r = boss.post("/api/admin/welcome/images", json={"data_b64": PNG}).json()
    name = r["added"]
    assert name.endswith(".png") and name in r["images"]
    page = boss.request("PUT", "/api/admin/welcome", json={"enabled": True}).json()
    img = client.get(f"/api/welcome/{page['key']}/img/{name}")
    assert img.status_code == 200 and img.content.startswith(b"\x89PNG")
    assert client.get(f"/api/welcome/wrong/img/{name}").status_code == 404
    assert client.get(f"/api/welcome/{page['key']}/img/..%2F..%2Fsecret.png").status_code == 404
    assert name not in boss.delete(f"/api/admin/welcome/images/{name}").json()["images"]
