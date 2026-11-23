"""A race's official results, pasted in: a CSV download, or a table copied from the results website.

Each line is split on tabs (a copied table), else on the CSV's separator (comma or semicolon), else on runs
of two or more spaces. A header line, when there is one, names the columns: position, name (or first and
last name), category, and the time (finish, net or chip time before gun time). Without a header, each cell
is read by its look: the first whole number is the position, the last h:mm:ss the time, and the longest
text the name. Rows without a time (DNF, DNS) are kept at the end without one.

The athlete is found by their name, else by their official time (within 2 seconds), else by their ride's
elapsed time (within a minute); the athlete can also point at their own line. Then: their position overall
and in their category (counted from the results), the gap to the winner, and the riders around them. Kept
with the race (Race.result["results"]).
"""

import csv
import io
import re
import unicodedata

from .race_estimate import format_time

MAX_ROWS = 20000
AROUND = 5  # riders shown above and below the athlete
TIME_RE = re.compile(r"^(\d{1,3}):([0-5]\d)(?::([0-5]\d))?(?:[.,]\d+)?$")
POS_HEADERS = ("pos", "position", "place", "rank", "overall", "plc", "#", "no")
NAME_HEADERS = ("name", "rider", "athlete", "participant", "full name", "naam")
FIRST_HEADERS = ("first name", "firstname", "first", "voornaam", "name first")
LAST_HEADERS = ("last name", "lastname", "surname", "last", "van", "name last")
CAT_HEADERS = ("category", "cat", "age group", "agegroup", "division", "class", "group", "kategorie")
TIME_HEADERS = ("net time", "nett time", "chip time", "finish time", "time", "net", "chip", "finish", "result")
GUN_HEADERS = ("gun time", "gun", "official time")


class ResultsError(ValueError):
    pass


def parse_time(cell: str) -> int | None:
    m = TIME_RE.match(cell.strip())
    if not m:
        return None
    a, b, c = m.groups()
    return int(a) * 3600 + int(b) * 60 + int(c) if c is not None else int(a) * 60 + int(b)


def _split(lines: list[str]) -> list[list[str]]:
    sample = lines[: min(len(lines), 20)]
    if sum("\t" in ln for ln in sample) >= len(sample) / 2:
        return [[c.strip() for c in ln.split("\t")] for ln in lines]
    for sep in (",", ";"):
        if sum(ln.count(sep) >= 2 for ln in sample) >= len(sample) / 2:
            return [[c.strip() for c in row] for row in csv.reader(io.StringIO("\n".join(lines)), delimiter=sep)]
    return [[c.strip() for c in re.split(r"\s{2,}", ln.strip())] for ln in lines]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", " ", s.lower()).strip()


def _header_index(cells: list[str], names: tuple) -> int | None:
    low = [_norm(c) for c in cells]
    for n in names:  # in order of preference
        for i, c in enumerate(low):
            if c == n:
                return i
    for n in names:
        for i, c in enumerate(low):
            if len(n) > 2 and n in c:
                return i
    return None


def _is_header(cells: list[str]) -> bool:
    if any(parse_time(c) for c in cells):
        return False
    low = " ".join(_norm(c) for c in cells)
    return any(w in low.split() or w in low for w in ("name", "time", "pos", "place", "category", "surname"))


