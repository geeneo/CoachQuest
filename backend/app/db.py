"""SQLAlchemy models and session handling."""

import time
from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.exc import OperationalError
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
    # Approves sign-ups when "Super admin approves new sign-ups" is on; regular admins can't change their account.
    is_super_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    # False while waiting for an admin (registration mode "approval").
    approved: Mapped[bool] = mapped_column(Boolean, default=True)
    # Email me when someone invites me, accepts, or changes or stops sharing.
    notify_sharing: Mapped[bool] = mapped_column(Boolean, default=True)
    # Email me when someone comments on one of my plans (or a plan I coach).
    notify_comments: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    # Athlete profile, used for TSS and by the AI coach
    ftp_watts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lthr_bpm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_hr_bpm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    # From Garmin or typed in; coaches (profile scope) and the AI coach only ever see the age.
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
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
    # IANA name, e.g. "Africa/Johannesburg". Decides "today" and which day an activity
    # (stored in UTC) falls on. None = UTC.
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # How dates and times are shown (see datefmt.py); None = the default.
    date_format: Mapped[str | None] = mapped_column(String(10), nullable=True)
    time_format: Mapped[str | None] = mapped_column(String(4), nullable=True)
    # {"preferred": ["zwift"], "auto": {"zwift": false}}; see platforms.py
    platform_prefs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Strength options from Profile (strength.py): equipment, level, sports, sessions, minutes, limits.
    strength_prefs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Your plan in your Strava activity descriptions (strava_notes.py): off, manual (per activity) or auto.
    strava_notes: Mapped[str] = mapped_column(String(10), default="off")
    # Where the athlete's home forecast is for (Weather page); empty = where their latest ride started.
    home_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    home_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    home_name: Mapped[str] = mapped_column(String(120), default="")
    # Health conditions from Profile (health.py), and when the athlete accepted the medical disclaimer.
    health_conditions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    health_disclaimer_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Admin controls for the AI coach: off for this user, and a monthly limit overriding the site's.
    ai_disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Admin switch: no emails at all to this user, except password resets and the sign-up approval.
    emails_disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Set by a coach or an admin: plans the athlete asks the AI for apply without a coach's approval.
    plan_approval_off: Mapped[bool] = mapped_column(Boolean, default=False)
    # Hours a coach has to answer before the athlete may decide themselves; None = 48, 0 = never.
    approval_wait_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # When is_active is off: why, since when, and whether they paused it themselves (Profile).
    disabled_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    disabled_by_self: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_monthly_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)


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
    # The plan lines CoachQuest last wrote into this activity's Strava description (strava_notes.py).
    strava_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The route, as Strava's encoded summary polyline (outdoor Strava activities); see geo.py, ride_routes.py.
    polyline: Mapped[str | None] = mapped_column(Text, nullable=True)


class DeletedActivity(Base):
    """An activity the athlete deleted: syncs skip it (activity_delete.py), and it can be restored."""

    __tablename__ = "deleted_activities"
    __table_args__ = (UniqueConstraint("user_id", "source", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(20))
    external_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255), default="")
    sport: Mapped[str] = mapped_column(String(40), default="Other")
    start_time: Mapped[datetime] = mapped_column(DateTime)
    data: Mapped[dict] = mapped_column(JSON)  # the activity as it was, for Undo
    deleted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


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
    # Who filled the day: garmin, or intervals_icu (which only fills what Garmin left empty).
    source: Mapped[str] = mapped_column(String(20), default="garmin")


