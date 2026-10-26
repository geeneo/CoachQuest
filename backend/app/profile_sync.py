"""Profile thresholds (FTP, lactate threshold HR, max HR) and birth date from a provider.

A provider value is applied when it is new: different from the last value
seen from that provider. So a number the athlete typed in stays until the
provider reports a change, and an unchanged provider value never overwrites
a manual edit.
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .db import Activity, User, utcnow
from .fitness import estimate_tss

THRESHOLDS = ("ftp_watts", "lthr_bpm", "max_hr_bpm")
FIELDS = (*THRESHOLDS, "birth_date")


def age(birth_date: date | None, today: date | None = None) -> int | None:
    if birth_date is None:
        return None
    today = today or date.today()
    return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))


def recalculate_tss(db: DbSession, user: User) -> None:
    """FTP or LTHR changed, so every activity's TSS changes too (hidden sources included)."""
    for a in db.scalars(select(Activity).where(Activity.user_id == user.id)):
        a.tss, a.tss_method = estimate_tss(
            a.duration_s, a.norm_power, a.avg_power, a.avg_hr, a.relative_effort, user.ftp_watts, user.lthr_bpm
        )


def mark_manual(user: User, fields) -> None:
    sources = dict(user.profile_sources or {})
    for field in fields:
        if field in FIELDS:
            sources[field] = {**sources.get(field, {}), "source": "manual", "at": utcnow().isoformat()}
    user.profile_sources = sources


def apply_from_provider(db: DbSession, user: User, provider: str, values: dict, force: bool = False) -> list[str]:
    """Apply new provider values; returns the fields that changed. `force` applies unchanged values too."""
    sources = dict(user.profile_sources or {})
    changed = []
    for field, value in values.items():
        if field not in FIELDS or value is None:
            continue
        info = sources.get(field, {})
        seen = value.isoformat() if isinstance(value, date) else value  # stored as JSON
        if seen == info.get(f"{provider}_seen") and not force:
            continue  # nothing new from the provider
        sources[field] = {**info, "source": provider, "at": utcnow().isoformat(), f"{provider}_seen": seen}
        if getattr(user, field) != value:
            setattr(user, field, value)
            changed.append(field)
    user.profile_sources = sources
    if {"ftp_watts", "lthr_bpm"} & set(changed):
        recalculate_tss(db, user)
    return changed
