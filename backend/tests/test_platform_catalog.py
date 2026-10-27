"""Zwift / MyWhoosh catalog: upload, matching plan days, swapping, and the super admin switch."""

from test_phase3 import HARD, _create, _scheduled, _uid, planner  # noqa: F401  (fixture)

from app import platform_catalog

THRESHOLD_ZWO = """<workout_file>
  <author>Zwift</author><name>Threshold 4x5</name><description>Four at threshold</description>
  <sportType>bike</sportType>
  <workout>
    <Warmup Duration="600" PowerLow="0.5" PowerHigh="0.75"/>
    <IntervalsT Repeat="4" OnDuration="300" OffDuration="300" OnPower="1.04" OffPower="0.5" Cadence="90">
      <textevent timeoffset="0" message="Hold it"/>
    </IntervalsT>
    <Cooldown Duration="600" PowerLow="0.6" PowerHigh="0.4"/>
  </workout>
</workout_file>"""

RECOVERY_ZWO = """<workout_file><name>Easy spin</name><sportType>bike</sportType>
  <workout><SteadyState Duration="2700" Power="0.55"/></workout></workout_file>"""

RUN_ZWO = """<workout_file><name>Run</name><sportType>run</sportType>
  <workout><SteadyState Duration="600" Power="0.8"/></workout></workout_file>"""


def _upload(admin, platform, *files):
    return admin.post(
        "/api/admin/platform-workouts",
        json={"platform": platform, "files": [{"name": f"{i}.zwo", "content": c} for i, c in enumerate(files)]},
    )


def test_parse_zwo():
    w = platform_catalog.parse_zwo(THRESHOLD_ZWO)
    assert w["name"] == "Threshold 4x5" and w["description"] == "Four at threshold"
    assert w["steps"][1] == {
        "kind": "intervals",
        "repeat": 4,
        "on_s": 300,
        "on_power": 1.04,
        "off_s": 300,
        "off_power": 0.5,
        "cadence": 90,
        "text": "Hold it",
    }
    for bad in (RUN_ZWO, "<html/>", "not xml", '<!DOCTYPE x [<!ENTITY a "b">]><workout_file/>'):
        try:
            platform_catalog.parse_zwo(bad)
            raise AssertionError(bad)
        except platform_catalog.ZwoError:
            pass


def test_similar_workouts_score_higher():
    want = platform_catalog.features(HARD)
    same = platform_catalog.features(platform_catalog.parse_zwo(THRESHOLD_ZWO)["steps"])
    easy = platform_catalog.features(platform_catalog.parse_zwo(RECOVERY_ZWO)["steps"])
    assert platform_catalog.score(want, same) >= 90
    assert platform_catalog.score(want, easy) < platform_catalog.MIN_SCORE


def test_upload_list_and_delete(make_user):
    admin = make_user("admin@example.com")
    rider = make_user("rider@example.com")
    r = _upload(admin, "zwift", THRESHOLD_ZWO, RECOVERY_ZWO, RUN_ZWO).json()
    assert r["added"] == 2 and r["updated"] == 0 and r["errors"][0]["file"] == "2.zwo"
    assert _upload(admin, "zwift", THRESHOLD_ZWO).json()["updated"] == 1  # same name replaces
    assert _upload(admin, "rouvy", THRESHOLD_ZWO).status_code == 422
    rows = admin.get("/api/admin/platform-workouts").json()["workouts"]
    assert [w["name"] for w in rows] == ["Easy spin", "Threshold 4x5"]
    assert rider.get("/api/admin/platform-workouts").status_code == 403
    assert _upload(rider, "zwift", THRESHOLD_ZWO).status_code == 403
    assert admin.request("DELETE", f"/api/admin/platform-workouts/{rows[0]['id']}").status_code == 200
    assert len(admin.get("/api/admin/platform-workouts").json()["workouts"]) == 1


def _thursday(plan):
    return next(d for d in plan["weeks"][0]["days"] if d["workout"] and d["workout"]["name"] == "4x5 threshold")


