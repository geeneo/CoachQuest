# CoachQuest — Multi-Platform Workout Synchronisation

Spec from the owner, 25 Oct 2026. Tracked in [TODO.md](../TODO.md).
The "How this fits CoachQuest today" section at the end was added when the
spec was filed; read it before starting Phase 1.

## Objective

Extend the existing Coach Quest application to support structured cycling workout creation, scheduling, and synchronisation with Zwift and MyWhoosh.

The goal is for coaches to assign workouts to athletes and, wherever an authorised integration supports it, automatically deliver those workouts to the athlete's connected training platform without manual file uploads.

## 1. Review Existing Project

Before writing code:

- Inspect the existing repository, architecture, frameworks, database schema, authentication, and athlete/coach relationships.
- Reuse existing components, services, styling, and conventions.
- Do not rewrite working functionality.
- Check existing Garmin and Strava integrations to avoid duplicating activity records.
- Produce an implementation plan before making major architectural changes.

## 2. Platform Connections

Add a **Settings → Connected Platforms** section.

Support these integration types:

| Platform | Integration |
|---|---|
| Zwift | Official Training API when approved; ZWO export fallback |
| MyWhoosh | Official integration if available; experimental API behind feature flag |
| Garmin | Reuse existing connection; support workout delivery only where authorised |
| Strava | Reuse existing activity integration |
| Intervals.icu | Investigate supported API and Zwift workout delivery |

For each supported platform display:

- Connection status
- Athlete account identifier
- Last successful sync
- Last error
- Available capabilities
- Automatic synchronisation toggle
- Disconnect and reconnect controls

Use official OAuth flows wherever available. Encrypt credentials and tokens at rest. Never expose platform tokens to frontend code.

Do not collect or store users' platform passwords.

## 3. Workout Builder

Create a graphical workout editor supporting:

- Warm-up and cool-down
- Steady-state intervals
- Repeated intervals
- Recovery intervals
- FTP-based power targets
- Optional cadence targets
- Workout duration
- Estimated TSS and intensity factor
- Workout descriptions and coach instructions
- Workout preview chart

Allow coaches to create reusable workout templates.

Use a platform-independent workout model. Do not store workouts exclusively in Zwift or MyWhoosh formats.

## 4. Training Calendar

Build an athlete training calendar supporting:

- Daily and weekly views
- Drag-and-drop workout scheduling
- Multi-week training plans
- Coach-assigned workouts
- Rest days
- Workout rescheduling
- Workout completion status
- Platform synchronisation status

Workouts should belong to the correct athlete, with explicit coach permissions.

Store dates and times in UTC with the athlete's configured timezone.

## 5. Zwift Integration

Zwift has a restricted Structured Training API requiring partner approval.

Implement a provider abstraction with two modes.

**Mode A: Official API**

When credentials and documentation have been approved and provided:

- Authenticate using the supported partner mechanism.
- Send supported workouts to the correct athlete.
- Schedule, update, and delete workouts where supported.
- Retrieve completion data where permitted.
- Handle rate limits, authentication expiration and errors.

Do not invent Zwift endpoints, authentication flows, or credentials.

**Mode B: ZWO export**

Immediately implement:

- Valid `.zwo` generation
- Export of individual workouts
- ZIP export of complete training plans
- Correctly calculated FTP-relative power targets
- Support for intervals, ramps, recoveries and cadence where the format allows

Provide simple installation instructions for Zwift on Windows.

Clearly distinguish manual export from automatic account synchronisation.

## 6. MyWhoosh Integration

Investigate MyWhoosh's published workout editor and its unofficial community-documented API.

Reference:
https://github.com/mywhoosh-community/mywhoosh-api

Requirements:

- Isolate unofficial API functionality in a dedicated adapter.
- Require explicit athlete authorisation.
- Use a feature flag, disabled by default.
- Verify API permissions and terms before enabling write operations.
- Do not rely on reverse-engineered authentication or bypass platform access controls.
- Implement workout upload, scheduling, updating and deletion only for operations actually verified as supported.
- Provide an export/manual import option if automated integration is unavailable.

Label experimental functionality clearly in the UI.

## 7. Automatic Synchronisation Engine

Implement a background job system.

Trigger synchronisation when:

- A coach assigns a workout.
- A scheduled workout changes.
- An athlete connects or reconnects a platform.
- A workout is cancelled.
- An authorised retry is requested.

