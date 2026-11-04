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
- Or click **From my Strava**, tick your starred segments and routes on Strava (several at once),
  and click **Add to favourites**. Routes missing? Connect Strava again on **Connections** and
  allow it to see your private routes.

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
- keeps indoor days to their structured workout, without a route or segment.

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
to see how to do it: photos of the start and end of the movement, a body map with the muscles it
works, and the steps.

## Good to know

- The exercises come from an open, public-domain exercise library (text and photos).
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

ZWIFT_GUIDE = (
    "Get your plan into Zwift: link Intervals.icu with Zwift",
    "Step by step: CoachQuest puts your workouts on your Intervals.icu calendar, and Zwift picks them up.",
    """Your plan's indoor workouts can wait for you in Zwift, ready to ride in ERG mode. CoachQuest
can't send them to Zwift directly, but Intervals.icu (free) can, so the chain is:

**CoachQuest → Intervals.icu calendar → Zwift**

## 1. Connect Intervals.icu in CoachQuest

1. Open **Connections**.
2. On the **Intervals.icu** card, click **Connect Intervals.icu** and allow CoachQuest to write to
   your calendar. (No account yet? Make one at [intervals.icu](https://intervals.icu), it's free.)
3. Under **Connected platforms**, tick **Auto-send workouts** for Intervals.icu.

From now on, every workout on your **Calendar** from today on is put on your Intervals.icu
calendar, and kept up to date when you change, move or delete it.

## 2. Link Zwift in Intervals.icu

1. In Intervals.icu, open **Settings** and find the **Zwift** box.
2. Click **Connect**. Zwift opens: make sure you're logged in to the Zwift account you ride with,
   and accept.
3. Back in Intervals.icu, choose what to upload to Zwift: tick workouts for **Rides**. You can also
   let it download your Zwift rides (they then come straight from Zwift instead of through Strava).

## 3. Ride it in Zwift

- **Today's workout** shows on the Zwift home screen when you log in.
- **The coming week** is under **Workouts → Custom → Intervals.icu**.

## 4. Keep your FTP the same everywhere

Power targets are a percentage of FTP, so set the same FTP in CoachQuest (**Profile**),
Intervals.icu (**Settings → Sports → Ride**) and Zwift. Otherwise Zwift asks for different watts
than your plan.

## Good to know

- Intervals.icu sends **the next 7 days** to Zwift, every day. A workout further out arrives later;
  past ones are taken off.
- CoachQuest sends workouts as indoor rides, which is what Zwift takes. Workouts you make yourself
  in Intervals.icu need **Indoor** ticked too.
- Targets are power (% of FTP) and cadence; heart-rate targets don't carry over to Zwift.
- **Connections → Workout delivery** in CoachQuest shows what was sent, and lets you retry anything
  that failed.

## Not showing up in Zwift?

1. Check the workout is on your Intervals.icu calendar (if not, look at **Workout delivery**).
2. Check it's within the next 7 days.
3. Close Zwift and log in again: workouts are loaded when Zwift starts.
4. Still nothing? In Intervals.icu **Settings → Zwift**, disconnect and connect again. Zwift
   support suggests this for workouts that stop syncing.

## Watch how it's done

- TheCycloBrewer: [Zwift custom workout scheduling with Intervals.icu](https://www.youtube.com/watch?v=UcodSWxvZdQ&t=145s)
- [How to sync Intervals.icu to Zwift and other apps](https://www.youtube.com/watch?v=Qkqgb51NIHY)
- Nina Nygaard: [create a Zwift workout on Intervals.icu](https://www.youtube.com/shorts/T207hvyiQ74)

## More help

- [Intervals.icu and Zwift integration is live](https://forum.intervals.icu/t/intervals-icu-and-zwift-integration-is-live/81764)
  (the Intervals.icu forum, setup and questions)
- [Intervals.icu announces Zwift integration](https://zwiftinsider.com/intervals-integration/) (Zwift Insider)
- [Planned workouts not syncing to Zwift](https://forum.intervals.icu/t/solved-planned-workouts-not-syncing-to-zwift/97528)
  (fixes others found)
""",
)

