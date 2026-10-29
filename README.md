# CoachQuest

A self-hosted, multi-user training portal. Athletes link **Strava** and
**Garmin Connect**, choose which **coaches** can see which parts of their data,
and coaches (or the athletes themselves) use **Claude** as an AI coach to write
training plans from that data.

It grew out of the single-user "Mike Training Hub" (see `docs/TAKEOUT_MikeTrainingHub.md`) and
keeps its stack: FastAPI + SQLite, React + Vite, nginx, Docker on a home server
via Portainer.

## How it fits together

```
 browser ──HTTPS──▶ proxy (nginx + built SPA)            ──▶ api (FastAPI, uvicorn, 1 worker)
                     │  /api/auth/login|register  public       │  SQLite in /data
                     │  /api/*  ── auth_request /_auth ──────▶ │  /internal/auth/verify
                     │            200 → add X-Auth-User-Id     │  scheduler: Strava 6h, Garmin 2×/day
                     │            401 → stop at nginx          │  Anthropic API (key server-side)
                     │  /internal/*  → 404                     │
                     └  /*  → SPA (React Router)               └  Strava / Garmin APIs
```

### Access control: authentication in the reverse proxy

nginx is the authentication layer. The API itself publishes no port.

1. On login the API creates a server-side session and sets an `HttpOnly`,
   `SameSite=Lax` cookie (`Secure` when `COOKIE_SECURE=true`). The database
   stores only a SHA-256 hash of the token.
2. For every `/api/*` request except login/register/logout/health, nginx runs
   `auth_request /_auth`, which calls the API's `/internal/auth/verify` with the
   cookie. Invalid or expired session → nginx answers `401` and the request
   never reaches the API.
3. On success nginx forwards the request with `X-Auth-User-Id` (from the
   verify response) and `X-Proxy-Secret`. Any `X-Auth-*` header the client
   sent is overwritten.
4. The API trusts `X-Auth-User-Id` only when `X-Proxy-Secret` matches
   `PROXY_SHARED_SECRET`, so a request that bypasses nginx carries no identity.
5. `/internal/*` is not routable from outside (`404`).

Also in the proxy: rate limits (login/register 10/min per IP, AI plans 6/min,
API 20/s), security headers (CSP, `X-Frame-Options`, `nosniff`), and a 1 MB
body cap. On writes the API also requires `X-Requested-With: CoachQuest`, a
CSRF guard that a cross-site form or a fetch without CORS preflight can't
satisfy.

HAProxy can do the same job. The equivalent there is an `http-request lua` or
SPOE auth call to `/internal/auth/verify`, then `http-request set-header` for
the two headers. Use nginx unless you already run HAProxy.

### Authorization: what a coach may see

Athletes grant a coach any combination of these scopes (Sharing page):

| Scope | Gives access to |
|---|---|
| `activities` | Activity list (name, sport, time, distance, HR, power, TSS) |
| `fitness` | CTL / ATL / TSB curve and weekly volume |
| `wellness` | Garmin sleep, HRV, resting HR, Body Battery, stress, steps |
| `profile` | FTP, lactate threshold HR, max HR, goal |
| `weight` | Body weight (separate because it is more personal) |
| `plans` | View plans and generate new ones with the AI coach |

- An invitation is `pending` until the coach accepts. Only an `active` grant
  gives access.
- The athlete can change scopes or revoke at any time, and the coach can
  leave. The check runs on every request, so changes apply immediately.
- The AI coach only gets the profile numbers and weight when those scopes are
  granted. Without `profile` it plans from the data alone.
- A missing scope returns `404`, not `403`, so a coach can't probe user ids.
- Every read by someone other than the athlete is written to an access log,
  which the athlete sees on the Sharing page.

### Sharing with friends (view only)

Besides a coach, an athlete can share with a friend: Sharing → Share my data
→ "A friend (view only)", picking what to share like for a coach. The friend
accepts and finds the athlete under My athletes → Friends sharing with me.
Friends only look: every change is refused ("View only"), they can't approve
plans or comment, get no coach emails, and don't count as the athlete's
coach (so the athlete's plans don't wait for approval because of them).
Their looks go in the athlete's "Who looked at my data" log.

