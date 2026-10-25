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
- [ ] **Fill Profile from Garmin and/or Strava.** A "Pull from…" button per
      field (FTP, lactate threshold HR, max HR, weight), with a choice of
      Garmin, Strava or manual. Optionally keep it in sync on every sync.
      - Weight from Garmin is done. FTP, LTHR and max HR are still to do
        (`get_cycling_ftp`, `get_lactate_threshold`, `get_heart_rate_zones`).
      - Strava has FTP and weight only when the athlete set them there. It
        needs the `profile:read_all` scope, so Strava users reconnect once.
      - Show where each value came from and when, e.g. "FTP 265 W · Garmin ·
        3 days ago".
      - When FTP or LTHR changes, recalculate TSS (Save already does this).
- [ ] **My training: volume summary** (like the old hub's Volume stats).
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
- [ ] **My training: Recent activities table** (like the old hub).
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
- [ ] **Races / event plan** (like the old hub's Races table, but per user and
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
- [ ] **Training preferences: weekday riding preferences.** One row per day
      (Mon–Sun), choose one or more: Rest, E-MTB, MTB, Road, Hill repeats,
      Zwift / indoor, Treadmill run, Outdoor run, Race. Other sports can be
      added. The AI coach reads this when planning (it replaces the plan
      form's "training days"). Option to apply it to weeks already planned.
- [ ] **Training preferences: activity note tags.** Each user manages their
      own preset tags for the Recent activities "Note" dropdown: illness,
      mechanical, travel, weather, adventure, group, solo, wind, work, other…
      Add, rename (click a tag), remove. The AI coach reads tagged activities
      as explained (e.g. a light week marked "illness" is disclosed, not a
      gap in training).
- [ ] **AI coach: assessments of wellness and training progress.** A new
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

## Later

- [ ] Account export and delete (POPIA/GDPR), privacy notice and consent text
      on the Sharing page
- [ ] Optional two-factor sign-in (TOTP)
- [ ] Strava webhooks instead of 6-hourly polling
- [ ] AI plan → calendar of dated workouts, with plan vs actual
- [ ] Coach comments on plans
- [ ] Postgres + Alembic migrations when SQLite gets tight
- [ ] Ask Strava to raise the shared app's athlete limit (if not every user
      brings their own app)
- [ ] Garmin: move to the official Garmin Connect Developer Program before
      offering CoachQuest as a paid service