def test_plan_days_show_matches_and_swap(make_user, planner):  # noqa: F811
    admin = make_user("admin@example.com")
    _upload(admin, "zwift", THRESHOLD_ZWO, RECOVERY_ZWO)
    athlete = make_user("rider@example.com")
    plan = _create(athlete)
    url = f"/api/athletes/me/plans/{plan['id']}"
    # No platform chosen yet: nothing to match against.
    plan = athlete.get(url).json()
    pm = plan["platform_matching"]
    assert pm["enabled"] and pm["platforms"] == [] and pm["catalog_size"] == 0 and pm["indoor_days"] == 4
    assert "platform_matches" not in _thursday(plan)

    assert athlete.request("PUT", "/api/me/platforms", json={"preferred": ["zwift"], "auto": {}}).status_code == 200
    plan = athlete.get(url).json()
    pm = plan["platform_matching"]
    assert pm["catalog"] == {"zwift": 2} and pm["platform_names"] == {"zwift": "Zwift"}
    assert pm["matched_days"] == 2  # both threshold days; the tempo days have no close match
    match = _thursday(plan)["platform_matches"][0]
    assert match["name"] == "Threshold 4x5" and match["platform"] == "zwift" and match["score"] >= 90

    day = _thursday(plan)["date"]
    plan = athlete.post(f"{url}/days/{day}/platform-workout", json={"platform_workout_id": match["id"]}).json()
    swapped = _thursday_by_date(plan, day)
    assert swapped["workout"]["name"] == "Threshold 4x5" and swapped["workout"]["platform"]["name"] == "Zwift"
    assert swapped["workout"]["original"]["name"] == "4x5 threshold"
    # Still matched on what the plan asked for.
    assert swapped["platform_matches"][0]["id"] == match["id"]
    # The calendar workout follows (and goes on to the athlete's platforms from there).
    names = {sw.name for sw in _scheduled(_uid(athlete)) if sw.day.isoformat() == day}
    assert names == {"Threshold 4x5"}

    plan = athlete.request("DELETE", f"{url}/days/{day}/platform-workout").json()
    back = _thursday_by_date(plan, day)
    assert back["workout"] == {"name": "4x5 threshold", "steps": HARD} and back["duration_min"] == 60
    assert athlete.request("DELETE", f"{url}/days/{day}/platform-workout").status_code == 400
    names = {sw.name for sw in _scheduled(_uid(athlete)) if sw.day.isoformat() == day}
    assert names == {"4x5 threshold"}


def _thursday_by_date(plan, day):
    return next(d for w in plan["weeks"] for d in w["days"] if d["date"] == day)


def test_super_admin_switch(make_user, planner):  # noqa: F811
    boss = make_user("admin@example.com")
    _upload(boss, "zwift", THRESHOLD_ZWO)
    helper = make_user("helper@example.com")
    hid = helper.get("/api/auth/me").json()["id"]
    boss.patch(f"/api/admin/users/{hid}", json={"is_admin": True})
    off = {"values": {"platform_matching": "off"}}
    assert helper.request("PUT", "/api/admin/settings", json=off).status_code == 403
    assert boss.request("PUT", "/api/admin/settings", json=off).status_code == 200

    athlete = make_user("rider@example.com")
    athlete.request("PUT", "/api/me/platforms", json={"preferred": ["zwift"], "auto": {}})
    plan = _create(athlete)
    url = f"/api/athletes/me/plans/{plan['id']}"
    plan = athlete.get(url).json()
    assert plan["platform_matching"] == {"enabled": False}
    day = _thursday(plan)
    assert "platform_matches" not in day
    wid = boss.get("/api/admin/platform-workouts").json()["workouts"][0]["id"]
    r = athlete.post(f"{url}/days/{day['date']}/platform-workout", json={"platform_workout_id": wid})
    assert r.status_code == 403


def _zip(files: dict[str, str]) -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()


def test_upload_a_zip(make_user):
    import base64

    admin = make_user("admin@example.com")
    data = _zip(
        {
            "Workouts/threshold.zwo": THRESHOLD_ZWO,
            "Workouts/easy.zwo": RECOVERY_ZWO,
            "Workouts/run.zwo": RUN_ZWO,
            "__MACOSX/Workouts/._easy.zwo": "junk",
            "readme.txt": "not a workout",
        }
    )
    r = admin.post(
        "/api/admin/platform-workouts",
        json={
            "platform": "zwift",
            "files": [{"name": "legacy.zip", "content": base64.b64encode(data).decode(), "base64": True}],
        },
    ).json()
    assert r["added"] == 2 and r["error_count"] == 1 and r["errors"][0]["file"] == "Workouts/run.zwo"
    bad = {"platform": "zwift", "files": [{"name": "x.zip", "content": "!!!", "base64": True}]}
    assert admin.post("/api/admin/platform-workouts", json=bad).status_code == 422
    empty = base64.b64encode(_zip({"a.txt": "x"})).decode()
    r = admin.post(
        "/api/admin/platform-workouts",
        json={"platform": "zwift", "files": [{"name": "e.zip", "content": empty, "base64": True}]},
    )
    assert r.json()["errors"] == [{"file": "e.zip", "error": "The .zip has no .zwo files"}]


def test_import_from_a_link(make_user, monkeypatch):
    admin = make_user("admin@example.com")
    rider = make_user("rider@example.com")
    asked = []

    def fake_download(url):
        asked.append(url)
        return "legacy.zip", _zip({"threshold.zwo": THRESHOLD_ZWO})

    monkeypatch.setattr(platform_catalog, "download", fake_download)
    body = {"platform": "mywhoosh", "url": "https://example.com/legacy.zip"}
    r = admin.post("/api/admin/platform-workouts/import-url", json=body).json()
    assert r["added"] == 1 and asked == ["https://example.com/legacy.zip"]
    assert admin.get("/api/admin/platform-workouts").json()["workouts"][0]["platform"] == "mywhoosh"
    assert rider.post("/api/admin/platform-workouts/import-url", json=body).status_code == 403


def test_links_must_be_public_web_files():
    import pytest

    for url in ("ftp://example.com/a.zwo", "file:///etc/passwd", "http://127.0.0.1/a.zwo", "http://10.0.0.5/a.zip"):
        with pytest.raises(platform_catalog.ZwoError):
            platform_catalog.download(url)