### Strava API app: shared or per user

Strava needs an API app (Client ID + Client Secret). There are two ways to set
it up:

- **Per user (recommended for small groups).** Each user creates their own app
  at strava.com/settings/api, with Authorization Callback Domain set to your
  CoachQuest host. They paste its Client ID and Secret on their Connections
  page. Every personal app allows its owner, so nobody waits for Strava to
  raise the athlete limit.
- **Shared.** The admin enters one app under Admin → Settings → Strava. Users
  without their own app use it. A new app allows only 1 athlete until Strava
  approves more.

A user's own app wins over the shared one. Secrets are stored encrypted and
never shown again. Tokens only refresh with the app that issued them, so after
switching apps a user disconnects and connects Strava again (the page says so).

Admin → Users shows which app holds each Strava link (shared, own, or an old
app that is no longer set up). Usage shows how many users are on the shared app.
A user on the shared app with no sign-in for 30 days is flagged "idle on shared
Strava app": ask them to disconnect or move to their own app to free the slot.

### Alpha notice for new users

Off by default; only super admins can switch it (Admin → Settings → Accounts →
"Alpha notice for new users", or `ALPHA_NOTICE=on`). When on, the sign-up page
says CoachQuest is an alpha version and access is subject to approval, and
everyone who signs up gets a welcome email saying the same (needs Email set up).
It only informs: whether sign-ups wait for approval is still decided by
Registration and "Super admin approves new sign-ups".

### Admin access to athletes' data

Off by default. Admin → Settings → Accounts → "Admins can view athletes' data"
turns it on: Admin → Users then has a "View data" link that opens the athlete's
pages read only. Every look is written to the athlete's "Who looked at my data"
log, like a coach's. Changing anything for an athlete still needs a sharing
grant. Check the Strava API Agreement before turning this on (see below).

### Super admins and approving sign-ups

Super admins are admins with one extra job: when Admin → Settings → Accounts →
"Super admin approves new sign-ups" is on, everyone who signs up waits until a
super admin approves them under Admin → Users. Only super admins are emailed
about new sign-ups, and only they can approve or reject them. Off by default;
with it off, Registration (open / approval / closed) works as before.

The `SUPER_ADMIN_EMAILS` accounts (or, when that's empty, the `ADMIN_EMAILS`
accounts) are super admins; a super admin can make other admins super admins
under Admin → Users → Details. Only a super admin can change that setting, or
change, disable, delete or reset the password of another super admin.

### Several sessions a day

Profile → Weekday preferences takes up to three session types a day (e.g.
Zwift / indoor + Strength, or Walk + Strength); Rest stands alone. The AI
coach plans every one of them that day as its own session: the main one
(which carries the structured indoor workout) and extra sessions under it,
which can be edited, removed or added on the plan. A super admin sets the
limit (1 to 4) under Admin → Settings → Workouts → "Sessions per day".

### Strength training

Profile → **Strength training** sets the athlete's equipment (bodyweight,
bands, dumbbells, kettlebells, barbell, gym machines, …), level, sports
(cycling, running), sessions a week, minutes and limits. On Strength days the
AI coach writes a structured session from an exercise library: sets, reps,
effort and rest per exercise, periodised (heavy legs and hips twice a week in
base and build, plyometrics for runners, once a week to maintain in race
season, clear of key sessions), following Rønnestad & Mujika (2014) and the
2022 Sports Medicine – Open meta-analysis on heavy vs plyometric training.
Plan days list the exercises; click one for its instructions.

The library is the public-domain [Free Exercise DB](https://github.com/yuhonas/free-exercise-db)
(Unlicense): 806 strength, plyometric, powerlifting and stretching
exercises in `backend/app/data/exercises.json`, built by
`scripts/import_exercises.py`. Their start and end photos, shrunk to 400 px
WebP (1,606 photos, ~15 MB), are in `backend/app/data/exercise-images/`, built
by `scripts/import_exercise_images.py`. Where those photos first came from
isn't documented, so a super admin can hide them all at once (Admin → Settings
→ Workouts → Exercise photos); the muscle map (our own drawing) stays. The AI gets a shortlist that fits the athlete's equipment
and level (legs, hips, trunk and back, a share per group).

