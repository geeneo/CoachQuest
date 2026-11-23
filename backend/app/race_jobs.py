"""After race days, in the background: fetch what the race review needs, and remind the athlete to write.

Once a day (main.py) for races that ended in the last FETCH_DAYS days:
- Fetch: Strava's detail of the race ride and its earlier years (segments, laps), the race's track (for the
  plan against the race) and the other riders' rides (race_review.py, race_analysis.py), each once, so the
  review opens without waiting on Strava. The rides sync from Strava a few times a day, so a race is tried
  on each of the days until its ride is there. Other riders aren't written to their access logs here:
  nobody looked yet (they are when someone opens the review).
- Remind: the day after the race (the athlete's local date), an email to write the post-race update while
  it's fresh, once per race (Race.reminded_at), when there's a ride, no update yet, and the athlete hasn't
  switched it off (Profile, notify_races).
"""

import logging
from datetime import date, timedelta

from sqlalchemy import select

from . import localtime, mailer, race_analysis, race_review, race_stages
from .config import settings
from .db import Race, SessionLocal, User, utcnow

log = logging.getLogger("coachquest.race_jobs")

FETCH_DAYS = 4
UPDATE_KEYS = ("official_s", "position", "went_well", "went_badly", "nutrition", "problems", "next_time")


def recent_races(db, today: date) -> list[Race]:
    rows = db.scalars(
        select(Race).where(
            Race.target_date.is_not(None),
            Race.target_date <= today,
            Race.target_date >= today - timedelta(days=FETCH_DAYS + 60),  # a stage race ends after its start
        )
    ).all()
    return [r for r in rows if today - timedelta(days=FETCH_DAYS) <= race_stages.last_day(r) < today]


async def prefetch(db, race: Race, owner: User, today: date | None = None) -> bool:
    """Everything the review fetches from Strava, done ahead (each day of a stage race on its own). True
    when a ride of the race was there."""
    today = today or date.today()
    stages = race_review.riding_stages(race)
    views = (
        [race_review.stage_view(race, s["day"]) for s in stages if s.get("date") and s["date"] <= today.isoformat()]
        if stages
        else [race]
    )
    found = False
    for view in views:
        ride = race_review.pick_ride(view, race_review.candidates(db, owner, view))
        if ride is None:
            continue
        found = True
        await race_review.fill_details(db, owner.id, [ride, *race_review.editions(db, owner, view, ride)])
        if view.target_seconds and view.segment_id:
            await race_analysis.fill_track(db, owner.id, race_review.strava_copy(db, ride))
        others = race_review.other_riders(db, owner, owner, view, ride, log_access=False)
        await race_review.fill_rider_details(db, others)
    return found


def needs_reminder(race: Race, owner: User, today_local: date) -> bool:
    res = race.result or {}
    return (
        race.reminded_at is None
        and race_stages.last_day(race) == today_local - timedelta(days=1)
        and not any(res.get(k) for k in UPDATE_KEYS)
        and owner.is_active
        and owner.notify_races
        and not owner.emails_disabled
    )


def reminder_text(race: Race, owner: User) -> tuple[str, str]:
    link = f"{settings.public_base_url}/races/{race.id}/review"
    subject = f"CoachQuest: how did {race.name} go?"
    text = (
        f"Hi {owner.display_name},\n\n"
        f"Well done on {race.name}! While it's fresh, take two minutes for your post-race update: your official "
        "time and position, how it felt, what went well and what didn't, food and drink, and what you'd do "
        "differently next time. The AI coach builds your next plans on it.\n\n"
        f"Your race review (your ride, earlier years, segments and the weather) is ready: {link}\n\n"
        "You can turn these reminders off in CoachQuest under Profile."
    )
    return subject, text


async def run(today: date | None = None) -> dict:
    """The daily job: prefetch recent races, and send the day-after reminders. Never raises."""
    fetched = reminded = 0
    with SessionLocal() as db:
        for race in recent_races(db, today or date.today()):
            owner = db.get(User, race.user_id)
            if owner is None or not owner.is_active:
                continue
            try:
                had_ride = await prefetch(db, race, owner, today)
                fetched += had_ride
            except Exception as exc:  # one race never stops the others
                log.warning("Race %s prefetch failed: %r", race.id, exc)
                db.rollback()
                had_ride = False
            local_today = today or localtime.today(owner)
            if had_ride and needs_reminder(race, owner, local_today) and mailer.configured():
                subject, text = reminder_text(race, owner)
                try:
                    await mailer.send(owner.email, subject, text)
                except mailer.MailError as exc:
                    log.warning("Race reminder to user %s not sent: %s", owner.id, exc)
                    continue
                race.reminded_at = utcnow()
                db.commit()
                reminded += 1
    if fetched or reminded:
        log.info("Races after the day: %s fetched, %s reminded", fetched, reminded)
    return {"fetched": fetched, "reminded": reminded}
