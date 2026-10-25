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

### What to import from where

Each connection has its own import choices on the Connections page:

- **Strava:** activities.
- **Garmin:** activities and wellness.

A common setup is activities from Strava and wellness only from Garmin. That
is the default when Garmin is linked after Strava.

- **Switching a type off** stops importing it and hides what was already
  imported from that source. Load numbers and AI plans update straight away.
  You're also offered the option to delete that data.
- **Switching a type back on** backfills it on the next sync.
- **Activities on from both sources:** an activity that both sources have,
  starting within 10 minutes of each other, is shown once, as the Strava copy.

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
in `DATA_PATH` (default `./data`).

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

- Account export/delete, password reset by email, optional TOTP 2FA
- Postgres + Alembic migrations when SQLite gets tight
- Strava webhooks instead of 6-hourly polling
- Plan → calendar: turn the AI plan into dated workouts and track plan vs actual
- Coach-to-athlete comments on plans