### Favourite routes & segments

On the Plans tab, an athlete (or their coach) keeps favourite Strava routes
(whole rides: the long-ride loop, the recovery spin) and segments (climbs
and stretches for hill repeats and efforts). Add one by pasting its Strava
link, or with **From my Strava**, which lists the athlete's starred segments
and their (public) routes. With Strava linked, length, gradient, climbing
and estimated time come from Strava. Each favourite gets uses (hill repeats,
intervals, endurance, long ride, recovery…) and notes.

The AI coach gets them as `favourites` and plans rides on them: a route for
outdoor rides whose length and purpose fit (setting the session's time from
it), a segment for hill repeats and efforts, or the same efforts indoors
with the place named. Plan days show it as a 🗺 / ⛰ link to Strava, and the
day editor can set or clear it.

### Workout library

Workouts → Library: 90 structured bike workouts written for CoachQuest, open to
every user, in ten collections (recovery & endurance, tempo, sweet spot,
threshold, over-unders & race efforts, VO2 max, anaerobic & sprints, short &
sharp, cadence & skills, tests). Power is a share of FTP, so each fits any
athlete. Search, filter by collection and length, then put a workout on your
own or an athlete's calendar, save a copy to My workouts to change it, or
download the .zwo (Zwift: custom workouts folder; MyWhoosh: Workout Builder →
Upload). Scheduled workouts go to Intervals.icu (and on to Zwift / MyWhoosh)
like any other.

Plans use it too: an indoor plan day with no close Zwift / MyWhoosh workout
(or an athlete with no platform picked) shows the closest library workout
with its match score, and "Use this" swaps it in; "Back to the plan's
workout" undoes it. Same super admin switch as platform matching.

The library lives in `backend/app/library.py` as code, so it is reviewed like
code and the same on every server; each workout is checked against the steps
format when the module loads.

### Matching Zwift / MyWhoosh workouts

Neither Zwift nor MyWhoosh lets another app search its workouts, so admins
keep one shared catalog: Admin → Platform workouts, upload .zwo files per
platform, a .zip full of them (Zwift's own ZIP of its legacy workouts works),
or paste a link to a .zwo or .zip for the server to download (public
addresses only, 25 MB at most). "Use Zwift's official workouts ZIP" fills in
the link to the ZIP Zwift posted on its forum (Workout Refresh, October 2023):
about 1,270 rides, with their Zwift collection names. MyWhoosh workouts download as .zwo too.
CoachQuest doesn't crawl fan sites such as What's on Zwift or mywhooshinfo.com:
both block automated access. Each upcoming indoor plan
day then shows the closest catalog workout on the athlete's preferred
platforms (Connections) with a match score, comparing length, intensity and
the work efforts. "Use this" swaps the day's workout for it (the calendar and
Intervals.icu follow); "Back to the plan's workout" swaps back. Athletes only
see the workout's name; the files stay on the server.

A super admin can switch it off under Admin → Settings → Workouts → "Match
plan workouts to Zwift / MyWhoosh". Days already swapped keep their workout.

The catalog list on Admin → Platform workouts is grouped by collection
(collapsed), with search, platform and length filters, and bulk delete: tick
workouts or whole collections, then "Delete selected", or "Delete collection".
Uploading and importing are under "Add workouts".

### News & guides

