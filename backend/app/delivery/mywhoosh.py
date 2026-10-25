"""MyWhoosh (experimental, off by default).

MyWhoosh has no official public API. A community project documents one
(github.com/mywhoosh-community/mywhoosh-api), but its authentication is
reverse-engineered and MyWhoosh hasn't published terms allowing it. So:

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