Requirements:

- Per-platform sync queue
- Idempotent operations
- Exponential backoff
- Rate-limit handling
- Sync audit history
- Error logging
- Manual retry
- Prevention of duplicate workouts
- External workout ID mapping

Do not silently retry permanent authentication or permission failures.

## 8. Coach and Athlete Experience

**Coach dashboard**

Allow coaches to:

- View connected platforms for authorised athletes.
- Create and assign workouts.
- Build multi-week plans.
- Track workout delivery status.
- Review completed sessions.
- Compare planned and actual performance.

**Athlete dashboard**

Allow athletes to:

- Connect their own accounts.
- Select preferred training platforms.
- Enable or disable automatic workout delivery.
- Review upcoming workouts.
- Download workout files.
- See synchronisation errors.
- Revoke integrations.

The athlete must explicitly authorise third-party account access.

## 9. Activity Synchronisation

Use existing Strava and Garmin activity integrations where possible.

Where supported and authorised, associate completed Zwift or MyWhoosh activities with scheduled workouts.

Avoid duplicates when the same activity arrives through multiple providers.

Use external activity IDs, timestamps, source identifiers and other reliable matching fields.

Show:

- Planned versus actual duration
- Planned versus actual power
- Average and normalised power when available
- Heart rate
- Cadence
- Completion percentage
- TSS and intensity factor when calculable

Do not invent missing activity metrics.

## 10. API and Database

Design appropriate database changes for:

- Platform connections
- Workout definitions
- Workout steps
- Training plans
- Scheduled workouts
- External workout mappings
- Synchronisation jobs
- Synchronisation logs

Create secure internal API endpoints for workout management, calendar scheduling, platform connections, export and synchronisation.

Follow the project's existing backend conventions.

## 11. Testing

Include automated tests for:

- ZWO generation and validation
- FTP power conversion
- Intervals and repeat blocks
- Date and timezone handling
- Coach/athlete access control
- Duplicate prevention
- Sync retries
- Token expiration
- Platform API errors
- Disconnect and revocation
- Exporting full training plans

Use mocked platform APIs for development. Never perform real athlete account mutations during automated testing.

## 12. Implementation Order

**Phase 1 — Working MVP**
1. Review repository.
2. Build canonical workout data model.
3. Implement workout editor.
4. Implement training calendar.
5. Implement ZWO and ZIP export.
6. Create connected-platform UI.

**Phase 2 — Integration framework**
1. Create provider adapters.
2. Implement background sync queue.
3. Implement sync history and error reporting.
4. Investigate Intervals.icu integration.
5. Add provider mock tests.

**Phase 3 — Authorised automatic delivery**
1. Add Zwift official API when approved.
2. Validate MyWhoosh integration feasibility.
3. Implement automatic workout scheduling where supported.
4. Synchronise completion information.
5. Add planned-versus-actual training analysis.

## Acceptance Criteria

- A coach can create and assign a structured workout.
- An athlete can view scheduled workouts.
- A valid `.zwo` file can be exported.
- An entire training plan can be downloaded as a ZIP.
- Platform capabilities and connection status are visible.
- Automatic sync is available only for properly authorised integrations.
- Failed synchronisations are visible and retryable.
- Existing Coach Quest functionality remains operational.

## Important Instructions for Claude Code

Start by inspecting the current codebase and identifying existing functionality.

Do not assume APIs are publicly available.

Do not replace existing working modules.

Use the existing design system and application architecture.

Implement Phase 1 first, then progress through subsequent phases where technically possible.

Clearly report any integration that requires third-party approval or credentials.

At completion, provide a summary of implemented features, migrations, configuration variables, test results and outstanding API dependencies.

---

## How this fits CoachQuest today

Notes from filing the spec, to save the review step some time. Check them
again against the code before building.

- **Plans and calendar already exist.** `Plan.weeks` holds dated weeks and
  days (type, description, duration, intensity chips, gear, route, locked,
  missed reason), tracked against logged activities in
  `backend/app/plan_tracker.py` and shown by `PlanTracker.jsx`. Swap, lock,
  "Apply weekday preferences" and "Re-plan from this week" work on it. The
  calendar (section 4) should extend this, not replace it: a plan day gets
  an optional link to a structured workout.
