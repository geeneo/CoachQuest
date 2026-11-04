"""Profile thresholds (FTP, lactate threshold HR, max HR) and birth date from a provider.

A provider value is applied when it is new: different from the last value
seen from that provider. So a number the athlete typed in stays until the
provider reports a change, and an unchanged provider value never overwrites
a manual edit.
"""

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import localtime
from .db import Activity, AppSetting, User, utcnow
from .fitness import THRESHOLD_FIELDS, TSS_VERSION, rescore, threshold_at
from .security import decrypt_json, encrypt_json

log = logging.getLogger("coachquest.profile_sync")

THRESHOLDS = ("ftp_watts", "lthr_bpm", "max_hr_bpm")
FIELDS = (*THRESHOLDS, "birth_date")


def age(birth_date: date | None, today: date | None = None) -> int | None:
    if birth_date is None:
        return None
    today = today or date.today()
    return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))


def recalculate_tss(db: DbSession, user: User) -> None:
    """Thresholds changed: score every activity again (hidden sources included), each with the thresholds
    of its own date, so workouts before a change keep their TSS."""
    for a in db.scalars(select(Activity).where(Activity.user_id == user.id)):
        rescore(a, user)


def record_change(user: User, field: str, old, new, day: date | None = None) -> None:
    """FTP, run threshold power or LTHR changed: the new value counts from today, earlier workouts keep
    the value they had (the old one, kept as "before" when there was no history yet)."""
    if field not in THRESHOLD_FIELDS or old == new:
        return
    day = day or localtime.today(user)
    hist = [dict(h) for h in user.threshold_history or []]
    if not any(h.get("field") == field for h in hist) and old is not None:
        hist.append({"field": field, "from": None, "value": old})
    hist = [h for h in hist if not (h.get("field") == field and h.get("from") == day.isoformat())]
    hist.append({"field": field, "from": day.isoformat(), "value": new})
    user.threshold_history = sort_history(hist)


def sort_history(hist: list[dict]) -> list[dict]:
    order = {f: i for i, f in enumerate(THRESHOLD_FIELDS)}
    return sorted(hist, key=lambda h: (order.get(h["field"], 9), h.get("from") or ""))


def set_history(db: DbSession, user: User, hist: list[dict]) -> None:
    """The athlete edited their threshold history: Profile shows the value of today, and every activity
    is scored again with the value of its own date."""
    user.threshold_history = sort_history(hist)
    today = localtime.today(user)
    for field in THRESHOLD_FIELDS:
        if any(h["field"] == field for h in hist):
            setattr(user, field, threshold_at(user, field, today))
    recalculate_tss(db, user)


def rescore_all_once(db: DbSession) -> int:
    """After a change in how TSS is scored (fitness.TSS_VERSION): score everyone's activities again, once.
    TSS comes from the stored power and heart rate, so this only recalculates; nothing else changes."""
    row = db.get(AppSetting, "tss_version")
    done = int(decrypt_json(row.value_enc)["v"]) if row else 0
    if done >= TSS_VERSION:
        return 0
    users = db.scalars(select(User)).all()
    for u in users:
        recalculate_tss(db, u)
    row = row or AppSetting(key="tss_version", value_enc="")
    row.value_enc = encrypt_json({"v": TSS_VERSION})
    db.merge(row)
    db.commit()
    log.info("Training load scored again for %d users (TSS version %d)", len(users), TSS_VERSION)
    return len(users)


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
            record_change(user, field, getattr(user, field), value)
            setattr(user, field, value)
            changed.append(field)
    user.profile_sources = sources
    if {"ftp_watts", "lthr_bpm", "run_ftp_watts"} & set(changed):
        recalculate_tss(db, user)
    return changed