A **News & guides** page for posts about CoachQuest: news (what's new) and
how-to guides (connecting Strava / Garmin, Intervals.icu to Zwift and
MyWhoosh, MyWhoosh, the training calendar). Admins write them in Markdown
with a live preview, publish or unpublish them, and set the order of guides;
everyone signed in reads the published ones. A fresh install starts with
those guides and a "What's new" post as drafts, to check and publish.

### AI coach tab

All AI features follow one rule: CoachQuest computes the facts and decisions,
and Claude writes the words. Only data the viewer may see goes in.

- **Daily readiness.** Code decides go / easy / rest from last night's HRV,
  resting HR, sleep and Body Battery against the athlete's own 30-day
  baseline, plus TSB. Claude explains the verdict and adjusts today's planned
  session.
- **Weekly review.** Covers last week's plan vs actual, volume, load,
  wellness vs the week before, notes, races and progress. Saved week by
  week.
- **Progress.** CTL trend, bests and projected CTL at the next race against
  its target. No AI involved.
- **Ask the coach.** A chat where Claude looks data up through tools.
  - Each tool checks the viewer's scope and writes the access log.
  - Conversations are stored server-side exactly as sent, thinking blocks
    included.
- **Automatic notes.** Each athlete can opt in to daily readiness (06:40
  UTC) and a Monday weekly review, optionally by email.
- **Cost control.** Admin → Settings → "Monthly AI calls per user", with
  per-user usage on the Admin page.

### What to import from where

Each connection has its own import choices on the Connections page:

- **Strava:** activities.
- **Garmin:** activities and wellness.

**Where activities come from** (top of the Connections page): the athlete
picks one *main activity source* (Strava, Garmin or Intervals.icu). When a
session is on several platforms, the main source's copy is the one shown. Each
other connected source has "Also import activities that are only on …", for
sessions that never reach the main source (e.g. walks or strength recorded on
a Garmin watch only). Until a main source is picked the card is highlighted
and asks for it. A new connection only imports activities when no other source
does yet. Wellness, weight and thresholds are chosen per connection as before.

- **Switching a type off** stops importing it and hides what was already
  imported from that source. Load numbers and AI plans update straight away.
  You're also offered the option to delete that data.
- **Switching a type back on** backfills it on the next sync.
- **Duplicates are shown once.** Two activities of the same kind (any two
  rides count as one kind) are one session when they start within 10 minutes
  of each other or overlap for at least half of the shorter one. That catches
  a ride from both Strava and Garmin, and a ride uploaded twice to the same
  source (e.g. by Zwift and a Garmin head unit). The main activity source's
  copy is shown (without one picked: Strava, then Garmin, then Intervals.icu);
  within one source the copy with power, then elevation, then the longer one.
- **Remove duplicates** (under Recent activities, or Admin → Users → Details)
  deletes the hidden copies for good. They go to Deleted activities (Undo
  works) and the next sync doesn't bring them back.

### AI coach

`POST /api/athletes/{id}/plans` builds a JSON "facts" document in code:

- profile and request
- load numbers (CTL/ATL/TSB, ramp) and weekly volume
- the last 14 days of activities
- wellness averages
- **readiness flags** (high fatigue, fast ramp, suppressed HRV, raised resting
  HR, short sleep)

**Only the scopes the requester holds go in.** Claude
(`ANTHROPIC_MODEL`, default `claude-opus-5-5`) writes the plan in Markdown. The
facts are saved next to the plan, so anyone can see exactly what the model was
given. The key stays on the server. Calls use streaming and a server-side
refusal fallback (`fallbacks: "default"`). Only metadata (model, status,
latency, tokens) is logged; prompt and response text are not.

## Running it

### Server (Docker + Portainer)

```bash
git clone <repo> /data/coachquest && cd /data/coachquest
cp .env.example .env     # fill it in, see below
bash build.sh            # builds coachquest-api and coachquest-proxy images
docker compose -p coachquest up -d     # or paste docker-compose.yml into Portainer as a stack
```

Fill in `.env` (it is gitignored, never commit it):

- `PUBLIC_BASE_URL`: the HTTPS URL users open, e.g. `https://coach.example.com`.
- `PROXY_SHARED_SECRET`:
  `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`
- `TOKEN_ENCRYPTION_KEY`:
  `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
  **Back this key up separately from the data.** Without it the stored
  Strava/Garmin tokens can't be decrypted. With it, a stolen backup can be.
- `STRAVA_CLIENT_ID` / `STRAVA_CLIENT_SECRET`: from
  <https://www.strava.com/settings/api>. Set *Authorization Callback Domain* to
  the host of `PUBLIC_BASE_URL`.
- `ADMIN_EMAILS`: these accounts get the Admin page. Needed for the first
  admin only.
- `SUPER_ADMIN_EMAILS` (optional): these accounts are super admins. Empty:
  the `ADMIN_EMAILS` accounts are.

Everything else can be set on the **Admin page** in the web UI instead of
`.env`:

- Anthropic API key, model and effort, with a *Test key* button
- Strava client ID and secret
- registration open/closed
- which users are admins or disabled

Values saved there override `.env` and take effect without a restart. They
are stored encrypted with `TOKEN_ENCRYPTION_KEY`, so a copy of the database
alone doesn't reveal them. Secrets are write-only: the page shows only their
last 4 characters.

`PROXY_SHARED_SECRET`, `TOKEN_ENCRYPTION_KEY` and `PUBLIC_BASE_URL` always stay
in `.env`. The app and nginx need them before anything else can start.

Put TLS in front of port `APP_PORT`: a Cloudflare Tunnel, Caddy/Traefik, or
certificates added to the nginx config. Then turn on the HSTS line in
`nginx/templates/default.conf.template`.

Day-to-day: `bash deploy.sh [all|backend|frontend]`, or `bash menu.sh` for
version check, logs, backups (rotated, keeps 14) and cleanup. All state lives
in `DATA_PATH` (default `./data`): SQLite by default, or Postgres in its own
container. [docs/postgres.md](docs/postgres.md) moves the data across with
`python -m app.movedb` (the SQLite file is only read) and back again.

Tests run on SQLite; `TEST_DATABASE_URL=postgresql+psycopg://...` runs them on
an empty Postgres database.

### Development

```bash
cd backend && python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q && ruff check .

cd frontend && npm install && npm test && npm run build
```

The backend tests include a fake nginx (`tests/conftest.py`) that performs the
`auth_request` step. To run the UI against a real stack, start the compose
stack and run `npm run dev`; Vite proxies `/api` to the nginx container on
`localhost:3040`.

## Repository layout

```
backend/app/
  main.py          app wiring, CSRF guard, scheduler, admin endpoints
  config.py        settings from env, fails fast on missing secrets
  db.py            models: User, Session, Connection, Activity, WellnessDay, Grant, Plan, AccessLog, AiCall
  security.py      scrypt passwords, session tokens, Fernet encryption
  deps.py          identity from proxy headers + scope checks
  fitness.py       pure TSS / CTL / ATL / TSB / flags math (unit tested)
  coach.py         facts builder + Claude call
  providers/       strava.py (OAuth), garmin.py (garminconnect, MFA)
  routers/         auth, connections, grants, athletes, plans
frontend/src/      React Router app: pages/, components/, hooks/useApi.js, lib/
nginx/templates/   proxy config (envsubst at container start)
docker-compose.yml build.sh deploy.sh menu.sh .env.example
```

## Before you go live: compliance notes

- **Strava API Agreement.** Read the current agreement before onboarding other
  people. Things to check:
  - It limits showing a user's Strava data to other users.
  - It limits using the data with AI/ML.
  - It requires deleting data on disconnect. CoachQuest already does this.
  - New apps get a low athlete-count limit until Strava reviews them.

  Get Strava's written OK for the coach-sharing and AI-coach use case, or
  limit what other people see to data from Garmin and manual entry.
- **Garmin.** `garminconnect` is an unofficial client that logs in as the
  user. That's fine for you and a few friends. For a service you sell, apply
  to the Garmin Connect Developer Program (Health/Activity API) and swap out
  `providers/garmin.py`.
- **Personal data (POPIA/GDPR).** Health data is special personal
  information. You need:
  - a privacy notice and consent wording on the Sharing page
  - a way to export and delete an account
  - a written data-retention rule
- **Anthropic.** The AI coach sends athlete data to the Anthropic API. Say so
  in the privacy notice.

## Next steps

See [TODO.md](TODO.md).
