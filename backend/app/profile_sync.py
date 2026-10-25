"""Profile thresholds (FTP, lactate threshold HR, max HR) from a provider.

A provider value is applied when it is new: different from the last value
seen from that provider. So a number the athlete typed in stays until the
provider reports a change, and an unchanged provider value never overwrites
a manual edit.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .db import Activity, User, utcnow
from .fitness import estimate_tss

THRESHOLDS = ("ftp_watts", "lthr_bpm", "max_hr_bpm")


def recalculate_tss(db: DbSession, user: User) -> None:
    """FTP or LTHR changed, so every activity's TSS changes too (hidden sources included)."""
    for a in db.scalars(select(Activity).where(Activity.user_id == user.id)):
        a.tss, a.tss_method = estimate_tss(
            a.duration_s, a.norm_power, a.avg_power, a.avg_hr, a.relative_effort, user.ftp_watts, user.lthr_bpm
        )


def mark_manual(user: User, fields) -> None:
    sources = dict(user.profile_sources or {})
    for field in fields:
        if field in THRESHOLDS:
            sources[field] = {**sources.get(field, {}), "source": "manual", "at": utcnow().isoformat()}
    user.profile_sources = sources


def apply_from_provider(db: DbSession, user: User, provider: str, values: dict) -> list[str]:
    """Apply new provider values; returns the fields that changed."""
    sources = dict(user.profile_sources or {})
    changed = []
    for field, value in values.items():
        if field not in THRESHOLDS or value is None:
            continue
        info = sources.get(field, {})
        if value == info.get(f"{provider}_seen"):
            continue  # nothing new from the provider
        sources[field] = {**info, "source": provider, "at": utcnow().isoformat(), f"{provider}_seen": value}
        if getattr(user, field) != value:
            setattr(user, field, value)
            changed.append(field)
    user.profile_sources = sources
    if {"ftp_watts", "lthr_bpm"} & set(changed):
        recalculate_tss(db, user)
    return changed
