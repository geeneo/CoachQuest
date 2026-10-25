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
