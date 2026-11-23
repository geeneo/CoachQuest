"""Official results pasted in (race_results.py): parsing, finding the athlete, placing them."""

from app import race_results as rr
from app.db import SessionLocal
from tests.test_race_review import RACE_DAY, _ride, racer  # noqa: F401 (the fixture)

COPIED = """Pos\tBib\tName\tCategory\tGun time\tNet time
1\t101\tPieter van Wyk\tM40\t2:01:10\t2:01:05
2\t205\tAnna Smit\tW30\t2:03:00\t2:02:58
3\t340\tRider\tM40\t2:09:35\t2:09:30
4\t411\tJohan Botha\tM40\t2:15:00\t2:14:50
DNF\t512\tSam Jones\tM50\t\t
"""

CSV = """Place,First Name,Last Name,Age Group,Finish Time
2,Anna,Smit,W30,2:02:58
1,Pieter,van Wyk,M40,2:01:05
3,Michael,Nel,M40,2:09:30
"""

PLAIN = """1   Pieter van Wyk     M40   2:01:05
2   Anna Smit          W30   2:02:58
3   Michael Nel        M40   2:09:30"""


def test_copied_table_net_time_and_unfinished_last():
    rows = rr.parse(COPIED)
    assert [r["name"] for r in rows] == ["Pieter van Wyk", "Anna Smit", "Rider", "Johan Botha", "Sam Jones"]
    assert rows[0]["time_s"] == 7265 and rows[0]["category"] == "M40"  # net time, not gun
    assert rows[-1]["time_s"] is None  # DNF: kept, last


def test_csv_first_and_last_names_sorted_by_time():
    rows = rr.parse(CSV)
    assert [r["name"] for r in rows] == ["Pieter van Wyk", "Anna Smit", "Michael Nel"]
    assert rows[2]["category"] == "M40"


def test_no_header_read_by_the_look_of_cells():
    rows = rr.parse(PLAIN)
    assert rows[2] == {"pos": 3, "name": "Michael Nel", "category": None, "time_s": 7770}


def test_find_me_and_my_place():
    rows = rr.parse(COPIED)
    assert rr.find_me(rows, "Rider", None, None) == 2
    assert rr.find_me(rows, "Someone Else", 7771, None) == 2  # by official time, 1 s off
    assert rr.find_me(rows, "Someone Else", None, 7800) == 2  # by the ride's elapsed time, 30 s off
    assert rr.find_me(rows, "Someone Else", None, None) is None
    s = rr.summary({"rows": rows, "me": 2})
    assert (s["position"], s["field"], s["entries"]) == (3, 4, 5)
    assert (s["category"], s["category_position"], s["category_size"]) == ("M40", 2, 3)
    assert s["gap_to_winner_s"] == 505 and s["gap_to_category_winner_s"] == 505
    around = {r["name"]: r["gap_s"] for r in s["around"]}
    assert around["Pieter van Wyk"] == -505 and around["Johan Botha"] == 320 and around["Sam Jones"] is None


def test_import_fills_the_post_race_update(racer):  # noqa: F811
    p, uid, rid = racer
    with SessionLocal() as db:
        db.add(_ride(uid, "me", RACE_DAY))
        db.commit()
    p.request("PUT", f"/api/races/{rid}/result", json={"position": 99})  # already given: kept
    r = p.request("PUT", f"/api/races/{rid}/results", json={"text": COPIED})
    assert r.status_code == 200, r.text
    assert r.json()["position"] == 3
    d = p.get(f"/api/athletes/me/races/{rid}/review").json()
    assert d["result"]["position"] == 99 and d["result"]["field_size"] == 4 and d["result"]["category"] == "M40"
    assert d["result"]["official_time"] == "2:09:30"
    assert "results" not in d["result"] and d["results"]["category_position"] == 2  # the list stays out
    # Not found by name: point at one's own line.
    hits = p.get(f"/api/races/{rid}/results/search?q=botha").json()
    assert hits == [{"index": 3, "name": "Johan Botha", "category": "M40", "time": "2:14:50"}]
    me = p.request("PUT", f"/api/races/{rid}/results/me", json={"index": 3}).json()
    assert me["position"] == 4
    assert p.request("PUT", f"/api/races/{rid}/results", json={"text": "nothing useful here"}).status_code == 422
    assert p.request("DELETE", f"/api/races/{rid}/results").status_code == 200
    assert p.get(f"/api/athletes/me/races/{rid}/review").json()["results"] is None
