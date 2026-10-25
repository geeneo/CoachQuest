"""SQLAlchemy models and session handling."""

from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .config import settings


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(100))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    # Athlete profile, used for TSS and by the AI coach
    ftp_watts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lthr_bpm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_hr_bpm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Where weight_kg came from ("garmin" | "manual") and when it was measured or entered.
    weight_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    weight_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Where FTP / LTHR / max HR came from: {"ftp_watts": {"source": "garmin", "at": "...", "garmin_seen": 265}}
    profile_sources: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # {"mon": ["Rest"], "tue": ["Zwift / indoor"], ...}; see preferences.py
    weekday_prefs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    note_tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # {"daily": bool, "weekly": bool, "email": bool}: scheduled AI coach notes
    ai_settings: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    week_start: Mapped[int] = mapped_column(Integer, default=0)  # 0 = Monday ... 6 = Sunday


class Session(Base):
    """Server-side login session. Only a hash of the cookie value is stored."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Connection(Base):
    """A user's link to a data provider. Tokens are Fernet-encrypted."""

    __tablename__ = "connections"
    __table_args__ = (UniqueConstraint("user_id", "provider"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(20))  # strava | garmin
    external_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    token_enc: Mapped[str] = mapped_column(Text)  # encrypted JSON blob
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | error
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # What to import from this provider, e.g. {"activities": false, "wellness": true}.
    # Missing keys mean "on"; see sync_options.py.
    options: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Progress of an "import older data" run; see backfill.py.
    backfill: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class UserStravaApp(Base):
    """A user's own Strava API app, used instead of the server-wide one."""

    __tablename__ = "user_strava_apps"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(20))
    secret_enc: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class OAuthState(Base):
    __tablename__ = "oauth_states"

    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PendingMfa(Base):
    """Garmin login waiting for an MFA code. Encrypted, expires after 10 minutes."""

    __tablename__ = "pending_mfa"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    state_enc: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Activity(Base):
    __tablename__ = "activities"
    __table_args__ = (UniqueConstraint("user_id", "source", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(20))  # strava | garmin
    external_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255), default="")
    sport: Mapped[str] = mapped_column(String(40), default="Other")
    start_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    duration_s: Mapped[int] = mapped_column(Integer, default=0)
    distance_m: Mapped[float] = mapped_column(Float, default=0)
    elevation_m: Mapped[float] = mapped_column(Float, default=0)
    avg_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_power: Mapped[float | None] = mapped_column(Float, nullable=True)
    norm_power: Mapped[float | None] = mapped_column(Float, nullable=True)
    relative_effort: Mapped[float | None] = mapped_column(Float, nullable=True)
    tss: Mapped[float] = mapped_column(Float, default=0)
    tss_method: Mapped[str] = mapped_column(String(20), default="duration")
    avg_cadence: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_speed_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    kilojoules: Mapped[float | None] = mapped_column(Float, nullable=True)
    calories: Mapped[float | None] = mapped_column(Float, nullable=True)
    indoor: Mapped[bool] = mapped_column(Boolean, default=False)  # trainer / virtual
    is_race: Mapped[bool] = mapped_column(Boolean, default=False)
    # Set by the athlete in CoachQuest; never written back to the provider.
    type_override: Mapped[str | None] = mapped_column(String(40), nullable=True)
    race_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note_tag: Mapped[str | None] = mapped_column(String(40), nullable=True)


class WellnessDay(Base):
    __tablename__ = "wellness_days"
    __table_args__ = (UniqueConstraint("user_id", "day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    resting_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    hrv_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    sleep_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sleep_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    body_battery_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    stress_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    steps: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Grant(Base):
    """An athlete lets a coach see selected data.

    pending -> active (coach accepts) -> revoked (either side ends it).
    """

    __tablename__ = "grants"

    id: Mapped[int] = mapped_column(primary_key=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    coach_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Race(Base):
    """An event an athlete is training for (or has done)."""

    __tablename__ = "races"
    __table_args__ = (UniqueConstraint("user_id", "code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(20))  # short id, e.g. "k2c"
    name: Mapped[str] = mapped_column(String(120))
    short_name: Mapped[str] = mapped_column(String(20), default="")
    distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    elevation_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    discipline: Mapped[str | None] = mapped_column(String(30), nullable=True)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    start_time: Mapped[str | None] = mapped_column(String(5), nullable=True)  # "06:30"
    target_ctl: Mapped[int | None] = mapped_column(Integer, nullable=True)
    days: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    request: Mapped[dict] = mapped_column(JSON, default=dict)
    facts: Mapped[dict] = mapped_column(JSON, default=dict)
    content_md: Mapped[str] = mapped_column(Text)
    # Structured plan (see plan_tracker.py). Older plans have only content_md.
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    weeks: Mapped[list | None] = mapped_column(JSON, nullable=True)
    model: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Assessment(Base):
    """AI coach note: a daily readiness check or a weekly review."""

    __tablename__ = "assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # None when scheduled
    kind: Mapped[str] = mapped_column(String(10))  # daily | weekly
    period_start: Mapped[date] = mapped_column(Date, index=True)
    verdict: Mapped[str | None] = mapped_column(String(10), nullable=True)  # go | easy | rest (daily)
    facts: Mapped[dict] = mapped_column(JSON, default=dict)
    content_md: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CoachChat(Base):
    """An 'Ask the coach' conversation. Messages are stored exactly as sent to Claude."""

    __tablename__ = "coach_chats"

    id: Mapped[int] = mapped_column(primary_key=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    viewer_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    messages: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AccessLog(Base):
    """Every time someone other than the athlete reads the athlete's data."""

    __tablename__ = "access_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    viewer_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    resource: Mapped[str] = mapped_column(String(40))
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AiCall(Base):
    """Metadata only: no prompt or response text."""

    __tablename__ = "ai_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    athlete_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    model: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(40))
    latency_ms: Mapped[int] = mapped_column(Integer)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PasswordReset(Base):
    """Single-use password reset link. Only a hash of the token is stored."""

    __tablename__ = "password_resets"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)  # admin id, or None if self-service
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AppSetting(Base):
    """Settings an admin changed in the web UI. Values are Fernet-encrypted."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_enc: Mapped[str] = mapped_column(Text)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


_connect_args = {"check_same_thread": False} if settings.db_url.startswith("sqlite") else {}
engine = create_engine(settings.db_url, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


# Columns added after the first release. create_all() only creates missing
# tables, so add missing columns to existing ones here.
_ADDED_COLUMNS = {
    "connections": {"options": "JSON", "backfill": "JSON"},
    "plans": {"start_date": "DATE", "weeks": "JSON"},
    "activities": {
        "avg_cadence": "FLOAT",
        "avg_speed_ms": "FLOAT",
        "kilojoules": "FLOAT",
        "calories": "FLOAT",
        "indoor": "BOOLEAN NOT NULL DEFAULT 0",
        "is_race": "BOOLEAN NOT NULL DEFAULT 0",
        "type_override": "VARCHAR(40)",
        "race_id": "INTEGER",
        "note_tag": "VARCHAR(40)",
    },
    "users": {
        "weight_source": "VARCHAR(20)",
        "weight_updated_at": "DATETIME",
        "profile_sources": "JSON",
        "weekday_prefs": "JSON",
        "note_tags": "JSON",
        "ai_settings": "JSON",
        "week_start": "INTEGER NOT NULL DEFAULT 0",
    },
}


def init_db() -> None:
    Base.metadata.create_all(engine)
    existing = inspect(engine)
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            have = {c["name"] for c in existing.get_columns(table)}
            for name, sql_type in columns.items():
                if name not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