def parse(text: str) -> list[dict]:
    """Results rows: {pos, name, category, time_s}, in finishing order (by time; no time last)."""
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        raise ResultsError("Paste the results first")
    if len(lines) > MAX_ROWS + 1:
        raise ResultsError(f"That's more than {MAX_ROWS} results; paste the part around your result")
    rows = _split(lines)
    head = rows[0] if _is_header(rows[0]) else None
    body = rows[1:] if head else rows
    idx = {}
    if head:
        idx = {
            "pos": _header_index(head, POS_HEADERS),
            "name": _header_index(head, NAME_HEADERS),
            "first": _header_index(head, FIRST_HEADERS),
            "last": _header_index(head, LAST_HEADERS),
            "cat": _header_index(head, CAT_HEADERS),
            "time": _header_index(head, TIME_HEADERS),
            "gun": _header_index(head, GUN_HEADERS),
        }
        if idx["name"] in (idx["first"], idx["last"]):
            idx["name"] = None

    def cell(r, i):
        return r[i] if i is not None and i < len(r) else ""

    out = []
    for r in body:
        if not any(r):
            continue
        times = [(i, parse_time(c)) for i, c in enumerate(r) if parse_time(c)]
        if idx.get("time") is not None and parse_time(cell(r, idx["time"])):
            t = parse_time(cell(r, idx["time"]))
        elif idx.get("gun") is not None and parse_time(cell(r, idx["gun"])):
            t = parse_time(cell(r, idx["gun"]))
        else:
            t = times[-1][1] if times else None
        pos_txt = cell(r, idx.get("pos")) if idx.get("pos") is not None else ""
        if not pos_txt.strip().rstrip(".").isdigit():
            pos_txt = next((c for c in r if c.strip().rstrip(".").isdigit()), "")
        pos = int(pos_txt.strip().rstrip(".")) if pos_txt.strip().rstrip(".").isdigit() else None
        if idx.get("first") is not None or idx.get("last") is not None:
            name = " ".join(x for x in (cell(r, idx.get("first")), cell(r, idx.get("last"))) if x)
        elif idx.get("name") is not None:
            name = cell(r, idx["name"])
        else:
            words = [c for c in r if c and not parse_time(c) and not c.rstrip(".").isdigit()]
            name = max(words, key=len) if words else ""
        cat = cell(r, idx.get("cat")) if idx.get("cat") is not None else ""
        if not name and t is None:
            continue
        out.append({"pos": pos, "name": name[:80], "category": cat[:40] or None, "time_s": t})
    if not any(r["time_s"] for r in out):
        raise ResultsError("No results found in that: paste the table with names and times (h:mm:ss)")
    out.sort(key=lambda x: (x["time_s"] is None, x["time_s"] or 0, x["pos"] or 0))
    return out


def find_me(rows: list[dict], name: str, official_s: int | None, elapsed_s: int | None) -> int | None:
    """The athlete's line: by name (all of their name's words in the line, or the line's in theirs), else
    by official time (2 s), else by the ride's elapsed time (a minute)."""
    mine = set(_norm(name).split())
    if mine:
        for i, r in enumerate(rows):
            theirs = set(_norm(r["name"]).split())
            if theirs and (mine <= theirs or (len(theirs) >= 2 and theirs <= mine)):
                return i
    for target, slack in ((official_s, 2), (elapsed_s, 60)):
        if target:
            near = [(abs(r["time_s"] - target), i) for i, r in enumerate(rows) if r["time_s"]]
            if near and min(near)[0] <= slack:
                return min(near)[1]
    return None


def summary(stored: dict | None) -> dict | None:
    """The athlete's place in the results, for the review."""
    if not stored or not stored.get("rows"):
        return None
    rows = stored["rows"]
    timed = [r for r in rows if r["time_s"]]
    me = stored.get("me")
    out = {"field": len(timed), "entries": len(rows), "imported_at": stored.get("imported_at"), "me": me}
    if timed:
        out["winner"] = {"name": timed[0]["name"], "time": format_time(timed[0]["time_s"])}
    if me is None or me >= len(rows):
        out["around"] = [_row(i, r, None, None) for i, r in enumerate(rows[: 2 * AROUND + 1])]
        return out
    my = rows[me]
    place = sum(1 for r in timed if r["time_s"] < (my["time_s"] or 0)) + 1 if my["time_s"] else None
    cat = my.get("category")
    in_cat = [r for r in timed if cat and r.get("category") == cat]
    out.update(
        {
            "position": place,
            "time": format_time(my["time_s"]),
            "time_s": my["time_s"],
            "category": cat,
            "category_position": (sum(1 for r in in_cat if r["time_s"] < my["time_s"]) + 1)
            if cat and my["time_s"]
            else None,
            "category_size": len(in_cat) if cat else None,
            "gap_to_winner_s": my["time_s"] - timed[0]["time_s"] if my["time_s"] and timed else None,
            "gap_to_category_winner_s": my["time_s"] - in_cat[0]["time_s"] if in_cat and my["time_s"] else None,
            "percentile": round(100 * (place - 1) / max(1, len(timed) - 1)) if place else None,
        }
    )
    lo, hi = max(0, me - AROUND), min(len(rows), me + AROUND + 1)
    out["around"] = [_row(i, rows[i], my["time_s"], me) for i in range(lo, hi)]
    return out


def _row(i: int, r: dict, mine: int | None, me: int | None) -> dict:
    return {
        "index": i,
        "place": i + 1 if r["time_s"] else None,
        "name": r["name"],
        "category": r.get("category"),
        "time": format_time(r["time_s"]),
        "gap_s": r["time_s"] - mine if mine and r["time_s"] else None,
        "me": i == me,
    }
