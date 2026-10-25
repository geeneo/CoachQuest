"""What every delivery adapter provides, and the errors the sync engine understands.

The error type decides what happens next, so adapters must pick it carefully:

- Transient: network trouble or a 5xx. Retried with exponential backoff.
- RateLimited: the platform asked us to slow down. Retried after `retry_after`.
- AuthFailed / Forbidden: the athlete's authorisation is gone or too narrow.
  Never retried automatically; the athlete has to reconnect.
- Rejected: the platform refused this workout (bad data). Not retried until
  the workout changes or someone presses Retry.
- NotSupported: the adapter can't do this at all (not configured, not
  approved, or the operation isn't verified).
"""

from dataclasses import dataclass


class DeliveryError(Exception):
    permanent = False

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class Transient(DeliveryError):
    pass


class RateLimited(DeliveryError):
    def __init__(self, message: str, retry_after: int = 60):
        super().__init__(message)
        self.retry_after = max(1, min(retry_after, 3600))


class AuthFailed(DeliveryError):
    permanent = True


class Forbidden(DeliveryError):
    permanent = True


class Rejected(DeliveryError):
    permanent = True


class NotSupported(DeliveryError):
    permanent = True


@dataclass
class Delivered:
    remote_id: str | None  # the platform's own id, when it returns one


class Adapter:
    """One platform. `token` is the decrypted credential dict from the Connection row."""

    id: str = ""
    name: str = ""
    # What the adapter can really do today. Only listed operations are ever called.
    operations: tuple[str, ...] = ()

    def available(self) -> bool:
        """Configured and allowed on this server (keys present, feature flag on...)."""
        return False

    async def upsert(self, token: dict, external_id: str, workout: dict, day) -> Delivered:
        raise NotSupported(f"{self.name} can't receive workouts")

    async def delete(self, token: dict, external_id: str) -> None:
        raise NotSupported(f"{self.name} can't delete workouts")

    async def revoke(self, token: dict) -> None:
        """Tell the platform we no longer use this authorisation. Best effort."""
