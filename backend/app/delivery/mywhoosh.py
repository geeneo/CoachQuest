"""MyWhoosh (experimental, off by default).

MyWhoosh has no official public API. A community project documents one
(github.com/mywhoosh-community/mywhoosh-api, "Unofficial API documentation"),
but it logs in with the athlete's MyWhoosh email and password, and MyWhoosh
hasn't endorsed it or published terms allowing it. Collecting platform
passwords is ruled out, so this is not feasible as an integration (checked
Oct 2026). Intervals.icu users report that Intervals.icu puts planned
workouts into MyWhoosh, so athletes get MyWhoosh delivery through the
Intervals.icu adapter instead. So:

- The adapter is only "available" when MYWHOOSH_EXPERIMENTAL is on.
- Even then no write operation is enabled: `operations` stays empty until an
  operation is verified as supported and permitted. No reverse-engineered
  login is implemented, and MyWhoosh passwords are never collected.
- Athletes use .zwo export meanwhile.
"""

from ..config import settings
from .base import Adapter


class MyWhoosh(Adapter):
    id = "mywhoosh"
    name = "MyWhoosh"
    operations = ()

    def available(self) -> bool:
        return settings.mywhoosh_experimental