LOAD_GUIDE = (
    "Compare your training load with TrainingPeaks",
    "Fitness, fatigue and form different from TrainingPeaks? See how CoachQuest got its numbers and find the "
    "first day the two part.",
    """CoachQuest and TrainingPeaks both show **fitness (CTL)**, **fatigue (ATL)** and **form (TSB)**, worked out
the same way from each day's training stress (TSS). When the numbers differ, it's almost always the TSS of
some sessions, not the sums. This guide shows how to find which.

## 1. Open the training load audit

1. Go to **My training → Overview**.
2. Under **Training load**, click **See how it's calculated and compare**.
3. Pick **180 days**.

The page shows, without changing anything:

- the **FTP**, **threshold heart rate (LTHR)** and **time zone** CoachQuest used;
- **warnings**, for example no FTP, or a large share of estimated TSS;
- **where the TSS came from**: power and FTP, heart rate, Strava's Relative Effort, or an estimate from the
  duration (50 TSS an hour) when there's nothing else;
- every **day** (TSS, CTL, ATL, TSB) and every **activity** (source, counted or a copy, TSS, how).

Use **Days (CSV)** and **Activities (CSV)** to keep a copy.

## 2. Export the same period from TrainingPeaks

1. In TrainingPeaks on the web, click your name in the top right and open **Settings**.
2. Scroll down to **Export Data**.
3. On the **Workout Summary** row (format CSV), set **From** and **To** to the same dates as the audit
   (at most 12 months at a time) and click **Export**. You get a CSV of your workouts, possibly in a ZIP:
   CoachQuest takes either. You don't need **Workout Files** or **Custom Metrics**.

Coaches find the same export in each athlete's account settings. Bulk export may need a paid TrainingPeaks
plan.

## 3. Compare

1. Back on the audit page, under **Compare with TrainingPeaks**, click **Choose the TrainingPeaks file**
   and pick the CSV or ZIP.
2. CoachQuest adds up each day's workouts and compares every day in the file's date range. A day without a
   workout in TrainingPeaks counts as 0 there, so a walk only CoachQuest counted shows up.
3. Read the totals (and how many times higher or lower), then the **first day that differs**.

The file needs a date column (WorkoutDay or Date) and a TSS column. If CoachQuest says it can't find them,
open the file and check the first row's column names.

## 4. What the difference usually is

- **FTP.** Power TSS goes with the square of power ÷ FTP: an FTP 10% lower makes about 23% more TSS. CoachQuest
  scores every ride with the FTP in your **Profile** today; TrainingPeaks keeps each workout's TSS from the
  FTP it had then. Check both FTPs first.
- **Sessions without power or heart rate.** Walks, strength and yoga get an estimate in CoachQuest (Relative
  Effort, or 50 an hour); TrainingPeaks often gives them little or none. Setting your **threshold heart
  rate** in Profile lets CoachQuest score them by heart rate instead.
- **The same session twice.** A ride from Strava and Garmin counts once in CoachQuest (the Activities list
  in the audit says "copy of"). Check that TrainingPeaks doesn't have it twice either.
- **History.** CoachQuest starts counting 120 days before the period shown; TrainingPeaks from your first
  workout there. Long histories make small differences in CTL.
- **Form (TSB)** is the day before's fitness minus fatigue, on both. So today's CTL minus today's ATL isn't
  the form shown.

## Still not right?

Open **Data health** (from the same Training load card, or **Connections**) to check your connections,
duplicates and profile values, then **Download diagnostics** and send the file to your admin with the
TrainingPeaks CSV.
""",
)

