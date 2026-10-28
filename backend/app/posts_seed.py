"""How-to guides and news posts that ship with CoachQuest, added once each to News & guides.

Each post has a key. At start-up the ones not added before are added; the keys
already added are remembered (app_settings "posts_seeded"), so a post an admin
edited or deleted is never added again. The first batch went in as drafts for
the admin to check; later ones are published at once (`published`). Written
from how the app works; screen names in **bold** match the app.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from .db import AppSetting, Post, utcnow
from .security import decrypt_json, encrypt_json

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


ROUTES_GUIDE = (
    "Plan your rides on your favourite routes and segments",
    "Save the loops and climbs you ride, and the AI coach plans your rides on them.",
    """CoachQuest can plan your rides on the roads you actually ride: your long-ride loop, your easy
spin, the climb you use for hill repeats.

- A **route** is a whole ride (e.g. the Saturday loop over Hells).
- A **segment** is a climb or stretch for efforts (e.g. Kendal climb for hill repeats).

## 1. Save your favourites

Open **My training → Plans → Favourite routes & segments**. Then either:

- **Paste a Strava link** and click **Add favourite**. All three work:
  - a route: `strava.com/routes/…`
  - a segment: `strava.com/segments/…`
  - a ride you did: `strava.com/activities/…` (saved as a route, "from a ride")
- Or click **From my Strava** to pick from your starred segments and your routes on Strava, and
  click **Add**. Private routes on Strava don't show up there; paste their link instead.

With Strava connected, the length, climbing, gradient and time are filled in for you.

## 2. Say what each one is for

Tick what each favourite is for: **hill repeats**, **intervals**, **sprints**, **tempo**,
**endurance**, **long ride**, **recovery** or **race simulation**. Add a note for the coach if it
helps, e.g. "4-8 repeats, easy back down".

The AI coach goes by these ticks: a route ticked **long ride** is used for your long rides, a
segment ticked **hill repeats** for hill repeats.

## 3. Let the AI coach plan on them

Make a new plan, or click **Re-plan from this week** on your plan. The AI coach then:

- plans outdoor rides on a route whose length and ticks fit, and takes the ride's time from it;
- plans hill repeats and efforts on a segment ("6 x Kendal climb at 95-105% FTP, easy back down");
- on indoor days, gives the same efforts and names the climb for reference.

## 4. Or put a route on a day yourself

On your training plan, click the **map** button next to swap / lock / comment on a day, and pick
the route or segment. Pick **– no route –** to take it off. (Clicking the day's description and
using **Route / segment** in the editor works too.)

## Where you see them

- On the training plan, each day shows 🗺 (route) or ⛰ (segment) as a link that opens it in Strava.
- On **My training → Calendar**, the day shows the same link under the plan.
""",
)

ROUTES_NEWS = (
    "New: plan your rides on your favourite routes and segments",
    "Save your loops and climbs from Strava; the AI coach plans your long rides and hill repeats on them.",
    """- **Favourite routes & segments** on the Plans tab: paste a Strava route, segment or ride link,
  or pick from your starred segments and routes with **From my Strava**.
- Tick what each is for (long ride, hill repeats, recovery…). The AI coach plans your rides on
  them when you make a plan or re-plan.
- A **map** button on each plan day puts a route on that day in one click.
- Plan days and the **Calendar** link straight to the route or segment in Strava.

See the guide *Plan your rides on your favourite routes and segments* for the steps.
""",
)

STRENGTH_GUIDE = (
    "Strength training with the AI coach",
    "Tell the coach what equipment you have; it writes your strength sessions for cycling and running.",
    """Strength work makes cyclists and runners faster and more robust: research shows heavy strength
training helps cycling, and heavy strength plus jumps (plyometrics) helps running economy, without
hurting either. CoachQuest's AI coach now writes your strength sessions.

## 1. Set your strength options

Open **Profile → Strength training**:

- **Equipment I have**: tick everything you can use, e.g. bodyweight, bands, dumbbells,
  kettlebells, barbell or gym machines. The coach only picks exercises you can do with it.
- **For**: cycling, running or both.
- **Level**: beginner, intermediate or expert.
- **Sessions a week** and **Minutes each**.
- **Limits**: injuries or exercises to avoid, e.g. "left knee: no deep jumps".

