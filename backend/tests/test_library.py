"""CoachQuest's workout library: valid workouts, open to every user, schedulable and downloadable."""

from app import library, workouts


def test_library_is_valid_and_varied():
    assert len(library.LIBRARY) >= 80
    assert {w["collection"] for w in library.LIBRARY} == set(library.COLLECTION_NAMES)
    for w in library.LIBRARY:
        assert w["description"] and w["instructions"], w["slug"]
        assert workouts.validate_steps(w["steps"]) == w["steps"]
        minutes = workouts.duration(w["steps"]) / 60
        assert 15 <= minutes <= 130, w["slug"]
    short = [w for w in library.LIBRARY if w["collection"] == "short"]
    assert all(workouts.duration(w["steps"]) <= 45 * 60 for w in short)


def test_every_user_can_browse_it(make_user):
    make_user("admin@example.com")
    rider = make_user("rider@example.com")
    body = rider.get("/api/library").json()
    assert len(body["workouts"]) == len(library.LIBRARY)
    assert [c["key"] for c in body["collections"]] == [k for k, _, _ in library.COLLECTIONS]
    first = body["workouts"][0]
    assert first["blocks"] and first["estimate"]["duration_s"] and "steps" not in first
    detail = rider.get(f"/api/library/{first['slug']}").json()
    assert detail["steps"] and detail["name"] == first["name"]
    assert rider.get("/api/library/nope").status_code == 404


def test_schedule_save_and_download(make_user):
    rider = make_user("rider@example.com")
    w = rider.get("/api/library/sweetspot-2x20").json()
    r = rider.post(
        "/api/athletes/me/workouts",
        json={
            "day": "2026-11-02",
            "name": w["name"],
            "description": w["description"],
            "instructions": w["instructions"],
            "steps": w["steps"],
        },
    )
    assert r.status_code == 200 and r.json()["name"] == "Sweet spot 2 × 20 min"
    saved = rider.post(
        "/api/workouts",
        json={
            "name": w["name"],
            "description": w["description"],
            "instructions": w["instructions"],
            "steps": w["steps"],
        },
    )
    assert saved.status_code == 200
    assert [x["name"] for x in rider.get("/api/workouts").json()] == ["Sweet spot 2 × 20 min"]
    z = rider.get("/api/library/sweetspot-2x20/zwo")
    assert z.status_code == 200 and "<workout_file>" in z.text and "Sweet spot 2" in z.text
    assert 'filename="Sweet spot 2 x 20 min.zwo"' in z.headers["content-disposition"]