LOAD_GUIDE_V2 = (
    "Compare your training load with TrainingPeaks",
    "Fitness, fatigue and form different from TrainingPeaks? See how CoachQuest got its numbers and find the "
    "first day the two part.",
    """CoachQuest and TrainingPeaks both show **fitness (CTL)**, **fatigue (ATL)** and **form (TSB)**, worked out
the same way from each day's training stress (TSS). When the numbers differ, it's almost always the TSS of
some sessions, not the sums. This guide shows how to find which.

## 1. Open the training load audit

1. Go to **My training → Overview**.
2. Under **Training load**, click **See how it's calculated and compare**.
3. Pick **180 days**.

The page shows, without changing anything:

- the **FTP**, **threshold heart rate (LTHR)** and **time zone** CoachQuest used;
- **warnings**, for example no FTP, or a large share of estimated TSS;
- **where the TSS came from**: power and FTP, heart rate, Strava's Relative Effort, or an estimate from the
  duration (50 TSS an hour) when there's nothing else;
- every **day** (TSS, CTL, ATL, TSB) and every **activity** (source, counted or a copy, TSS, how).

Use **Days (CSV)** and **Activities (CSV)** to keep a copy.

## 2. Export the same period from TrainingPeaks

1. In TrainingPeaks on the web, click your name in the top right and open **Settings**.
2. Scroll down to **Export Data**.
3. On the **Workout Summary** row (format CSV), set **From** and **To** to the same dates as the audit
   (at most 12 months at a time) and click **Export**. You get a CSV of your workouts, possibly in a ZIP:
   CoachQuest takes either. You don't need **Workout Files** or **Custom Metrics**.

Coaches find the same export in each athlete's account settings. Bulk export may need a paid TrainingPeaks
plan.

## 3. Compare

1. Back on the audit page, under **Compare with TrainingPeaks**, click **Choose the TrainingPeaks file**
   and pick the CSV or ZIP.
2. CoachQuest adds up each day's workouts and compares every day in the file's date range. A day without a
   workout in TrainingPeaks counts as 0 there, so a walk only CoachQuest counted shows up.
3. Read the totals (and how many times higher or lower), then the **first day that differs**.

The file needs a date column (WorkoutDay or Date) and a TSS column. If CoachQuest says it can't find them,
open the file and check the first row's column names.

## 4. What the difference usually is

- **FTP.** Power TSS goes with the square of power ÷ FTP: an FTP 10% lower makes about 23% more TSS. Both
  CoachQuest and TrainingPeaks score each workout with the FTP you had on its date. Copy your thresholds from
  TrainingPeaks (**Settings → Zones**) into **Profile**, and your earlier FTPs into **Profile → Threshold
  history**, so older rides score as they did then.
- **Runs.** Runs use your **Run threshold power** (running power isn't on the cycling scale), or heart rate
  until you set it.
- **Walks, strength and yoga.** Scored as TrainingPeaks does: strength, yoga and other workouts 0; walks and
  hikes light, at most 15 TSS an hour.
- **The same session twice.** A ride from Strava and Garmin counts once in CoachQuest (the Activities list
  in the audit says "copy of"). Check that TrainingPeaks doesn't have it twice either.
- **History.** CoachQuest starts counting 120 days before the period shown; TrainingPeaks from your first
  workout there. Long histories make small differences in CTL.
- **Form (TSB)** is the day before's fitness minus fatigue, on both. So today's CTL minus today's ATL isn't
  the form shown.

## Still not right?

Open **Data health** (from the same Training load card, or **Connections**) to check your connections,
duplicates and profile values, then **Download diagnostics** and send the file to your admin with the
TrainingPeaks CSV.
""",
)

WHATS_NEW_2 = (
    "What's new in CoachQuest",
    "Training load that counts like TrainingPeaks, weather on your rides, how your week is going, and more.",
    """## Training load counts like TrainingPeaks

Your **fitness (CTL)**, **fatigue (ATL)** and **form (TSB)** are now much closer to TrainingPeaks:

- **Runs** are scored with a new **Run threshold power** in Profile (running power isn't on the cycling
  scale), or by heart rate until you set it. Before, runs could count two or three times too much.
- **Walks and hikes** count as light (at most 15 TSS an hour); **strength, yoga and other workouts** count 0,
  as on TrainingPeaks.
- **Each workout keeps the FTP of its date.** A new FTP counts from the day you change it; earlier rides keep
  their training load. Add your earlier FTPs (and threshold heart rate) in **Profile → Threshold history** so
  older rides score as they did then.
- Sessions count on your **local date**, so an early-morning ride no longer lands on the day before.
- **See how it's calculated and compare** (under Training load): every day and activity, and a day-by-day
  comparison with a TrainingPeaks export. The guide *Compare your training load with TrainingPeaks* has the
  steps.

To do: copy your **FTP**, **threshold heart rate** and **run threshold power** from TrainingPeaks
(**Settings → Zones**) into **Profile**.

## Your week

- **AI coach → This week so far**, with **How is your week going?**: on track, worth watching or off track,
  and what to look out for.
- **Weekly reviews** follow your plan's weeks and stick to the sessions planned for next week. You can delete
  a review.
- Extra sessions (e.g. Zwift + Strength on one day) show in the Calendar and in *Still to come*.

## Plans and calendar

- **The plan follows what you did**: a session done on another day or as another type is matched, and the
  days ahead adjust.
- **Weather** along your routes on outdoor plan days, and the AI coach plans with it (Weather page,
  home location and favourite routes).
- Calendar: done / partly / missed marks, planned km and climbing, week totals, rest days 😴.
- **Multi-day events**: a stage race's days with totals.

## Your data

- **Data health** (Overview, or Connections): checks your connections, activities, profile values, wellness
  and plan, with what to fix, and a report to download for your admin.
- Emails you can switch off in Profile: a reminder after a while away, and CoachQuest news.
- Profile: choose whether your training data, anonymised, may be used to improve CoachQuest (never Strava
  data).
""",
)


