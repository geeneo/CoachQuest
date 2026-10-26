from datetime import date

from app import datefmt


class U:
    def __init__(self, date_format=None, time_format=None):
        self.date_format, self.time_format = date_format, time_format


D = date(2026, 3, 5)


def test_formats():
    assert datefmt.day(D, U()) == "5 Mar 2026"
    assert datefmt.day(D, U("iso"), weekday=True) == "Thu 2026-03-05"
    assert datefmt.day(D, U("dmy")) == "05/03/2026"
    assert datefmt.day(D, U("mdy")) == "03/05/2026"
    assert datefmt.day(D, U("nonsense")) == "5 Mar 2026"
    assert "12-hour" in datefmt.ai_instruction(U("mdy", "12h")) and "10/26/2026" in datefmt.ai_instruction(U("mdy"))


def test_profile_setting(make_user):
    p = make_user("rider@example.com")
    me = p.get("/api/auth/me").json()
    assert (me["date_format"], me["time_format"]) == ("d_mon_y", "24h")
    r = p.request("PATCH", "/api/me", json={"date_format": "iso", "time_format": "12h"})
    assert r.status_code == 200 and r.json()["date_format"] == "iso" and r.json()["time_format"] == "12h"
    assert p.request("PATCH", "/api/me", json={"date_format": "yyyy"}).status_code == 422
    assert p.request("PATCH", "/api/me", json={"time_format": "36h"}).status_code == 422
