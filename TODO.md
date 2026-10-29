# CoachQuest to-do

## Next up

- [x] **Update CoachQuest from the admin page.** Admin → Update CoachQuest
      (super admins): running version, newest on GitHub, the new commits,
      "Check now", and "Update now" (everything / backend / frontend, with
      the admin's password), live log and earlier updates; recorded in the
      sign-in log. Safe by design: the API only writes a request file in
      DATA_PATH/deploy; deploy-agent.sh on the server (cron each minute,
      menu.sh option 11) runs deploy.sh. No Docker socket or root for the
      web app. Later: an email to super admins when new commits arrive;
      roll back to the previous version with one click.
      - [ ] Review the lock-down later (fine for testing now: super admin
        plus password): e.g. a second factor (TOTP) for updates, an email
        to all super admins when one starts, only allow it from certain
        IPs, or deploy only signed / tagged releases.

- [x] **Deleting a user deletes all their data.** accounts.delete_account
      follows every foreign key to users (tables added later are covered
      too): rows that belong to them are deleted, what they wrote for others
      stays unsigned. Before deleting, CoachQuest revokes its access at
      Strava and Intervals.icu and removes the upcoming workouts it sent to
      Intervals.icu; afterwards the user is emailed. Admin → Users shows
      what will be deleted once the email is typed. Tested on SQLite and
      Postgres: nothing anywhere points at the user afterwards.
      Still open: say in a privacy notice that the sign-in log keeps the
      email until it's cleared and backups for 14 days; "delete my
      account" and "export my data" for athletes themselves (POPIA/GDPR,
      Later list).

- [ ] **Wellness: tiles showed "–", and when Garmin data comes in.** The
      five tiles (resting HR, HRV, sleep, sleep score, Body Battery) took
      today's row, which is empty until the next sync, so they showed "–"
      while the chart had data. Fixed: each tile shows the newest day with
      a value (with its date when it isn't today), "no data yet" if none.
      Still to do:
      - Garmin syncs at 06:15 and 18:15 UTC (08:15 and 20:15 in South
        Africa); Strava and Intervals.icu every 6 hours. Show "last synced"
        and "next sync" on the wellness card, and a "Sync now" button.
      - Check which source sends sleep and Body Battery (Garmin direct
        does; Intervals.icu may not), and say so when a value never comes.
      - Maybe sync Garmin wellness once more mid-morning, after most
        watches have uploaded the night.

- [ ] **Monitor the database size.** Admin → Storage already shows the
      database size, per-table rows and free disk (per user under Admin →
      Users). Add:
      - a size history (one reading a day) with a small chart, so growth
        shows;
      - a warning to super admins (banner and email) when free disk drops
        below, say, 2 GB or the database grows unusually fast;
      - the backup age: when the last backup was made (none yet on the
        server!).

- [x] **Postgres option, with a lossless move and the way back.**
      docs/postgres.md: a db container (profile "postgres"), app.movedb
      copies every table SQLite → Postgres (source only read, counts
      checked, fixes reported), and back. Backups with pg_dump (menu 7).

- [ ] **URGENT to decide: Strava API Agreement (effective 1 June 2026) vs
      how CoachQuest uses Strava data.** Found while researching the
      write-back below (strava.com/legal/api_policy):
      - 5.3: Strava data may not be used "directly or indirectly" in
        developing or operating an AI application, also derived,
        aggregated or anonymised data, grounding and retrieval. The AI
        coach sends recent activities, load and volume to Claude, and these
        can come from Strava. Only the Strava MCP (3.5) is allowed for AI,
        and not for commercial or third-party use.
      - 2.3 / 6.1: a user's Strava data may be shown only to that user,
        unless the app's athlete capacity is 9,999 or less. CoachQuest
        shows it to coaches and friends (with consent); our Strava app is
        far below that limit, so 6.1 likely covers it for now.
      - Options: (a) email developers@strava.com describing CoachQuest
        and ask for written OK; (b) a super admin switch "Send Strava
        data to the AI coach" (off: Strava-sourced activities are left
        out of AI facts; Garmin, Intervals.icu and manual data still go);
        (c) make Garmin or Intervals.icu the main activity source for AI
        users. Not legal advice: check with a lawyer for the company.

- [x] **Done (29 Oct):** Profile → "Your plan on Strava": Off (default) /
      Per activity (a 🎯 button on each Strava activity, preview first) /
      Automatically (after each Strava sync, recent activities only, when
      the lines change); "Allow on Strava" asks for activity:write.
      Written from the plan, never by the AI; own text kept, lines replaced
      not repeated. Still to do: ask developers@strava.com before many
      athletes use it.