def _revised(post, pairs):
    title, summary, body = post
    for a, b in pairs:
        assert a in body, a[:40]
        body = body.replace(a, b)
    return (title, summary, body)


LOAD_GUIDE_V3 = _revised(
    LOAD_GUIDE_V2,
    [
        (
            "(running power isn't on the cycling scale), or heart rate\n  until you set it.",
            "(TrainingPeaks: run power threshold), or heart rate until\n  you set it. Runs by heart rate count "
            "far less than by power, so set it.",
        ),
        (
            "Scored as TrainingPeaks does: strength, yoga and other workouts 0; walks and\n"
            "  hikes light, at most 15 TSS an hour.",
            "Scored from heart rate against your **threshold heart rate**, as\n  TrainingPeaks does; walks a bit "
            "lower (TrainingPeaks scores them by pace). Without heart rate\n  they count 0.",
        ),
    ],
)

WHATS_NEW_2B = _revised(
    WHATS_NEW_2,
    [
        (
            "- **Walks and hikes** count as light (at most 15 TSS an hour); **strength, yoga and other workouts** "
            "count 0,\n  as on TrainingPeaks.",
            "- **Strength, yoga, walks and hikes** are scored from heart rate against your threshold heart rate, as\n"
            "  TrainingPeaks does (walks a bit lower); without heart rate they count 0.",
        ),
        (" Before, runs could count two or three times too much.", " Set it: runs by heart rate count far less."),
    ],
)


WHATS_NEW_2C = _revised(
    WHATS_NEW_2B,
    [
        (
            "To do: copy your **FTP**",
            "- **Coaches** with your *profile* share can set your FTP, run threshold power and threshold heart rate\n"
            "  (athlete → Overview → Thresholds); your Profile says who set each value.\n"
            "- When a value was simply wrong, tick **Correct earlier workouts too** so it counts for all of them.\n\n"
            "To do: copy your **FTP**",
        )
    ],
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
    {"key": "zwift-intervals", "kind": "guide", "position": 15, "published": True, "post": ZWIFT_GUIDE},
    {"key": "training-load-compare", "kind": "guide", "position": 30, "published": True, "post": LOAD_GUIDE_V3},
    {"key": "whats-new-2", "kind": "news", "position": 0, "published": True, "post": WHATS_NEW_2C},
]
FIRST_BATCH = {"strava-garmin", "intervals", "mywhoosh", "calendar", "whats-new-1"}
SEEDED = "posts_seeded"


def _seeded(db: DbSession) -> set[str]:
    row = db.get(AppSetting, SEEDED)
    if row is not None:
        return set(decrypt_json(row.value_enc)["v"])
    # Before keys were remembered, the first batch went in whenever there were posts at all.
    return set(FIRST_BATCH) if db.scalar(select(func.count()).select_from(Post)) else set()


# Shipped posts rewritten later: (key, old post, new post). The text is replaced once, only where an admin
# hasn't edited it since.
REVISIONS = [
    ("training-load-compare@2", LOAD_GUIDE, LOAD_GUIDE_V2),
    ("training-load-compare@3", LOAD_GUIDE_V2, LOAD_GUIDE_V3),
    ("whats-new-2@2", WHATS_NEW_2, WHATS_NEW_2B),
    ("whats-new-2@3", WHATS_NEW_2B, WHATS_NEW_2C),
]


def _revise(db: DbSession, done: set[str]) -> set[str]:
    applied = set()
    for key, (title, _, body), (new_title, new_summary, new_body) in REVISIONS:
        if key in done:
            continue
        for post in db.scalars(select(Post).where(Post.title == title)):
            if post.body_md == body:
                post.title, post.summary, post.body_md = new_title, new_summary, new_body
        applied.add(key)
    return applied


def seed(db: DbSession) -> None:
    """Add the shipped posts not added before (a fresh install gets them all), and apply rewrites."""
    done = _seeded(db)
    new = [p for p in POSTS if p["key"] not in done]
    revised = _revise(db, done)  # before the new ones go in: a fresh install gets the new text
    if not new and not revised:
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
    row.value_enc = encrypt_json({"v": sorted(done | {p["key"] for p in new} | revised)})
    row.updated_at = utcnow()
    db.merge(row)
    db.commit()
