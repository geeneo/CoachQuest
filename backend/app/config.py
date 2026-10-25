"""Settings, all read from the environment (see .env.example).

Required values are checked at startup so a misconfigured container fails
loudly instead of running half-working.
"""

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "coachquest")
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    data_dir: str = os.getenv("DATA_DIR", "/data")
    database_url: str = os.getenv("DATABASE_URL", "")
    registration_mode: str = os.getenv("REGISTRATION_MODE", "open")
    admin_emails: frozenset = field(
        default_factory=lambda: frozenset(
            e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()
        )
    )
    cookie_secure: bool = _bool("COOKIE_SECURE", True)
    session_ttl_hours: int = int(os.getenv("SESSION_TTL_HOURS", "336"))

    proxy_shared_secret: str = os.getenv("PROXY_SHARED_SECRET", "")
    token_encryption_key: str = os.getenv("TOKEN_ENCRYPTION_KEY", "")

    strava_client_id: str = os.getenv("STRAVA_CLIENT_ID", "")
    strava_client_secret: str = os.getenv("STRAVA_CLIENT_SECRET", "")

    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-opus-5-5")
    anthropic_effort: str = os.getenv("ANTHROPIC_EFFORT", "high")
    ai_monthly_limit: str = os.getenv("AI_MONTHLY_LIMIT", "200")

    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: str = os.getenv("SMTP_PORT", "587")
    smtp_security: str = os.getenv("SMTP_SECURITY", "starttls")
    smtp_username: str = os.getenv("SMTP_USERNAME", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from: str = os.getenv("SMTP_FROM", "")

    build_commit: str = os.getenv("BUILD_COMMIT", "dev")
    build_time: str = os.getenv("BUILD_TIME", "")
    enable_scheduler: bool = _bool("ENABLE_SCHEDULER", True)

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{self.data_dir}/coachquest.db"


settings = Settings()

SESSION_COOKIE = "cq_session"


def check_required() -> None:
    """Fail at startup if a key the app can't run without is missing."""
    missing = [
        name
        for name, value in {
            "PROXY_SHARED_SECRET": settings.proxy_shared_secret,
            "TOKEN_ENCRYPTION_KEY": settings.token_encryption_key,
            "PUBLIC_BASE_URL": settings.public_base_url,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError("Missing required environment variables: " + ", ".join(missing) + ". See .env.example.")
    if len(settings.proxy_shared_secret) < 32:
        raise RuntimeError("PROXY_SHARED_SECRET must be at least 32 characters.")
