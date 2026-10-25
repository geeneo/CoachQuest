"""Workout delivery: adapters that put CoachQuest workouts on a training platform.

Each adapter wraps one platform's documented, authorised API. The sync engine
(sync_engine.py) decides when to call them and handles retries; adapters only
translate a workout and classify errors (see base.py).
"""

from .base import Adapter
from .intervals_icu import IntervalsIcu
from .mywhoosh import MyWhoosh
from .zwift import ZwiftOfficial

ADAPTERS: dict[str, Adapter] = {a.id: a for a in (IntervalsIcu(), ZwiftOfficial(), MyWhoosh())}


def adapter(provider: str) -> Adapter | None:
    return ADAPTERS.get(provider)
