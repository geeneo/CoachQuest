# CoachQuest to-do

## Next up

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
- [ ] **The real coach has a say in the AI coach.** A human coach (with the
      Training plans permission) can give the AI coach input that it must
      follow, so the coach stays in charge of the training:
      - Standing coach instructions per athlete, e.g. "no intervals on
        Mondays", "keep long rides under 4 h until the knee is fine",
        "build towards 300 W FTP by March". The athlete can see them.
      - Input per plan and per re-plan: a "Coach's notes" box that goes to
        Claude with the request. Shown on the plan so everyone sees what
        shaped it.
      - [x] Comments on the AI's readiness notes, weekly reviews and calendar
        workouts (and on plans), by the athlete and coaches; the next note,
        review or re-plan takes them into account. Done.
      - Coach approval for AI plans: a plan or re-plan the AI writes for a
        coached athlete stays "draft, waiting for coach" until the coach
        approves it, edits it, or sends it back. Only approved workouts go
        to Zwift.
      - In the facts sent to Claude, the coach's instructions rank above the
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
- [ ] **Disable an account** (without deleting it).
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
- [ ] **Athletes delete activities.** In My training → Activities, a
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
- [ ] **Decide: an athlete "memory" for the AI coach** (a memory.md per athlete,
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
- [ ] **Age / birth date from Garmin and/or Strava.** Fill the athlete's birth
      date (and so age) into Profile, like weight and thresholds, with "from
      Garmin · date" shown and a manual override.
      - Garmin's user profile has the birth date (user settings). Strava's API
        doesn't seem to include it; check, otherwise Garmin or manual only.
      - Used for age-based estimates (max HR when unknown) and by the AI coach
        (recovery and training load advice). Only shared with coaches under
        "Profile"; never shown on the dashboard.

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