- [ ] **Write back to Strava: the plan in the activity description,
      "powered by coachquest.mmc24.com".** When an activity matches a plan
      day, CoachQuest updates its Strava description, e.g.
      "🎯 Planned: Sweet spot 2×10 (Z3-Z4) · ✅ Goal met — CoachQuest
      training plan · coachquest.mmc24.com".
      - Possible: Strava's API has Update Activity (PUT /activities/{id})
        for name, description and more; it needs the activity:write scope
        (and activity:read_all for "Only me" activities), so athletes
        connect Strava again and agree.
      - Opt in per athlete (Profile → Strava: "Add my plan to Strava
        descriptions"), off by default; keep their own text and add ours
        below it once (never twice, never over theirs); undo removes it.
      - Write it from CoachQuest's own plan, not with the AI from Strava
        data (see the agreement item above), and keep it short and
        factual: the API policy bans unsolicited promotion (5.12) and
        Strava decides; using the Strava name or logo has to follow the
        brand guidelines and must not suggest Strava endorses CoachQuest.
        Ask developers@strava.com before going live.
      - Mind the rate limits (an update per activity; batch on sync).

- [x] **Health conditions in Profile (checkboxes with presets), with a
      medical disclaimer.** Athletes tick what applies; the AI coach plans
      around it (and the strength options' "limits" stay for free text).
      - Presets, grouped, each with an optional side (left / right / both)
        and a short note:
        - Heart: heart condition, high blood pressure, arrhythmia (e.g.
          atrial fibrillation), pacemaker / ICD, on beta blockers (heart
          rate zones less reliable: plan by power or feel).
        - Joints: knee, hip, ankle, shoulder, lower back, neck, wrist.
        - Muscles and tendons: Achilles, hamstring, calf, plantar fasciitis,
          IT band.
        - Other: asthma, diabetes (type 1 / 2), osteoporosis / low bone
          density, pregnancy / postpartum, recent surgery, concussion,
          recent illness (e.g. COVID), and "other" with a text box.
        - Per condition: current or past, and "my doctor cleared me for
          training" (yes / no).
      - The AI coach gets them as facts with rules: e.g. heart conditions
        or beta blockers → no max efforts without clearance, use power or
        RPE instead of heart rate; knee → no deep squats or jumps, easy
        gears; lower back → core work, careful with heavy hinges;
        osteoporosis → impact and loaded strength as cleared; pregnancy →
        keep it conversational, no lying on the back after the first
        trimester. A current condition without clearance → the plan stays
        easy and says to see a doctor first.
      - Disclaimer, shown in Profile next to the conditions, on plans, in
        the AI coach, and once when ticking a heart condition (must
        confirm): "CoachQuest is not medical advice. Always consult a
        doctor or other qualified health professional before starting or
        changing training, especially with a medical condition or injury.
        Stop and get help if you feel chest pain, dizziness, unusual
        shortness of breath or pain." Also in the sign-up terms.
      - Privacy: health data is special personal information (POPIA /
        GDPR): opt in, coaches see it only with the plans scope (friends
        never), and it's part of account export and delete.

- [x] **Maintain fitness when not training for an event.** Today a plan
      needs a goal (free text) and the event date is optional, so plans
      without an event still build like a race block. Suggestions:
      - A plan type on "New plan": "Training for an event" or "Maintain /
        general fitness" (and maybe "Build base" or "Lose weight"). For
        maintain: no event date, rolling blocks of 4 weeks (3 normal + 1
        easy) that renew themselves, instead of base → build → peak →
        taper.
      - What maintain means to the AI coach: keep fitness (CTL) roughly
        where it is (within ±5), mostly endurance (Z2) with one quality
        session a week (sweet spot, threshold or VO2 rotating), strength
        twice a week, and variety (group ride, gravel, a new route from
        Routes) so it stays fun. Hours follow the athlete's weekday
        preferences.
      - A "maintain target": hold current CTL, or a gentle +1-2 CTL a
        month; the Progress chart shows the band instead of a race-day
        target.
      - When a new block is due, CoachQuest re-plans the next 4 weeks
        automatically from recent training (or asks first), and suggests
        an event if the athlete adds one on Races.
      - Optional "fitness check" every 6-8 weeks (FTP test or a known
        segment from Routes) to update zones.

- [x] **Routes page: favourites and routes shared by athletes.** A Routes
      menu item with your favourite routes and segments (moved from My
      training → Plans) and "Shared by athletes": share a favourite with
      everyone (your name shows), search and filter shared ones, add one
      to your favourites in one click; admins can take one off the list.

- [x] **Guide (News & guides): link Intervals.icu with Zwift so plan workouts show in Zwift.**
      A how-to post (posts_seed.py, like the routes & segments guide):
      CoachQuest → Intervals.icu calendar → Zwift.
      1. CoachQuest: connect Intervals.icu on Connections; plan workouts are
         sent to its calendar automatically.
      2. Intervals.icu: Settings → Zwift box → Connect, log in to the right
         Zwift account, accept, and tick which workouts to upload (Rides).
      3. Zwift: today's workout is on the home screen; the coming week is
         under Workouts → Custom → "Intervals.icu".
      Tips: only the next 7 days are sent (rolls daily); FTP must match in
      CoachQuest, Intervals.icu and Zwift (targets are % FTP); HR targets
      aren't supported; not syncing → check the workout is % FTP (not HR),
      wait a day, or disconnect and reconnect Zwift in Intervals.icu.
      Done: workouts now go to Intervals.icu with "indoor": true (its API's
      flag; Zwift only takes indoor workouts).
      Videos: youtube.com/watch?v=UcodSWxvZdQ&t=145s (TheCycloBrewer, Zwift
      custom workout scheduling), youtube.com/shorts/T207hvyiQ74 (Nina Nygaard, create a Zwift
      workout on intervals.icu), youtube.com/watch?v=Qkqgb51NIHY (syncing
      Intervals.icu to Zwift and others).
      Docs: forum.intervals.icu/t/intervals-icu-and-zwift-integration-is-live/81764,
      zwiftinsider.com/intervals-integration/,
      forum.intervals.icu/t/solved-planned-workouts-not-syncing-to-zwift/97528,
      intervals.icu/features/training-calendar/.

- [x] **Indoor sessions: no Strava segments, only workouts.**
      An indoor day (Zwift / indoor) can be planned with a favourite
      segment linked, e.g. Thu "Zwift / indoor 40′" shows "⛰ Kendal climb A"
      next to the "Kendal A 5x2" workout. Indoor days should only get a
      structured workout: the AI coach shouldn't link a route or segment to
      them (prompt and a server-side check that drops it), and the calendar
      shouldn't show one. Segments and routes stay for outdoor (Road) days.

- [x] **Admin → Platform workouts: collapse the screen.**
      With 1,177 workouts the section is pages and pages of collections.
      Make the whole section collapsible (collapsed by default, showing just
      the counts and search), group collections by series (e.g. "2018 PRL100
      Prep" with its weeks inside), sort weeks in number order (Week 2 before
      Week 10), and show the first 20 groups with "Show more".

- [x] **Show clearly on the calendar when a session was done (emoji).**
      A done workout only shows a small "✓ Done" line, easy to miss next to
      "✓ Intervals.icu". Make done days stand out at a glance, e.g. an emoji
      badge on the workout card (✅ done, ⏭ skipped, ⚠️ partly done/short),
      maybe a tinted card, in the week and day views of the plan calendar.

- [x] **Load favourite routes & segments from Strava, picking several at once.**
      In Favourite routes & segments, "From my Strava" lists the athlete's
      starred segments and saved routes, but each one is added with its own
      Add button. Make it a picker: show Routes and Segments (filter to one
      or both), tick the ones wanted (select all per group), set what
      they're for (uses) in one go, and add them together. Also on the
      coach's view of the athlete.

- [x] **Strength training from the AI coach (cycling and running).**
      - Exercise library: the public-domain Free Exercise DB
        (github.com/yuhonas/free-exercise-db, Unlicense), text only, no
        images (their origin isn't documented): strength, plyometrics,
        powerlifting and stretching exercises with instructions, equipment,
        level and muscles.
      - Strength options in Profile: equipment at hand, level, sports
        (cycling, running), sessions per week, limits.
      - The AI coach writes the Strength days as structured sessions
        (exercises from the library with sets, reps, effort and rest),
        periodised: heavy strength 2x/week in base and build, 1x/week to
        maintain in race season, plyometrics for runners, clear of key
        rides and runs (Rønnestad & Mujika 2014; Sports Med Open 2022).
      - Shown on the plan day with each exercise's instructions.
- [x] **Drawings in workouts.** Plan days show the indoor workout's power
      chart; strength exercises show start/end photos (400 px WebP, ~15 MB,
      super admin switch "Exercise photos" in case their origin is
      questioned) and a muscle map (our own SVG drawing).

- [x] **Favourite Strava routes and segments for planning rides.** Athletes
      keep favourite routes and segments (from a link or their Strava
      starred segments and routes), tagged with uses; the AI coach plans
      outdoor rides on routes and efforts on segments, linked on plan days.
- [x] **First sign-in: make clear what comes from where (no duplicates).**
      When a new user links Strava, Garmin and Intervals.icu, show a
      prominent step that says which app brings in what (rides, runs,
      wellness, weight) and lets them choose, so the same ride isn't
      imported twice (e.g. a Zwift ride arriving through both Strava and
      Garmin). Builds on the per-source sync options that already exist.
      - Show it as soon as a second source is linked, and on Connections
        until they've confirmed it.
      - Plain summary: "Rides from Strava, sleep / HRV / weight from Garmin,
        workouts go to Intervals.icu".
- [x] **Strava segments for hill repeats in the plan.** Save Strava segment
      links (e.g. the local climb used for hill repeats) with a name, and
      use them in training:
      - Add a segment by pasting its Strava link; keep a list per athlete
        (and coaches can add them for their athletes).
      - The AI coach knows the saved segments and, on hill-repeat days,
        says which one to ride ("6 x Helshoogte, link") on outdoor days.
      - Indoor days: the same efforts as an indoor workout, with the
        segment named for reference.
      - Show the segment link on the plan day, so it opens in Strava.

- [x] **News and how-to section.** A place in the app for posts about
      CoachQuest, written and edited by admins in the web UI:
      - News: blog updates about the application (what's new, changes).
      - How-to guides, e.g. connecting MyWhoosh, the training calendar,
        Intervals.icu (and from there Zwift / MyWhoosh), Strava and Garmin.
      - Admins create, edit, publish / unpublish and delete posts (Markdown);
        every signed-in user can read the published ones.
      - Start with draft guides for MyWhoosh, the calendar and Intervals.icu,
        written from how the app works today, for the admin to edit.
- [x] **Share your data with friends (view only).** Besides sharing with a
      coach, an athlete can let other CoachQuest users look at their data:
      - Pick what to share (activities, fitness, wellness, …) per person,
        like with a coach; the other person accepts.
      - View only: they can't edit plans, approve plans, comment as a coach
        or get coach emails, and they don't count as the athlete's coach
        (plan approval, "athlete may decide" and so on stay as they are).
      - Shown separately from coaches on Sharing, and their looks go in the
        athlete's "Who looked at my data" log like a coach's.
      - Either side can end it at any time.

- [x] **Dark mode switch in the top right.** A light/dark toggle in the
      header (top right, next to the user menu), so it can be changed from
      any page. It should use the same setting as the Light / Dark / System
      switch in Profile and be remembered per browser.
- [x] **Dark mode toggle.** The app already follows the operating system's
      light/dark setting. Add a Light / Dark / System switch in Profile,
      remembered per browser.
- [x] **Email (SMTP).** Admin → Settings: host, port, username, password
      (encrypted, write-only like the other secrets), from address, TLS.
      Include a "Send test email" button. Password reset depends on this.
- [x] **Users change their own password.** Profile: current password + new
      password (min 12). Signs out the user's other sessions.
- [x] **Forgot password.** "Forgot password?" on the sign-in page emails a
      single-use reset link that expires in 30 minutes.
      - The page always says "if that email has an account, we've sent a link",
        so it doesn't reveal who has an account.
      - Rate limited in nginx.
      - Resetting signs out every session.
      - Needs SMTP.
- [x] **Backfill older data.** First sync imports 180 days of Strava and 30
      days of Garmin. Add a "Import older data" option on Connections:
      - Pick a start date (e.g. 1 year, 2 years, everything).
      - Runs in the background with progress shown on the card.
      - Respects Strava's rate limits (200 requests / 15 min, 2,000 a day,
        shared with Home Assistant and the old hub), pausing and resuming
        instead of failing.
      - Garmin wellness goes back day by day, so long ranges are slow; cap it
        or run it overnight.
      - The fitness chart and CTL get more accurate with more history.
- [x] **Fill Profile from Garmin and/or Strava.** A "Pull from…" button per
      field (FTP, lactate threshold HR, max HR, weight), with a choice of
      Garmin, Strava or manual. Optionally keep it in sync on every sync.
      - Done from Garmin: weight, FTP, LTHR and max HR (from Garmin's
        power and heart-rate zones). Strava is skipped for now: see below.
      - Strava has FTP and weight only when the athlete set them there. It
        needs the `profile:read_all` scope, so Strava users reconnect once.
      - Show where each value came from and when, e.g. "FTP 265 W · Garmin ·
        3 days ago".
      - When FTP or LTHR changes, recalculate TSS (Save already does this).
- [x] **My training: volume summary** (like the old hub's Volume stats).
      - 7 / 30 / 90 day switch.
      - Cards: distance (with activity count), elevation, moving time,
        calories, average effort per ride (Strava relative effort).
      - "Activity mix" bar chart by type: Road, Virtual, MTB / E-MTB, Run…
        from Strava's sport type.
      - "Weekly elevation" bar chart for the last 12 weeks.
      - Calories: Garmin's activity list has them. For Strava, use kilojoules
        from the activity list (kJ ≈ kcal for cycling); otherwise leave blank
        rather than guess.
      - Coaches see it only with the activities scope.
- [x] **My training: Recent activities table** (like the old hub).
      - Period: Date range (7d, 30d, 90d, 180d, 1/2/3/5/10 years, All time),
        Month or Year view.
      - Type chips (All, Road, Zwift / Virtual, E-MTB, MTB, Run, Swim, Walk,
        Hike, Workout, Yoga…) built from the types actually present, plus
        "Races only", "Show NP" and a name search.
      - Summary line: count, km, elevation with "analog" elevation (outdoor
        only, excluding virtual rides) and hours.
      - Columns: Date, Type, Activity, Dist, Elev, Time, Speed, Power, NP,
        HR, Cadence, Cal, RE (relative effort as a coloured badge: green /
        amber / red), Race, Note.
      - Editable per activity, saved in CoachQuest, never written back to
        Strava:
        - Type override (e.g. mark a ride as E-MTB).
        - Race link (pick from a races list).
        - Note tag (Group, Solo, Wind, Weather, …).
      - Needs new stored fields: cadence, kilojoules/calories, average speed,
        and the override/race/note columns. Plus a small Races list (name,
        date, distance) to link to.
      - Coaches see it with the activities scope; only the athlete can edit.
- [x] **Races / event plan** (like the old hub's Races table, but per user and
      in the database).
      - Fields: short code, name, short name, distance (km), elevation (m),
        discipline, target date, start time, target CTL, days (stage races),
        active.
      - Disciplines for every sport, not just cycling: Road, Mountain bike,
        Gravel, Track, Run, Trail run, Ultra, Triathlon, Duathlon, Swim /
        open water, Multisport, Other.
      - Inline editing (click a field, saves when you leave it), plus an
        "Add a race" row. Past results are read-only.
      - Used by the Recent activities "Race" dropdown, a countdown and
        "Upcoming races" on My training, and the AI coach (event date and
        target CTL go into plans and assessments).
      - Coaches see races with the plans scope.
- [x] **Training preferences: weekday riding preferences.** One row per day
      (Mon–Sun), choose one or more: Rest, E-MTB, MTB, Road, Hill repeats,
      Zwift / indoor, Treadmill run, Outdoor run, Race. Other sports can be
      added. The AI coach reads this when planning (it replaces the plan
      form's "training days"). Option to apply it to weeks already planned.
- [x] **Training preferences: activity note tags.** Each user manages their
      own preset tags for the Recent activities "Note" dropdown: illness,
      mechanical, travel, weather, adventure, group, solo, wind, work, other…
      Add, rename (click a tag), remove. The AI coach reads tagged activities
      as explained (e.g. a light week marked "illness" is disclosed, not a
      gap in training).
- [x] **Training plan tracker** (like the old hub's Training plan page).
      The AI coach writes plans as structured weeks and days (not just
      Markdown) so they can be tracked against what was actually done.
      - Week cards: phase badge (Base / Build / Recovery / Taper / Race),
        dates, focus note ("build week toward DC"), draft or confirmed,
        current week highlighted and "today" marked.
      - Each day:
        - Session type (Rest, Road, Zwift / MyWhoosh, MTB, E-MTB, Run,
          Strength…). Click to change.
        - Description and intensity chips (e.g. "95–105% FTP", "Z2").
          Click to edit.
        - Bike / gear.
        - Actions: route, swap with another day, lock (the AI won't change
          it when it re-plans), "fits a workout" (indoor workout match).
      - Plan vs actual: each day is matched to the logged activity.
        - "Goal met: 120.7 km · 1213 m · 4h55m · RE 169 · 138 W avg".
        - Or "Not logged" with a "why missed?" dropdown that uses the
          activity note tags.
      - Uses weekday preferences, races (event date, target CTL) and note
        tags. Re-planning keeps locked and past days.
      - Coaches with the plans scope can view and edit; the athlete sees
        changes.
      - Done: "Re-plan from this week" (Claude rewrites the remaining weeks
        from what was logged, with an optional "what changed?" note, keeping
        locked and past days).
      - Done: indoor days carry a structured workout, put on the calendar
        and sent to Zwift / MyWhoosh through Intervals.icu (workout sync
        phase 3).
- [x] **AI coach: assessments of wellness and training progress.** A new
      "AI coach" page per athlete, next to Plans. Same rules as plans:
      CoachQuest computes the facts, Claude writes the words, and only the
      scopes granted to the viewer go in.
      - **Daily readiness:** a short morning note from last night's sleep, HRV,
        resting HR and Body Battery vs the athlete's own 30-day baseline,
        plus TSB. "Go / easy / rest" is decided in code; Claude explains why.
      - **Weekly review:** planned vs done, load and ramp rate, standout
        sessions, wellness trend, and what to change next week. Stored, so
        progress can be read week to week.
      - **Progress over time:** fitness (CTL) trend, power and pace bests,
        and how close the athlete is to the goal / event date.
      - **Ask the coach (agent):** a chat where Claude can look things up
        itself through tools (activities, load, wellness, plans), limited to
        the viewer's scopes. Every question and tool call goes in the access
        log.
      - **Delivery:** shown on My training and in the coach's athlete view.
        Weekly review by email once SMTP is in.
      - **Cost control:** daily notes are short. Per-user monthly limits and
        token use are shown on the Admin page.
- [x] **Admin user management.**
      - Admin → Users: "Set password", or "Send reset link" once SMTP works.
        Signs that user out everywhere. Logged.
      - "Delete user": removes the account and all its data (activities,
        wellness, connections, plans, grants). Asks you to type the email to
        confirm, and you can't delete yourself.
      - Admin → Storage: database size on disk, rows per table (activities,
        wellness days, plans, users), and free disk space where the data lives.

- [x] **Admin approves new users.** A third registration mode, "approval",
      next to open and closed:
      - New accounts are created as "waiting for approval" and can't sign in
        yet; the sign-in page says so.
      - Admins get an email per sign-up, and Admin → Users shows them at the
        top with Approve / Reject.
      - The user is emailed when approved, with a link to sign in.
- [x] **"Walk" as a session type** in weekday preferences and plan days (and
      "Hike"), so walks can be planned and the AI coach can suggest them.
- [x] **Email updates for sharing invitations.**
  - The coach is emailed when an athlete invites them, with a link to
    Sharing.
  - The athlete is emailed when the coach accepts or leaves.
  - The coach is emailed when the athlete changes what's shared or stops
    sharing.
  - Each person can turn these off in Profile.
  - Needs email (SMTP) set up.
- [ ] **Training plan page layout like the old hub** (screenshot 25 Oct).
      - A "This week — Week 4" heading above the current week, and the plan
        title and length under the page title ("8-week Old Mutual Wealth
        Double Century plan").
      - Week header: phase badge, dates, then "DRAFT — focus text — review
        and adjust" on one line. Click the focus text to edit it.
      - One row per day: weekday on the left, with a coloured bar showing the
        day's state (rest, done, missed, planned).
      - A narrow column per day holding the type badge (with an icon: Rest,
        Zwift, Road…), the bike under it (e.g. "Trek Domane SLR6"), and
        stacked small buttons: route, MyWhoosh, fits a workout, swap, lock.
      - Indoor days show the MyWhoosh and "fits a workout" buttons (indoor
        workout matching).
      - On the right: the full description, then intensity chips with icons
        (⚡ 95–105% FTP, ❤ Z2), then "✓ Goal met · Logged: 120.7km · 1213m ·
        4h55m · RE 169 · 138W avg · 122bpm avg (Ride)", or "✗ Not logged"
        with the "why missed?" dropdown.
      - Compact, so a whole week fits on one screen.
- [ ] **Multi-platform workout sync (Zwift, MyWhoosh, Intervals.icu).**
      Full spec: [docs/workout-sync.md](docs/workout-sync.md). Coaches build
      structured cycling workouts, schedule them on the athlete's calendar,
      and CoachQuest delivers them to Zwift / MyWhoosh / Garmin where an
      authorised integration allows it, with ZWO file export everywhere
      else.
      - [x] **Phase 1 — working MVP:** review the code, a platform-neutral
        workout model, the graphical workout builder (with templates,
        TSS/IF estimate and preview chart), the training calendar (built on
        the existing plan tracker), ZWO and plan-ZIP export, and the
        Settings → Connected Platforms page.
      - [x] **Phase 2 — integration framework:** provider adapters, a
        background sync queue with retries and history, sync errors shown
        to the athlete, Intervals.icu investigation, tests against mocked
        platform APIs.
      - [x] **Phase 3 — automatic delivery:** AI plans schedule their
        indoor sessions as structured workouts (sent on automatically),
        completion is stored with manual correction, planned vs actual per
        week (also in the AI weekly review). MyWhoosh checked: no usable API
        (the community one needs the athlete's password), but Intervals.icu
        reaches it.
        - [ ] Still open: Zwift's own Training API, only once Zwift approves
          CoachQuest as a partner (Intervals.icu covers Zwift until then).
      - [x] **Closest Zwift / MyWhoosh workout per indoor day.** Shared
        catalog uploaded by admins as .zwo files; each indoor plan day shows
        the closest one on the athlete's preferred platforms with a match
        score, and can swap to it and back. A super admin switch turns it
        off.
      - This replaces the training plan page's "MyWhoosh" and "fits a
        workout" buttons: indoor plan days link to real workouts.
      - Needs from outside: Zwift partner approval; a check of MyWhoosh's
        terms; possibly Garmin's official developer program for sending
        workouts to Garmin.
- [ ] **Edit access for My coaches.** On Sharing → My coaches, choose per
      coach whether each shared item is view only or view and edit (screenshot
      25 Oct). Today "Training plans" lets a coach both view and change plans
      and workouts, and everything else is view only.
      - Per item: View, or View + edit. For example: profile (FTP, threshold
        and max HR, goal), weight, races, training plans and calendar
        workouts, activity notes and types.
      - Default for new and existing coaches: view only, except training
        plans, which keep view + edit so nothing changes for current coaches.
      - The API checks edit rights on every change, not only the buttons.
        Edits made by a coach are recorded in the access log, with what
        changed.
      - The athlete sees who last changed something ("FTP 265 W · set by
        Coach Mike · 2 days ago").
      - The coach is emailed when edit access is given or removed (with the
        existing sharing emails).
- [x] **The real coach has a say in the AI coach.** (Done.) A human coach (with the
      Training plans permission) can give the AI coach input that it must
      follow, so the coach stays in charge of the training:
      - [x] Standing coach instructions per athlete, e.g. "no intervals on
        Mondays", "keep long rides under 4 h until the knee is fine",
        "build towards 300 W FTP by March". The athlete can see them. Done:
        AI coach and Plans tabs; optional end date, pause, emails; every AI
        plan, re-plan, readiness note, weekly review and chat follows them.
      - [x] (Done.) Input per plan and per re-plan: a "Coach's notes" box that goes to
        Claude with the request. Shown on the plan so everyone sees what
        shaped it.
      - [x] Comments on the AI's readiness notes, weekly reviews and calendar
        workouts (and on plans), by the athlete and coaches; the next note,
        review or re-plan takes them into account. Done.
      - [x] (Done; plans and re-plans a coach asks for count as approved.) Coach approval for AI plans: a plan or re-plan the AI writes for a
        coached athlete stays "draft, waiting for coach" until the coach
        approves it, edits it, or sends it back. Only approved workouts go
        to Zwift.
      - [x] (Done with the standing instructions.) In the facts sent to Claude, the coach's instructions rank above the
        AI's own judgement, and the plan says where it followed them. The
        weekly review flags any conflict with the data (e.g. the coach asked
        for more volume but fatigue is flagged) instead of silently
        overruling either.
- [x] **Sign-in log.** See who signed in, when and from where. (Done.)
      - Admin → Sign-ins: every sign-in attempt with user (or the email
        typed), time, result (success, wrong password, waiting for approval,
        locked out / rate limited), IP address and browser. Filter by user,
        result and date.
      - Also logged: sign-outs, "sign out everywhere", password changes and
        resets, and admin actions on accounts.
      - Each user sees their own recent sign-ins in Profile → Security, so
        they can spot one that wasn't them.
      - Admin → Settings: "Keep sign-in log for X days" (e.g. 90 by
        default). Older entries are deleted automatically every night. Applies
        to the coach access log too, unless set separately.
      - Keep it to what's needed (POPIA): no passwords, and IP addresses only
        for as long as the retention allows.
- [x] **Disable an account** (without deleting it). (Done.)
      - Admin → Users → Manage → "Disable": the user is signed out
        everywhere and can't sign in (the sign-in page says the account is
        disabled). "Enable" undoes it. Their data, plans and sharing stay as
        they were.
      - While disabled: no scheduled syncs, AI notes, emails or workout
        sending for that account, and coaches see the athlete as disabled.
      - Optional reason and date, shown to admins; logged (with the sign-in
        log).
      - Users can pause their own account from Profile (same effect, they can
        come back by asking an admin), as a step before deleting it.
      - Admins can't disable themselves or the last admin.
- [x] **Athletes delete activities.** (Done.) In My training → Activities, a
      delete button per activity (and select several to delete at once),
      with "are you sure?". Only the athlete, never a coach.
      - Deleted activities stay deleted: the next Strava / Garmin /
        Intervals.icu sync must not bring them back (keep a small "deleted"
        list of source + id, with an "Undo" / "show deleted" option).
      - Removes the activity from load (CTL/ATL/TSB), volume stats, plan vs
        actual and workout completion, and recalculates them.
      - Never deletes anything on Strava, Garmin or Intervals.icu itself.
- [x] **Download the indoor workout from the plan.** (Done.) On the training plan,
      the workout badge of an indoor day (e.g. "▤ SS 3x10" on Thursday) gets
      a download: the .zwo file for Zwift / MyWhoosh, straight from the plan
      day, also for days before the workout reached the calendar. Plus
      "Download this week's indoor workouts" (ZIP) on each week card.
- [x] **Coach dashboard: all athletes' training week at a glance.** (Done.) One page
      for a coach (My athletes, as a table), a row per athlete with this week:
      - Workouts done / planned, compliance % and time ridden vs planned,
        today's session and whether it's done.
      - Readiness (go / easy / rest), form (TSB), fitness trend, and flags
        (missed sessions, under target, fatigue, sync or delivery errors).
      - Next race and days to go; new comments and unread AI notes.
      - Sort and filter (needs attention first); click through to the
        athlete's calendar, plan or AI coach tab.
      - Shows only what each athlete shares with the coach.
- [x] **Decide: an athlete "memory" for the AI coach** — (Built: Athlete notes, and AI-suggested
      notes a person accepts or dismisses; no hiding from the AI, no emails.) Decision in
      `docs/athlete-memory.md` (26 Oct): yes, as "Athlete notes" (short shared notes per
      athlete with categories and review dates, in the database; then AI-suggested notes
      a person accepts). Waiting for the owner's go-ahead. Original item: (a memory.md per athlete,
      or per coach and athlete). Today the AI coach starts every note, plan and
      chat from facts computed fresh from the data, plus plan comments; it
      remembers nothing else between requests. Check whether that's enough or
      whether it needs standing context:
      - Things the data can't show: injuries and niggles, bike setups, work
        and travel patterns, what motivates the athlete, what worked before.
      - The coach's standing instructions (overlaps "The real coach has a say
        in the AI coach").
      - If yes: store it in the database (not files on the server), one note
        per athlete that the athlete and their coaches can read and edit, with
        a history; the AI may suggest additions ("remember: knee sore after
        long climbs?") that a person accepts. Included in every AI request,
        within the sharing permissions. Covered by account export/delete.
- [x] **Age / birth date from Garmin and/or Strava.** (Done: from Garmin or typed in; Strava's API has no birth date.) Fill the athlete's birth
      date (and so age) into Profile, like weight and thresholds, with "from
      Garmin · date" shown and a manual override.
      - Garmin's user profile has the birth date (user settings). Strava's API
        doesn't seem to include it; check, otherwise Garmin or manual only.
      - Used for age-based estimates (max HR when unknown) and by the AI coach
        (recovery and training load advice). Only shared with coaches under
        "Profile"; never shown on the dashboard.
- [x] **My training: one period switch for the whole page.** (Done.) Choosing 7 / 30 /
      90 days (screenshot 26 Oct) changes only the Volume cards and the
      activity mix today. It should also change:
      - **Weekly elevation:** now always the last 12 weeks. For 7 days show
        elevation per day; for 30 and 90 days, per week over that period.
      - **Wellness:** now always 30 days (sleep, HRV, resting HR, Body Battery,
        steps) — follow the chosen period, with averages for that period.
      - **Training load (CTL/ATL/TSB):** now always 120 days — follow the
        period, keeping enough history before it that the curves are right.
      - One switch at the top of My training (and the coach's athlete view),
        remembered per browser; the chart titles say the period.
- [x] **Skin the site with the CoachQuest logo pack** (Done; a vector/transparent logo would still sharpen the small browser icon.) (Coachquest_Web_Logo_Pack.zip,
      26 Oct). The pack has: the primary logo (white "COACH", blue "QUEST",
      cyclist and runner on mountains, orange arrow, "DREAM IT. TRAIN IT. OWN
      IT."), two hero layouts, a square symbol, favicons (16–512 px, .ico,
      Apple touch icon), Open Graph and Twitter cards, and a web manifest.
      - Favicon, Apple icon and manifest in the page head; theme colour
        `#032440` (navy). Fix the manifest's icon paths (they miss the
        `favicons/` folder) and the name ("CoachQuest").
      - Logo in the sidebar / top bar and on the sign-in, register and
        password-reset pages; the slogan on the sign-in page.
      - Colours from the logo as the site palette: navy background, sky blue
        (`QUEST`, the figures) as the main accent, orange (the arrow) for
        highlights. Dark theme close to the logo; light theme keeps a white
        page with navy and blue accents. Check text contrast and the chart
        colours still read.
      - Social preview (Open Graph / Twitter) for links to
        coachquest.mmc24.com.
      - The artwork is raster only with a navy background (no transparent or
        SVG version): on a light background show it in a navy badge, or get a
        transparent / SVG version made later. Use resized copies, not the
        0.5–0.9 MB originals, so pages stay quick.

- [x] **Date format setting** (Done: Profile → Date format and Time format.) (screenshot 26 Oct). Dates follow the browser's
      language, so the same page mixes formats: "From Garmin, 10/26/2026,
      8:28:05 AM" (US month/day, 12-hour, seconds) next to a birth date of
      "1968/07/01".
      - A profile setting "Date format", e.g. 26 Oct 2026 (default),
        2026-10-26, 26/10/2026 or 10/26/2026, plus 24-hour or 12-hour time.
      - Used everywhere through `lib/format.js` (`dateTime`, `shortDate`,
        and the places that call `toLocaleString()` / `toLocaleDateString()`
        directly), in the user's own timezone; no seconds.
      - Emails and the AI coach's notes use the same format.
      - The browser's date picker (birth date, races, workouts) follows the
        browser's language and can't be restyled; show the chosen format
        next to it, or swap it for our own picker if that looks wrong.

- [x] **Admin: each user's data at a glance.** (Done, except a "reconnect needed" email.) Admin → Users today shows only
      name, email, role, active/approved and when they joined. Add per user:
      - Activities: total, by source (Strava / Garmin / Intervals.icu), first
        and latest activity date; wellness days.
      - Connections: Strava, Garmin and Intervals.icu each with status
        (connected / error / not connected), last sync time and the last error.
      - Workout delivery: queued / failed / blocked sync jobs.
      - Last sign-in, failed sign-ins lately; coaches and athletes shared with;
        plans, races and workouts counts; AI coach use (calls, tokens).
      - Database space per user (roughly), to see who uses the most.
      - Sort and filter (e.g. sync problems first), click a user for a detail
        panel; actions there such as "sync now" or "reconnect needed" email.
      - Admin only, and each view logged like a coach's access.

- [x] **Bug: the 7 / 30 / 90-day switch doesn't work for a coach** (Closed 26 Oct: works after the rebuild.) (26 Oct).
      As a coach, My athletes → an athlete → Overview: choosing a period
      doesn't change the charts. Reproduce with a coach account (shares with
      and without fitness / wellness / activities), check what the page asks
      the API for and fix; add a test for the coach's view.
      - Checked 26 Oct on the current code: as Coach Sam, choosing 7 days
        reloads volume, training load and wellness for 7 days. The switch
        came in with commit a556ca5; the server probably runs an older
        build. Rebuild (`bash build.sh`), then re-check; if it still fails,
        note the athlete and what they share.

- [x] **Admin: AI use per user, with a per-user limit and an off switch** (Done; the 80% email and a token budget are not built.) (26 Oct).
      Mike Nel (mike@mmc24.com) shows 6 AI calls / 28k tokens but has no data
      of his own: he's a coach.
      - Why: the AI use column counts calls by the person who *asked*, not
        whose data it was. A coach generating plans, readiness notes or chat
        answers for an athlete is charged for them. ~4.7k tokens a call is
        normal (instructions + the athlete's facts). Check his calls: which
        athlete, which kind (plan, re-plan, readiness, weekly, chat), and
        whether any were retries or errors.
      - Show it: Admin → Users → Details lists AI calls this month by kind and
        by athlete ("for themselves" vs "for Ann"), with tokens and a rough
        cost; the row says "for others" when most calls are for athletes.
      - Limit it: a per-user monthly limit that overrides the global
        "AI requests per user per month" (Settings), and an "AI off" switch
        that stops all AI calls for that user at once with a clear message
        ("The admin has paused the AI coach for your account"). Logged like
        other admin actions.
      - Optional: a monthly token budget (not only a call count), and an email
        to the admin when someone reaches 80% of their limit.

- [x] **Use fewer AI tokens** (Done: caching, cheaper settings for short jobs, no pointless notes, chat cap, smaller lookups, compact JSON, leaner re-plans, measuring. Old chats' history is left as it is: editing it would break the AI's stored reasoning.) (26 Oct; from a read of coach.py, assessments.py,
      coach_chat.py). Each AI call has a type: plan, re-plan, readiness note,
      weekly review or chat. Roughly in order of savings:
      - **Prompt caching (biggest win).** No call uses it today. The long
        instructions (and the chat's tool list) are the same on every call.
        In a chat, every tool round and every follow-up question resends the
        whole conversation. Cache the instructions and the conversation so
        far: cached input costs about a tenth.
      - **Skip calls that can't help.** The 06:40 readiness note and the
        weekly review run for everyone who switched them on, even with no
        data synced or nothing new since the last note (e.g. a coach-only
        account like Mike Nel). Skip when there's no data or nothing changed.
        Don't write a second readiness note on the same day unless something
        changed (new sleep/HRV data, a new comment).
      - **A smaller model and lower effort for the short jobs.** Everything
        uses the plan model (default Opus, effort "high", up to 32,000 output
        tokens), including a 120-word readiness note. Admin settings for the
        model and effort per type: plans as now; readiness, weekly review and
        chat on a cheaper model or lower effort, with a lower output cap.
      - **Trim long chats.** Each new question resends every earlier answer,
        tool result and thinking block in that chat. Drop or shorten old tool
        results after a few turns, cap the chat's length ("start a new chat
        to keep answers quick"), and use the API's context management to
        clear old tool results.
      - **Smaller tool results.** `get_activities` returns up to 150 full
        activity records, and `get_fitness` up to 365 daily rows. Send only
        the fields the AI needs, and weekly totals beyond ~8 weeks.
      - **Compact JSON.** Facts are sent with `indent=1`. Compact separators
        save roughly 10–20% of the input on plans and reviews.
      - **Re-plans send less.** Cap the comments and the "kept days" list to
        what's still relevant (e.g. the last 4 weeks), and summarise earlier
        weeks instead of listing them.
      - **Measure it.** Log each call's type and its cache read/write tokens
        (the `AiCall` table has neither), and show tokens per type on the
        admin page, so each change above can be checked against real numbers.
        Goes with "Admin: AI use per user".

- [x] **Why did Mike Nel (mike@mmc24.com) make AI calls with no data of his own?** (Done: guard built; Admin → Details → AI → "Latest calls" shows what each was for, old ones matched by time.) (26 Oct)
      Admin → Details shows 6 calls this month: 5 on his own account, and 1 for
      Michael Nel (the athlete he coaches). His account has no Strava, Garmin or
      Intervals.icu connection and no activities, but it does have 1 plan,
      1 race and 1 workout.
      - Find out what the 5 were. Those calls are from before calls had a
        type, so match them by time against his plans, AI notes (readiness
        and weekly) and chats on the server. Most likely he tried the AI coach
        on his own account: a plan for his race, "Check today's readiness",
        or a chat.
      - Guard against it. Before an AI call for an athlete with no synced
        data, say "The AI coach has nothing to go on yet. Connect Strava or
        Garmin first", and don't call the AI. For plans, allow it after a
        clear warning (a plan from just a goal and hours can still be
        useful).
      - The scheduled morning notes already skip accounts without data
        (since 26 Oct).

- [x] **Admin: turn off emails to a user** (Done.) (26 Oct). In Admin → Users → Details,
      a switch "Emails to this user" that stops every email CoachQuest
      would send them (sharing, comments, plan approvals, scheduled AI
      notes), whatever their own Profile switches say.
      - Keep the emails they need to get into their account: password reset
        links (self-service and the admin's) and the sign-up approval email.
        Say so next to the switch.
      - Show "emails off" in the users table and flags; log the change in the
        sign-in log like other admin actions.
      - The user sees in Profile that the admin has turned their emails off
        (their own switches greyed out).

- [x] **Intervals.icu: "Sync now" button** (Done.) (26 Oct). On Connections → Intervals.icu
      (screenshot: only "active", last sync and the three switches today):
      - "Sync now" sends every scheduled workout from today on to
        Intervals.icu again, even unchanged ones (normally skipped), so
        Intervals.icu tells MyWhoosh / Zwift again. Riders report that a
        changed workout is what makes MyWhoosh pick it up. Also runs the
        activity / wellness import when switched on.
      - Shows the result: "4 workouts sent, 0 failed", with any errors, and
        updates "Last sync".
      - Same 5-minute limit as Strava and Garmin "Sync now", so it can't be
        hammered. The API for the import part exists already
        (`POST /api/connections/intervals_icu/sync`); the page has no button
        and the forced re-send doesn't exist yet.

- [x] **Re-plan one day** (Done.) (26 Oct). On a plan day, a "Re-plan this day" button
      next to the comments, so the AI rewrites just that day (and its indoor
      workout) instead of the whole plan from this week.
      - Goes to the AI with the day's comments (e.g. Thu 19 Nov: the athlete
        wanted rest before the race, the coach said "no not"), the days
        around it (so the load still fits the week and the race), the coach
        instructions and athlete notes, and an optional "what should change"
        box.
      - Shows the proposed day next to the current one before saving; follows
        the same approval rule as other re-plans (waits for a coach unless
        switched off).
      - Much cheaper than a full re-plan: one day in, one day out.

- [x] **Athlete may approve when the coach doesn't answer** (Done.) (26 Oct). A plan,
      re-plan or re-planned day waiting for a coach shouldn't block training
      when no coach reacts.
      - After a waiting time (e.g. 48 hours; the coach can choose 24 h,
        48 h, 72 h or "never" on the athlete's Plans tab, next to the
        approval switch), the athlete gets **Approve** / **Send back** too.
      - Before that: a reminder email to the coaches halfway (if their
        emails are on), and the box says when the athlete may decide
        ("you can approve it yourself from Thu 09:00 if your coach hasn't").
      - Race-week safety: if the waiting day is before the waiting time
        ends (e.g. tomorrow's session), the athlete may decide at once.
      - Logged and shown on the plan as "approved by the athlete (no coach
        answer in 48 h)", and the coach is told.

- [x] **AI target CTL from a target finish time.** Races get a Target time
      (h:mm). CoachQuest works out what it takes (power, W/kg, IF and TSS for
      rides; pace for runs), and ✨ asks the AI coach for a target CTL with a
      verdict (realistic / a stretch / unlikely, with a realistic time). A
      suggestion only: "Use" fills in Target CTL.

## Later

- [ ] Account export and delete (POPIA/GDPR), privacy notice and consent text
      on the Sharing page
- [ ] Optional two-factor sign-in (TOTP)
- [ ] Strava webhooks instead of 6-hourly polling
- [x] Coach comments on plans (done: comments on the plan or a day by the athlete
      and coaches with Training plans; anyone there can edit or delete; emails
      with their own Profile switch; re-plans read them)
- [ ] Postgres + Alembic migrations when SQLite gets tight
- [ ] Ask Strava to raise the shared app's athlete limit (if not every user
      brings their own app)
- [ ] Garmin: move to the official Garmin Connect Developer Program before
      offering CoachQuest as a paid service