Click **Save strength options**.

## 2. Pick your strength days

In **Profile → Weekday preferences**, add **Strength** on one or two days. It can share a day with a
ride or run (e.g. **Zwift / indoor** + **Strength**): the coach plans both.

## 3. Let the AI coach write the sessions

Make a new plan, or click **Re-plan from this week** on your plan. Each Strength session comes
with a list of exercises, each with **sets × reps**, how hard (e.g. **RPE 8**: about 2 reps left in
the tank), rest between sets and a short cue.

How the coach builds them:

- **Base and build**: heavy legs and hips twice a week (a squat, a hinge such as a deadlift or hip
  thrust, single-leg work, calves) plus core. Beginners start lighter and build up over 3-4 weeks.
- **Runners**: a few hops, bounds or jumps before the heavy work, once you've done some weeks of
  strength.
- **Race season**: once a week to keep it. **Taper and race week**: none.
- Never the day before a key ride, run or race, and at least 48 hours between strength sessions.

## 4. Do the session

On your training plan, the day shows the session, e.g. **🏋 Heavy legs**. Click an exercise's name
to see how to do it, step by step.

## Good to know

- The exercises come from an open, public-domain exercise library (text only).
- Start light the first time you do an exercise, and stop if anything hurts.
- Record strength sessions on your watch or in Strava: they count toward that day's planned time
  on your plan.
""",
)

STRENGTH_NEWS = (
    "New: strength training from the AI coach",
    "Set your equipment in Profile; the AI coach writes strength sessions for cycling and running.",
    """- **Profile → Strength training**: tick your equipment, pick cycling and/or running, your level
  and any limits.
- On your **Strength** days the AI coach writes a full session: exercises with sets, reps, effort
  and rest, heavier in base and build and lighter in race season.
- Click an exercise on your plan for step-by-step instructions.

See the guide *Strength training with the AI coach* for the steps.
""",
)

# Every post that ships with CoachQuest, by key. Keys never change; new posts get new keys.
POSTS = [
    *(
        {"key": key, "kind": "guide", "position": (i + 1) * 10, "published": False, "post": g}
        for i, (key, g) in enumerate(zip(("strava-garmin", "intervals", "mywhoosh", "calendar"), GUIDES, strict=True))
    ),
    {"key": "whats-new-1", "kind": "news", "position": 0, "published": False, "post": NEWS},
    {"key": "routes", "kind": "guide", "position": 25, "published": True, "post": ROUTES_GUIDE},
    {"key": "routes-news", "kind": "news", "position": 0, "published": True, "post": ROUTES_NEWS},
    {"key": "strength", "kind": "guide", "position": 27, "published": True, "post": STRENGTH_GUIDE},
    {"key": "strength-news", "kind": "news", "position": 0, "published": True, "post": STRENGTH_NEWS},
]
FIRST_BATCH = {"strava-garmin", "intervals", "mywhoosh", "calendar", "whats-new-1"}
SEEDED = "posts_seeded"


def _seeded(db: DbSession) -> set[str]:
    row = db.get(AppSetting, SEEDED)
    if row is not None:
        return set(decrypt_json(row.value_enc)["v"])
    # Before keys were remembered, the first batch went in whenever there were posts at all.
    return set(FIRST_BATCH) if db.scalar(select(func.count()).select_from(Post)) else set()


def seed(db: DbSession) -> None:
    """Add the shipped posts not added before (a fresh install gets them all)."""
    done = _seeded(db)
    new = [p for p in POSTS if p["key"] not in done]
    if not new:
        return
    for p in new:
        title, summary, body = p["post"]
        db.add(
            Post(
                kind=p["kind"],
                title=title,
                summary=summary,
                body_md=body,
                position=p["position"],
                published=p["published"],
                published_at=utcnow() if p["published"] else None,
            )
        )
    row = db.get(AppSetting, SEEDED) or AppSetting(key=SEEDED, value_enc="")
    row.value_enc = encrypt_json({"v": sorted(done | {p["key"] for p in new})})
    row.updated_at = utcnow()
    db.merge(row)
    db.commit()
