"""The user's date and time format (Profile → Date format), for emails and the AI coach.

The web pages format dates in the browser (frontend/src/lib/format.js) with the
same choices; keep the two in step.
"""

from datetime import date

DATE_FORMATS = ("d_mon_y", "iso", "dmy", "mdy")  # 26 Oct 2026 · 2026-10-26 · 26/10/2026 · 10/26/2026
TIME_FORMATS = ("24h", "12h")
DEFAULT_DATE, DEFAULT_TIME = "d_mon_y", "24h"


def date_format(user) -> str:
    f = getattr(user, "date_format", None)
    return f if f in DATE_FORMATS else DEFAULT_DATE


def day(d: date, user, weekday: bool = False) -> str:
    """A calendar date, e.g. "Mon 26 Oct 2026" / "Mon 2026-10-26"."""
    f = date_format(user)
    text = {
        "d_mon_y": f"{d.day} {d:%b %Y}",
        "iso": d.isoformat(),
        "dmy": f"{d:%d/%m/%Y}",
        "mdy": f"{d:%m/%d/%Y}",
    }[f]
    return f"{d:%a} {text}" if weekday else text


def time_format(user) -> str:
    f = getattr(user, "time_format", None)
    return f if f in TIME_FORMATS else DEFAULT_TIME


def ai_instruction(user) -> str:
    """One line for the AI coach's instructions so its notes use the reader's format."""
    clock = "24-hour (e.g. 17:30)" if time_format(user) == "24h" else "12-hour (e.g. 5:30 pm)"
    example = day(date(2026, 10, 26), user, weekday=True)
    return f"Write dates for the reader like {example!r} and times in {clock}."
