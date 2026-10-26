from test_phase3 import _scheduled
from test_plan_approval import _create, team  # noqa: F401  (fixture)


def test_coach_switches_approval_off(team, make_user):  # noqa: F811
    athlete, cobus, aid, _ = team
    p = _create(athlete)
    assert p["approval"] == "awaiting" and p["can_approve"] is False
    url = f"/api/athletes/{aid}/plans/approval-setting"
    assert athlete.get("/api/athletes/me/plans/approval-setting").json() == {
        "required": True,
        "off": False,
        "has_coach": True,
        "can_change": False,
    }
    assert (
        athlete.request("PUT", "/api/athletes/me/plans/approval-setting", json={"required": False}).status_code == 403
    )
    assert cobus.request("PUT", url, json={"required": False}).json() == {"required": False, "off": True}
    # The athlete can now approve what was waiting, and new plans apply at once.
    plan_url = f"/api/athletes/me/plans/{p['id']}"
    assert athlete.get(plan_url).json()["can_approve"] is True
    assert athlete.post(f"{plan_url}/approve").json()["approval"] == "approved"
    assert len(_scheduled(aid)) == 4
    q = _create(athlete)
    assert q["approval"] == "approved"
    cobus.request("PUT", url, json={"required": True})
    assert _create(athlete)["approval"] == "awaiting"


def test_admin_switches_approval_off(team, make_user):  # noqa: F811
    athlete, cobus, aid, _ = team
    admin = make_user("admin@example.com")
    admin.request("PATCH", f"/api/admin/users/{aid}", json={"plan_approval_off": True})
    assert _create(athlete)["approval"] == "approved"
    row = next(u for u in admin.get("/api/admin/users").json() if u["id"] == aid)
    assert row["plan_approval_off"] is True
