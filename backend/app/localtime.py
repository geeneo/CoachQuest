"""The athlete's own calendar. Times are stored in UTC; days are the athlete's local days."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name) if name else ZoneInfo("UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def valid(name: str) -> bool:
    try:
        ZoneInfo(name)
        return "/" in name or name == "UTC"
    except (ZoneInfoNotFoundError, ValueError):
        return False


def today(user, now: datetime | None = None) -> date:
    """Today where the athlete is. `now` is an aware datetime (tests)."""
    return (now or datetime.now(UTC)).astimezone(zone(user.timezone)).date()


def local_date(utc_naive: datetime, tz: ZoneInfo) -> date:
    """The local day of a stored (naive UTC) time, e.g. a 23:30 UTC ride is the next day in Johannesburg."""
    return utc_naive.replace(tzinfo=UTC).astimezone(tz).date()
