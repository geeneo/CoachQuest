"""Draft how-to guides and a first news post, added once to an empty News & guides section.

They are drafts (unpublished): an admin checks them, edits them to taste and
publishes them from News & guides. Written from how the app works; screen
names in **bold** match the app.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from .db import Post

GUIDES = [
    (
        "Getting started: connect Strava or Garmin",
        "Bring in your rides, runs and wellness so the AI coach has something to work with.",
        """CoachQuest plans from what you actually did, so the first step is to bring in your activities.

## Strava

1. Open **Connections** in the menu.
2. On the **Strava** card, click **Connect with Strava** and allow access to your activities.
3. Your last 180 days arrive in the background. Rides from Zwift and MyWhoosh come in through Strava too.

## Garmin Connect

1. On **Connections**, use the **Garmin Connect** card and sign in with your Garmin account.
2. Garmin adds sleep, HRV, resting heart rate and weight, which the AI coach uses for readiness notes.

## Older data

Use **Import older data** on a connection to go back a year or more. It runs in the background and
pauses by itself to stay inside Strava's limits.

## Next

- Fill in **Profile** (FTP, threshold heart rate, weight) so watts and training load are right.
- Set **Weekday preferences** in Profile: what you do on each day, up to several sessions a day.
""",
    ),
    (
        "Send your workouts to Zwift and MyWhoosh with Intervals.icu",
        "Scheduled workouts appear in Zwift and MyWhoosh by themselves, through Intervals.icu.",
        """Zwift and MyWhoosh don't let other apps send workouts straight to them, but Intervals.icu can:
CoachQuest puts your workouts on your Intervals.icu calendar, and Intervals.icu passes the coming
week on to Zwift and MyWhoosh.

## 1. Connect Intervals.icu

1. Open **Connections**.
2. On the **Intervals.icu** card, click **Connect Intervals.icu** and allow CoachQuest to write to your calendar.
3. Under **Connected platforms**, tick **Auto-send workouts** for Intervals.icu.

## 2. Link Zwift and/or MyWhoosh in Intervals.icu

1. In Intervals.icu, open **Settings**.
2. Link your **Zwift** account, and/or your **MyWhoosh** account.
3. In Zwift, the workouts appear under **Workouts → Custom → Intervals.icu** (the coming week).

## 3. Keep your FTP the same everywhere

Power targets are a percentage of FTP, so set the same FTP in CoachQuest (**Profile**),
Intervals.icu, Zwift and MyWhoosh.

## Good to know

- Only workouts from today on are sent. Changing, moving or deleting one in CoachQuest updates it
  in Intervals.icu too.
- **Connections → Workout delivery** shows what was sent, and lets you retry anything that failed.
- MyWhoosh users report that ramps in ERG mode and cadence targets don't carry over.
""",
    ),
    (
        "Ride your plan on MyWhoosh",
        "Three ways to get CoachQuest's workouts into MyWhoosh.",
        """## Automatically, through Intervals.icu (recommended)

Connect Intervals.icu, tick **Auto-send workouts**, and link MyWhoosh in Intervals.icu's settings.
See the guide *Send your workouts to Zwift and MyWhoosh with Intervals.icu*.

## By hand, with a workout file

1. On your training plan, click the blue **⬇ workout** chip on an indoor day, or use
   **⬇ Indoor workouts** for the whole week. You get .zwo files.
2. Go to MyWhoosh's **Workout Builder** (workout.mywhoosh.com), upload the .zwo file and choose
   **Export to MyWhoosh**.
3. In the MyWhoosh app the workout is under **MyWorkout**.

## Ride a MyWhoosh workout instead

1. On **Connections**, tick **MyWhoosh** as a preferred platform.
2. Indoor days on your plan then show **Closest on MyWhoosh** with a match score, when the
   workout catalog has a close one.
3. **Use this** swaps the day's workout for it; **Back to the plan's workout** swaps back.

Your MyWhoosh rides come back into CoachQuest through Strava or Garmin, and are matched to the
day's workout by name and time.
""",
    ),
    (
        "Your training calendar",
        "See, move, add and download your workouts day by day.",
        """Open **My training → Calendar**.

## What you see

- Each day's workouts, from your training plan or added by you or your coach.
- Where each workout was sent (✓ sent, retrying, failed), and the ride that completed it.
- **Planned vs actual** under the calendar: time, training load and power against the plan.

## Add a workout

Drag a workout from your library onto a day (or tap it, then tap the day). Build workouts under
**Workouts**.

## Change a workout

Click a workout to open it. You can:
- **Move to** another date,
- skip or cancel it,
- pick the ride that completed it, or mark it "not done",
- **Download .zwo** for Zwift or MyWhoosh.

A workout made by your training plan follows the plan (re-plans update it) until you edit it on
the calendar.

## Week and day view

Switch between **Week** and **Day**, and download the shown workouts with **Week as ZIP**.
""",
    ),
]

NEWS = (
    "What's new in CoachQuest",
    "Several sessions a day, Zwift and MyWhoosh matches, dark mode and more.",
    """- **Several sessions a day.** Weekday preferences take more than one type a day
  (e.g. Zwift + Strength), and the AI coach plans every one of them.
- **Zwift and MyWhoosh matches.** Indoor plan days show the closest Zwift or MyWhoosh workout
  for the platform you ride on, and you can swap to it.
- **Dark mode switch** at the top right of every page.
- **News and how-to guides**, right here.
""",
)


def seed(db: DbSession) -> None:
    """Add the drafts when there are no posts at all (a fresh install, or every post deleted)."""
    if db.scalar(select(func.count()).select_from(Post)):
        return
    for i, (title, summary, body) in enumerate(GUIDES):
        db.add(Post(kind="guide", title=title, summary=summary, body_md=body, position=(i + 1) * 10))
    title, summary, body = NEWS
    db.add(Post(kind="news", title=title, summary=summary, body_md=body))
    db.commit()
