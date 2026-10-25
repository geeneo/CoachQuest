"""Settings an admin can change from the web UI, layered over the environment.

A value saved in the UI wins over the .env value; clearing it falls back to
.env again. Values are stored encrypted with TOKEN_ENCRYPTION_KEY, which lives
only in .env, so a copy of the database alone doesn't reveal them. Secrets are
write-only: the API never sends them back, only whether they are set and their
last four characters.

Bootstrap settings (PROXY_SHARED_SECRET, TOKEN_ENCRYPTION_KEY, PUBLIC_BASE_URL)
are deliberately not here: the app and nginx need them before this can load.
"""

import logging
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .config import settings
from .db import AppSetting, utcnow
from .security import decrypt_json, encrypt_json

log = logging.getLogger("coachquest.settings")


@dataclass(frozen=True)
class Editable:
    label: str
    group: str
    secret: bool = False
    choices: tuple[str, ...] = ()
    pattern: str = ""
    help: str = ""


EDITABLE: dict[str, Editable] = {
    "anthropic_api_key": Editable(
        "Anthropic API key",
        "AI coach",
        secret=True,
        pattern=r"sk-ant-[A-Za-z0-9_\-]{20,}",
        help="From console.anthropic.com → API keys.",
    ),
    "anthropic_model": Editable(
        "Model",
        "AI coach",
        pattern=r"[a-z0-9][a-z0-9.\-]{2,63}",
        help="Default: claude-opus-5-5.",
    ),
    "anthropic_effort": Editable(
        "Effort",
        "AI coach",
        choices=("low", "medium", "high", "xhigh", "max"),
        help="Higher means more thorough plans and more tokens.",
    ),
    "strava_client_id": Editable(
        "Client ID",
        "Strava",
        pattern=r"[0-9]{1,12}",
        help="From strava.com/settings/api.",
    ),
    "strava_client_secret": Editable("Client secret", "Strava", secret=True, pattern=r"[0-9a-f]{20,64}"),
    "registration_mode": Editable(
        "Registration",
        "Accounts",
        choices=("open", "closed"),
        help="Closed: only emails in ADMIN_EMAILS can create accounts.",
    ),
}

_overrides: dict[str, str] = {}


def load(db: DbSession) -> None:
    _overrides.clear()
    for row in db.scalars(select(AppSetting)).all():
        if row.key in EDITABLE:
            try:
                _overrides[row.key] = decrypt_json(row.value_enc)["v"]
            except RuntimeError:
                log.error("Could not decrypt setting %s; using .env value", row.key)


def get(key: str) -> str:
    if key in _overrides:
        return _overrides[key]
    return str(getattr(settings, key) or "")


def validate(key: str, value: str) -> str:
    spec = EDITABLE.get(key)
    if spec is None:
        raise ValueError(f"{key} can't be changed here")
    value = value.strip()
    if spec.choices and value not in spec.choices:
        raise ValueError(f"{spec.label}: choose one of {', '.join(spec.choices)}")
    if spec.pattern and not re.fullmatch(spec.pattern, value):
        raise ValueError(f"{spec.label}: that doesn't look like a valid value")
    return value


def save(db: DbSession, key: str, value: str | None, admin_id: int) -> None:
    """Store an override, or remove it (fall back to .env) when value is empty."""
    row = db.get(AppSetting, key)
    if not value:
        if row:
            db.delete(row)
        _overrides.pop(key, None)
    else:
        value = validate(key, value)
        if row is None:
            row = AppSetting(key=key, value_enc="")
            db.add(row)
        row.value_enc = encrypt_json({"v": value})
        row.updated_by = admin_id
        row.updated_at = utcnow()
        _overrides[key] = value
    db.commit()
    log.info("Admin %s %s setting %s", admin_id, "changed" if value else "cleared", key)


def describe() -> list[dict]:
    out = []
    for key, spec in EDITABLE.items():
        value = get(key)
        source = "web" if key in _overrides else ("env" if value else "unset")
        item = {
            "key": key,
            "label": spec.label,
            "group": spec.group,
            "secret": spec.secret,
            "choices": list(spec.choices),
            "help": spec.help,
            "source": source,
            "is_set": bool(value),
        }
        if spec.secret:
            item["hint"] = f"…{value[-4:]}" if len(value) >= 8 else ("set" if value else "")
        else:
            item["value"] = value
        out.append(item)
    return out