- **Coach permissions already exist.** Grants with the `plans` scope decide
  who can view and edit an athlete's plans (`require_scope`, logged in the
  access log). Workouts should use the same scope.
- **Activity matching already exists, by date.** `with_actuals` links a plan
  day to the activities logged that day. Section 9 needs a tighter match
  (start time and duration, source and external ID). Strava and Garmin
  activities are kept apart by the per-source sync options in
  `sync_options.py`; Zwift and MyWhoosh rides arrive through Strava or
  Garmin, so they should not be imported a third time.
- **Encrypted tokens already exist.** The `Connection` table and Fernet
  encryption (`TOKEN_ENCRYPTION_KEY`) cover section 2's "encrypt tokens at
  rest". Tokens never go to the frontend today; keep it that way.
- **Background jobs already exist.** APScheduler runs sync and backfill
  (`backfill.py` pauses for rate limits and resumes). Section 7's queue can
  start from that pattern, with a sync-jobs table for history and retries.
- **The FTP is already known.** The profile holds FTP, LTHR and max HR, and
  TSS is already calculated, so workout TSS and IF estimates (section 3) can
  use the same numbers.
- **No timezone yet.** Users have `week_start` but no timezone; section 4
  needs one added to Profile.
- **The AI coach writes plans.** Once workouts exist, the plan schema could
  let Claude describe indoor sessions as structured steps, so AI plans
  export to ZWO too.
- **Third-party dependencies to report:**
  - Zwift's training API needs partner approval; until then it's ZWO export
    only.
  - MyWhoosh has no official public API that we know of; the community API
    stays behind a flag, read-only until its terms are checked.
  - Intervals.icu has a documented API with per-athlete API keys and OAuth
    for apps; worth checking first, as it may be the most practical path
    for delivering workouts to Zwift.
  - Garmin workout delivery uses the Training API from Garmin's official
    developer program; the current Garmin connection is the unofficial
    library.

## Status

### Phase 1 — done (25 Oct 2026)

- **Workout model** (`backend/app/workouts.py`): steps are warm-up,
  cool-down, ramp, steady, recovery, intervals (repeat on/off) and free ride.
  Power is a fraction of FTP, with optional cadence and an on-screen cue per
  step. Validated on save (max 100 steps, 8 hours). Duration, IF and TSS are
  estimated in code: normalised power of the target profile, 30 s rolling
  average. Free-ride time has no target and is left out of TSS. Watts are
  only worked out for display, from the athlete's FTP.
- **Database:**
  - `workouts` is the owner's private library of templates.
  - `scheduled_workouts` holds the athlete's calendar: a copy of the steps,
    the local day, status planned / skipped / cancelled, and who assigned
    it.
  - Steps are stored as JSON on the workout rather than in a separate table.
  - New user columns: `timezone` and `platform_prefs`.
  - The migration runs automatically at start-up.
- **Builder** (Workouts page): the step editor, a live chart and estimate
  computed by the API, starter templates, a reusable library, scheduling for
  yourself or a coached athlete, and .zwo download.
- **Calendar** (Calendar tab on My training and on each athlete):
  - Week and day views, with the plan's session and rest days on each day.
  - Drag a library workout onto a day, or tap it and then tap a day on a
    phone. Drag a workout to reschedule it.
  - Skip, cancel or remove a workout.
  - Status is planned, today, done, partly done or missed. A day's bike
    rides from Strava or Garmin are matched in the athlete's timezone.
  - Planned vs actual: duration, completion %, average and normalised
    power, IF, TSS, heart rate and cadence. Only measured values are shown.
- **Access:** the athlete, and coaches with the "Training plans" scope. A
  coach sees platform status but not error text.
- **Export** (`backend/app/zwo.py`):
  - One .zwo per workout.
  - A ZIP for a week, a day or a whole plan, with install steps for Zwift on
    Windows and Mac.
  - Every download is labelled as a manual file, not account sync.
- **Connected platforms** (Connections page): Zwift, MyWhoosh, Garmin,
  Strava and Intervals.icu, each with status, account, last sync, last
  error, what CoachQuest can do with it, an "I use it" choice, and an
  automatic delivery switch. The switch is refused by the API until an
  authorised integration exists.
- **Timezone:** set in Profile. It decides "today" and which day a ride
  counts on, in the calendar and the plan tracker.
