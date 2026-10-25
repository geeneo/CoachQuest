"""Zwift's official Structured Training API (mode A).

Zwift's training API is open only to approved partners, and its endpoints and
authentication are shared with partners under agreement. CoachQuest has no
approval, so nothing here calls Zwift: this adapter reports itself unavailable
and every operation raises NotSupported. Fill it in from Zwift's partner
documentation once approved; don't guess endpoints.

Until then: .zwo export (zwo.py), or Intervals.icu, which is a Zwift partner
and forwards planned workouts to Zwift.
"""

from .base import Adapter


class ZwiftOfficial(Adapter):
    id = "zwift"
    name = "Zwift"
    operations = ()

    def available(self) -> bool:
        return False