class Grant(Base):
    """An athlete lets a coach (or a friend) see selected data.

    pending -> active (coach accepts) -> revoked (either side ends it).
    `coach_id` is whoever was invited, also when `role` is "friend": friends only look
    (deps.allowed_scopes) and are never treated as the athlete's coach.
    """

    __tablename__ = "grants"

    id: Mapped[int] = mapped_column(primary_key=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    coach_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    role: Mapped[str] = mapped_column(String(10), default="coach")  # coach | friend (view only)
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
    # Target finish time, and the AI coach's last target CTL suggestion for it (race_target.py).
    target_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ctl_advice: Mapped[dict | None] = mapped_column(JSON, nullable=True)
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
    # Coach approval (plan_approval.py): approved | awaiting | sent_back. Only approved plans
    # put workouts on the calendar. `pending` is a re-plan waiting for a coach; `history` what happened.
    approval: Mapped[str] = mapped_column(String(12), default="approved")
    pending: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    history: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Comment(Base):
    """A comment by the athlete or a coach on a plan (or one of its days), an AI coach note
    (assessment) or a calendar workout. See comments.py."""

    __tablename__ = "comments"
    __table_args__ = (Index("ix_comments_target", "target", "target_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    target: Mapped[str] = mapped_column(String(12))  # plan | assessment | workout
    target_id: Mapped[int] = mapped_column(Integer)
    day: Mapped[date | None] = mapped_column(Date, nullable=True)  # plan comments about one day
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    edited_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class CoachInstruction(Base):
    """A standing instruction for the AI coach about one athlete ("no intervals on Mondays").

    Written by a coach with the plans scope or by the athlete; every plan, re-plan,
    readiness note, weekly review and chat answer follows the active ones.
    """

    __tablename__ = "coach_instructions"

    id: Mapped[int] = mapped_column(primary_key=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    until: Mapped[date | None] = mapped_column(Date, nullable=True)  # last day it applies; None = until removed
    active: Mapped[bool] = mapped_column(Boolean, default=True)  # paused when False
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class AthleteNote(Base):
    """Background the AI coach should know about an athlete (athlete_notes.py): one short fact."""

    __tablename__ = "athlete_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    category: Mapped[str] = mapped_column(String(12))  # see athlete_notes.CATEGORIES
    body: Mapped[str] = mapped_column(Text)
    review_by: Mapped[date | None] = mapped_column(Date, nullable=True)  # left out of AI requests after this
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    history: Mapped[list | None] = mapped_column(JSON, nullable=True)  # earlier versions, oldest first


class NoteSuggestion(Base):
    """A note the AI coach proposed (athlete_notes.py). Saved as a note only when a person accepts it;
    dismissed ones are kept so the same suggestion isn't made again."""

    __tablename__ = "note_suggestions"

    id: Mapped[int] = mapped_column(primary_key=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(12))
    body: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(10))  # chat | weekly
    asked_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | accepted | dismissed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Workout(Base):
    """A reusable workout in someone's library (see workouts.py for the steps format)."""

    __tablename__ = "workouts"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    instructions: Mapped[str] = mapped_column(Text, default="")
    sport: Mapped[str] = mapped_column(String(20), default="bike")
    steps: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ScheduledWorkout(Base):
    """A workout on an athlete's calendar. A copy of the steps, so editing the library
    workout later doesn't change what was assigned."""

    __tablename__ = "scheduled_workouts"

    id: Mapped[int] = mapped_column(primary_key=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    assigned_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    template_id: Mapped[int | None] = mapped_column(ForeignKey("workouts.id", ondelete="SET NULL"), nullable=True)
    # The athlete's local calendar day (in their timezone), not a UTC date.
    day: Mapped[date] = mapped_column(Date, index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    instructions: Mapped[str] = mapped_column(Text, default="")
    sport: Mapped[str] = mapped_column(String(20), default="bike")
    steps: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="planned")  # planned | skipped | cancelled
    # Made from a training plan's indoor day. Managed by the plan (kept in step with it) until
    # someone edits the workout itself on the calendar; see plan_workouts.py.
    plan_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    plan_managed: Mapped[bool] = mapped_column(Boolean, default=False)
    plan_day: Mapped[date | None] = mapped_column(Date, nullable=True)  # the plan day it was made for
    # The activity that completed it (see completion.py). match: auto | manual | none ("not done").
    activity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    match: Mapped[str] = mapped_column(String(10), default="auto")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PlatformWorkout(Base):
    """A Zwift or MyWhoosh workout in the shared catalog plan days are matched against
    (see platform_catalog.py). Uploaded by admins as .zwo files."""

    __tablename__ = "platform_workouts"
    __table_args__ = (UniqueConstraint("platform", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(20), index=True)  # zwift | mywhoosh
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    # Where it sits on the platform, from the file (Zwift: "4wk FTP Booster · Week 4").
    collection: Mapped[str] = mapped_column(String(160), default="")
    steps: Mapped[list] = mapped_column(JSON)
    # platform_catalog.features(steps), kept so matching doesn't recompute them.
    features: Mapped[dict] = mapped_column(JSON)
    added_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ExternalWorkout(Base):
    """What a platform has of a scheduled workout. Our key there is "cq-<scheduled id>", so
    sending the same workout twice updates it instead of creating a duplicate."""

    __tablename__ = "external_workouts"
    __table_args__ = (UniqueConstraint("scheduled_workout_id", "provider"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # No foreign key: the row must outlive a deleted workout until the platform has deleted it too.
    scheduled_workout_id: Mapped[int] = mapped_column(Integer, index=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(20))
    external_id: Mapped[str] = mapped_column(String(64))
    remote_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64))  # what was sent; unchanged = nothing to do
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SyncJob(Base):
    """One pending change for one platform: send (upsert) or remove (delete) a workout.

    At most one open job per workout and platform; a newer change replaces the
    queued one, so a burst of edits sends once."""

    __tablename__ = "sync_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(20))
    scheduled_workout_id: Mapped[int] = mapped_column(Integer, index=True)
    workout_name: Mapped[str] = mapped_column(String(120), default="")
    action: Mapped[str] = mapped_column(String(10))  # upsert | delete
    # queued | running | done | failed (gave up or rejected; Retry) | blocked (reconnect needed)
    status: Mapped[str] = mapped_column(String(10), default="queued", index=True)
    reason: Mapped[str] = mapped_column(String(40), default="")  # assigned, changed, cancelled, connected, retry
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SyncLog(Base):
    """Audit history: every attempt and its outcome."""

    __tablename__ = "sync_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(20))
    scheduled_workout_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    workout_name: Mapped[str] = mapped_column(String(120), default="")
    action: Mapped[str] = mapped_column(String(10))
    outcome: Mapped[str] = mapped_column(String(20))  # sent, deleted, unchanged, retrying, failed, blocked, ...
    message: Mapped[str] = mapped_column(Text, default="")
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


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


class AuthEvent(Base):
    """Sign-in log: sign-ins (and failed attempts), sign-outs, password and admin account events."""

    __tablename__ = "auth_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    # None for an unknown email or a deleted account; `email` keeps what was typed or known.
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    email: Mapped[str] = mapped_column(String(255), default="")
    event: Mapped[str] = mapped_column(String(30))
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str] = mapped_column(String(255), default="")
    detail: Mapped[str] = mapped_column(String(255), default="")
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


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
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)  # uncached input only
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # What the call was for (coach.KINDS) and the prompt-cache tokens (read ~0.1x, written ~1.25x the input price).
    kind: Mapped[str] = mapped_column(String(12), default="")
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
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


class Segment(Base):
    """A favourite Strava route or segment an athlete trains on (e.g. the climb for hill repeats,
    the Saturday long-ride loop); see segments.py."""

    __tablename__ = "segments"
    __table_args__ = (UniqueConstraint("athlete_id", "strava_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    strava_id: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(10), default="segment")  # segment | route
    name: Mapped[str] = mapped_column(String(120))
    # From Strava when the athlete's Strava is linked; otherwise empty.
    distance_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_grade: Mapped[float | None] = mapped_column(Float, nullable=True)
    elevation_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    city: Mapped[str] = mapped_column(String(80), default="")
    # Routes: Strava's estimated moving time, and ride or run.
    est_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sport: Mapped[str] = mapped_column(String(10), default="ride")
    # What it's for (segments.USES), and how it's used, for the AI coach ("4-8 times, easy back down").
    uses: Mapped[list | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str] = mapped_column(String(300), default="")
    # The line on the map (Strava's encoded polyline), for the weather along it (weather.py).
    polyline: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Shared with everyone in CoachQuest (Routes page): others can add it to their own favourites.
    shared: Mapped[bool] = mapped_column(Boolean, default=False)
    added_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Post(Base):
    """A news item or how-to guide in the app, written by admins (see routers/posts.py)."""

    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), default="news")  # news | guide
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(String(300), default="")
    body_md: Mapped[str] = mapped_column(Text, default="")
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Guides are listed by this (lowest first); news newest first.
    position: Mapped[int] = mapped_column(Integer, default=0)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WelcomePage(Base):
    """The shareable information page (welcome.py): one row, edited by admins, shown at /welcome/<key>."""

    __tablename__ = "welcome_page"

    id: Mapped[int] = mapped_column(primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # The secret part of the link; a new one makes old links stop working.
    key: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(200), default="")
    body_md: Mapped[str] = mapped_column(Text, default="")
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AppSetting(Base):
    """Settings an admin changed in the web UI. Values are Fernet-encrypted."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_enc: Mapped[str] = mapped_column(Text)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# SQLite (one file in DATA_DIR, the default) or Postgres (DATABASE_URL=postgresql+psycopg://...;
# docs/postgres.md moves the data across with app.movedb and back again).
_sqlite = settings.db_url.startswith("sqlite")
engine = create_engine(
    settings.db_url,
    connect_args={"check_same_thread": False} if _sqlite else {},
    pool_pre_ping=not _sqlite,  # Postgres: drop connections the server closed (restart, idle timeout)
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


# Columns added after the first release. create_all() only creates missing
# tables, so add missing columns to existing ones here.
_ADDED_COLUMNS = {
    "connections": {"options": "JSON", "backfill": "JSON"},
    "plans": {
        "start_date": "DATE",
        "weeks": "JSON",
        "approval": "VARCHAR(12) NOT NULL DEFAULT 'approved'",
        "pending": "JSON",
        "history": "JSON",
    },
    "wellness_days": {"source": "VARCHAR(20) NOT NULL DEFAULT 'garmin'"},
    "scheduled_workouts": {
        "plan_id": "INTEGER",
        "plan_managed": "BOOLEAN NOT NULL DEFAULT 0",
        "plan_day": "DATE",
        "activity_id": "INTEGER",
        "match": "VARCHAR(10) NOT NULL DEFAULT 'auto'",
    },
    "activities": {
        "avg_cadence": "FLOAT",
        "avg_speed_ms": "FLOAT",
        "kilojoules": "FLOAT",
        "calories": "FLOAT",
        "indoor": "BOOLEAN NOT NULL DEFAULT 0",
        "is_race": "BOOLEAN NOT NULL DEFAULT 0",
        "type_override": "VARCHAR(40)",
        "strava_note": "TEXT",
        "polyline": "TEXT",
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
        "approved": "BOOLEAN NOT NULL DEFAULT 1",
        "is_super_admin": "BOOLEAN NOT NULL DEFAULT 0",
        "notify_sharing": "BOOLEAN NOT NULL DEFAULT 1",
        "notify_comments": "BOOLEAN NOT NULL DEFAULT 1",
        "birth_date": "DATE",
        "timezone": "VARCHAR(64)",
        "platform_prefs": "JSON",
        "strength_prefs": "JSON",
        "health_conditions": "JSON",
        "strava_notes": "VARCHAR(10) NOT NULL DEFAULT 'off'",
        "home_lat": "FLOAT",
        "home_lng": "FLOAT",
        "home_name": "VARCHAR(120) NOT NULL DEFAULT ''",
        "health_disclaimer_at": "DATETIME",
        "date_format": "VARCHAR(10)",
        "ai_disabled": "BOOLEAN NOT NULL DEFAULT 0",
        "emails_disabled": "BOOLEAN NOT NULL DEFAULT 0",
        "plan_approval_off": "BOOLEAN NOT NULL DEFAULT 0",
        "approval_wait_hours": "INTEGER",
        "disabled_reason": "VARCHAR(200)",
        "disabled_at": "DATETIME",
        "disabled_by_self": "BOOLEAN NOT NULL DEFAULT 0",
        "ai_monthly_limit": "INTEGER",
        "time_format": "VARCHAR(4)",
    },
    "races": {"target_seconds": "INTEGER", "ctl_advice": "JSON"},
    "platform_workouts": {"collection": "VARCHAR(160) NOT NULL DEFAULT ''"},
    "grants": {"role": "VARCHAR(10) NOT NULL DEFAULT 'coach'"},
    "segments": {
        "kind": "VARCHAR(10) NOT NULL DEFAULT 'segment'",
        "est_minutes": "INTEGER",
        "sport": "VARCHAR(10) NOT NULL DEFAULT 'ride'",
        "uses": "JSON",
        "shared": "BOOLEAN NOT NULL DEFAULT 0",
        "polyline": "TEXT",
    },
    "ai_calls": {
        "kind": "VARCHAR(12) NOT NULL DEFAULT ''",
        "cache_read_tokens": "INTEGER NOT NULL DEFAULT 0",
        "cache_write_tokens": "INTEGER NOT NULL DEFAULT 0",
    },
}


def _column_sql(sql_type: str, dialect: str) -> str:
    """The column types above are written for SQLite; Postgres wants TIMESTAMP and true/false defaults."""
    if dialect != "postgresql":
        return sql_type
    sql_type = sql_type.replace("DATETIME", "TIMESTAMP")
    if sql_type.startswith("BOOLEAN"):
        sql_type = sql_type.replace("DEFAULT 0", "DEFAULT false").replace("DEFAULT 1", "DEFAULT true")
    return sql_type


def wait_for_db(seconds: int = 60) -> None:
    """Postgres may still be starting when the API does (docker compose): wait for it a while."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            with engine.connect():
                return
        except OperationalError:
            if time.monotonic() > deadline:
                raise
            time.sleep(2)


def init_db() -> None:
    wait_for_db()
    Base.metadata.create_all(engine)
    existing = inspect(engine)
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            have = {c["name"] for c in existing.get_columns(table)}
            for name, sql_type in columns.items():
                if name not in have:
                    sql_type = _column_sql(sql_type, engine.dialect.name)
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"))
        # Plan comments briefly had their own table; move them into comments once.
        if existing.has_table("plan_comments"):
            conn.execute(
                text(
                    "INSERT INTO comments (athlete_id, target, target_id, day, author_id, body, created_at, edited_at) "
                    "SELECT p.athlete_id, 'plan', c.plan_id, c.day, c.author_id, c.body, c.created_at, c.edited_at "
                    "FROM plan_comments c JOIN plans p ON p.id = c.plan_id"
                )
            )
            conn.execute(text("DROP TABLE plan_comments"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