- **Configuration:** `MYWHOOSH_EXPERIMENTAL` (default false). Nothing uses
  it yet.
- **Tests:** `backend/tests/test_workouts.py` covers ZWO structure, FTP
  conversion, interval expansion, the TSS/IF estimate, validation,
  timezones, access control, rescheduling, statuses, plan ZIP and
  platforms.

### Phase 2 — done (25 Oct 2026)

- **Intervals.icu investigation:** Intervals.icu has a documented API and
  is an approved Zwift Training API partner. Workouts planned on an
  athlete's Intervals.icu calendar are uploaded to Zwift (the coming week,
  under Workouts > Custom > Intervals.icu) once the athlete links Zwift in
  Intervals.icu. This gives CoachQuest an authorised automatic route to
  Zwift without its own Zwift partnership. Sources:
  - [Intervals.icu and Zwift integration](https://forum.intervals.icu/t/intervals-icu-and-zwift-integration-is-live/81764)
  - [Intervals.icu OAuth support](https://forum.intervals.icu/t/intervals-icu-oauth-support/2759)
  - [Uploading planned workouts](https://forum.intervals.icu/t/uploading-planned-workouts-to-intervals-icu/63624)
  - [API cookbook](https://forum.intervals.icu/t/intervals-icu-api-integration-cookbook/80090)
- **Intervals.icu adapter** (`backend/app/delivery/intervals_icu.py`):
  - Connects through OAuth with the `CALENDAR:WRITE` scope.
  - Sends each workout as a .zwo file to the events bulk upsert, keyed by
    our own `external_id` ("cq-<id>"). Removals use the bulk delete.
  - Disconnecting revokes the app's access through `disconnect-app`.
  - The token is encrypted at rest and never sent to the browser.
  - Intervals.icu requires OAuth for apps, so personal API keys aren't
    accepted.
- **Provider adapters** (`backend/app/delivery/`): one interface (`upsert`,
  `delete`, `revoke`), with errors classified as transient, rate-limited,
  auth failed, forbidden, rejected or not supported.
  - Zwift (direct) and MyWhoosh adapters exist, but make no calls and enable
    no operations.
  - MyWhoosh is behind `MYWHOOSH_EXPERIMENTAL`. No reverse-engineered login
    is implemented.
- **Sync engine** (`backend/app/sync_engine.py`, tables `sync_jobs`,
  `sync_log` and `external_workouts`):
  - **Triggers:** assign, change, reschedule, skip or cancel, remove,
    connect or reconnect, switching auto-send on, and manual retry.
  - **Queue:** one open job per workout and platform; a burst of edits
    sends once.
  - **Duplicates:** the stable external id prevents them, and a content hash
    skips unchanged sends.
  - **Retries:** transient errors back off 1, 2, 4 … 60 minutes and give up
    after 6 tries. Rate limits wait as long as the platform asks, without
    using up attempts.
  - **Lost authorisation (401/403):** the job is blocked and the connection
    marked "Needs attention". It isn't retried until the athlete
    reconnects; reconnecting re-sends the blocked jobs. Rejected workouts
    wait for a change or a Retry.
  - **Account change:** linking a different Intervals.icu account sends
    everything again.
  - **When it runs:** right after each change, and every minute from the
    scheduler. Jobs left "running" by a restart are re-queued at start-up.
  - **Scope:** only workouts from today on are sent. Workouts already sent
    stay in step even if auto-send is switched off later.
- **History and errors in the UI:**
  - Connections → Connected platforms → Workout delivery shows open jobs
    (with Retry or "reconnect") and the attempt history.
  - Each calendar workout shows where it was sent (✓, retrying, failed,
    reconnect).
  - Coaches with Training plans access can view the history.
- **Settings:** `INTERVALS_CLIENT_ID` and `INTERVALS_CLIENT_SECRET` (or Admin
  → Settings → Intervals.icu). `INTERVALS_BASE_URL` exists only for
  development against `scripts/fake_intervals.py`.
- **Tests:** `backend/tests/test_sync.py` runs against a mocked Intervals.icu
  and makes no real calls. It covers:
  - OAuth (state, missing scope, not configured) and that tokens never
    reach the browser.
  - Upsert, update in place, unchanged changes, cancel and delete,
    coalescing, and past workouts.
  - Backoff and giving up, network errors, rate limits, and 401 blocking
    until reconnect.
  - Rejected workouts, disconnect and revocation, account change, coach
    access, the Zwift and MyWhoosh adapters doing nothing, and account
    deletion.

### Phase 3 — done (25 Oct 2026), except Zwift's own API

- **Zwift official Training API (mode A): not started, on purpose.** It needs
  partner approval, and its endpoints and authentication come with it.
  `delivery/zwift.py` stays a stub that makes no calls. Intervals.icu, an
  approved Zwift partner, already delivers to Zwift.
- **MyWhoosh feasibility: checked, not feasible directly.**
  - The [community API](https://github.com/mywhoosh-community/mywhoosh-api)
    describes itself as unofficial documentation. It logs in with the
    athlete's MyWhoosh email and password, and MyWhoosh hasn't endorsed it.
    Collecting platform passwords is ruled out, so it stays off and enables
    no operations.
  - Intervals.icu users report that it puts the coming week's planned
    workouts into MyWhoosh when MyWhoosh is linked there
    ([forum](https://forum.intervals.icu/t/mywhoosh-integration/79532)).
    Ramps in ERG mode and cadence targets reportedly don't carry over.
  - So MyWhoosh is reached through the Intervals.icu adapter, and the
    Connected platforms page says so.
- **Automatic scheduling from plans** (`backend/app/plan_workouts.py`):
  - The AI coach's plan schema gives each "Zwift / indoor" day a structured
    workout, using a step format mirroring `workouts.py`. Invalid steps are
    dropped, and the day keeps its text.
  - Creating, re-planning, editing a day, swapping days or applying
    preferences reconciles the calendar from today on. Plan workouts are
    created, updated or removed, then queued for delivery.
  - A plan workout edited or moved by hand stops being managed. Re-plans
    leave it alone and don't duplicate that day.
  - Deleting a plan removes its upcoming managed workouts.
  - The plan form has an option to switch this off.
- **Completion** (`backend/app/completion.py`; columns `activity_id`,
  `match`, `plan_id`, `plan_managed`, `plan_day` on `scheduled_workouts`):
  - The ride that completed a workout is stored.
  - Automatic matching:
    - A bike ride on the local day.
    - Prefers the ride named like the workout (Zwift and MyWhoosh name
      rides after it), then indoor rides, then the closest length.
    - One ride completes one workout.
  - The athlete can pick the ride by hand (from the day before to the day
    after), mark the workout "not done", or hand it back to automatic
    matching.
  - Strava/Garmin duplicates were already merged.
- **Planned vs actual** (`backend/app/compliance.py`,
  `GET /api/athletes/{a}/compliance`):
  - Per workout: completion (ridden vs planned time), normalised power vs
    plan, TSS, heart rate, and flags (short, under or over target by more
    than 10%).
  - Per week: done, partly done, missed and skipped; time and TSS planned
    vs actual; and compliance %.
  - Shown under the calendar, and given to the AI weekly review as
    `workout_compliance`.
  - Limited by sharing permissions: ride details need Activities, planned
    watts need Profile.
- **Tests:** `backend/tests/test_phase3.py` (12 tests), covering:
  - the strict plan schema;
  - plan workouts, including invalid and switched-off ones;
  - day edits, swaps, re-plans with hand edits, plan deletion, and delivery
    of plan workouts;
  - name-based matching, manual pick, "not done" and auto;
  - compliance and its scopes, and the weekly review facts.

### Setting up Intervals.icu (once, by the admin)

1. Sign in to intervals.icu and apply for an app at
   https://intervals.icu/oauth/apply. Use the redirect URL
   `https://coachquest.mmc24.com/api/connections/intervals/callback`.
2. Once the app is approved, copy the Client ID and secret from
   intervals.icu/settings/apps into Admin → Settings → Intervals.icu.
3. Each athlete:
   - Clicks Connect on Intervals.icu and ticks "Auto-send workouts".
   - In Intervals.icu, opens Settings → Zwift and links their Zwift
     account.
   - Keeps their FTP the same in CoachQuest, Intervals.icu and Zwift.

### Still depends on others (as of Phase 3)

- **Zwift:** Training API partner approval (Mode A).
- **MyWhoosh:** an official API, or a check of the community API's terms.
- **Garmin:** the official developer program, for sending workouts.
- **Intervals.icu:** approval of CoachQuest's OAuth app (until then
  "Connect" can't complete).
