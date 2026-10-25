from test_mail import _configure, fake_smtp  # noqa: F401  (fixture)


def _sent_to(fake_smtp):  # noqa: F811
    return [(c[1], c[2]) for call in fake_smtp for c in call if c[0] == "send"]


def test_sharing_emails(make_user, fake_smtp):  # noqa: F811
    admin = make_user("admin@example.com")
    _configure(admin)
    athlete = make_user("a@example.com", "Ann")
    coach = make_user("c@example.com", "Cobus")

    g = athlete.post("/api/grants", json={"coach_email": "c@example.com", "scopes": ["activities"]}).json()
    assert ("c@example.com", "CoachQuest: Ann invited you as their coach") in _sent_to(fake_smtp)

    coach.post(f"/api/grants/{g['id']}/accept")
    assert ("a@example.com", "CoachQuest: Cobus accepted your invitation") in _sent_to(fake_smtp)

    athlete.patch(f"/api/grants/{g['id']}", json={"scopes": ["activities", "wellness"]})
    assert ("c@example.com", "CoachQuest: Ann changed what they share with you") in _sent_to(fake_smtp)

    coach.delete(f"/api/grants/{g['id']}")
    assert ("a@example.com", "CoachQuest: Cobus is no longer your coach") in _sent_to(fake_smtp)


def test_opt_out_and_no_smtp(make_user, fake_smtp):  # noqa: F811
    athlete = make_user("a@example.com", "Ann")
    make_user("c@example.com", "Cobus")
    athlete.post("/api/grants", json={"coach_email": "c@example.com", "scopes": ["activities"]})
    assert _sent_to(fake_smtp) == []  # email not set up: nothing sent, no error

    admin = make_user("admin@example.com")
    _configure(admin)
    coach2 = make_user("d@example.com", "Dirk")
    coach2.patch("/api/me", json={"notify_sharing": False})
    athlete.post("/api/grants", json={"coach_email": "d@example.com", "scopes": ["activities"]})
    assert all(to != "d@example.com" for to, _ in _sent_to(fake_smtp))
