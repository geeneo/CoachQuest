# Takeout — Mike Training Hub

A portable summary of this project: what it is, how it's built, how it's
deployed, and which pieces are worth reusing on the next idea. Hand this file
to a new repo or a new Claude session as the starting context.

Snapshot taken 2026-10-25 at commit `149b146`. 53 commits since 2026-09-28.

---

## 1. What this project is

A self-hosted personal cycling training dashboard. It pulls activities from
Strava and wellness data from Garmin Connect into SQLite, computes a
training-load model (CTL/ATL/TSB), manages a 15-week training plan with
plan-vs-actual tracking, and uses Claude for an AI Coach and a Race
Predictor. It runs as three Docker containers behind Nginx, deployed with
Portainer on a home server.

## 2. Stack

| Layer | Choice | Notes |
|---|---|---|
| Backend | FastAPI (Python 3.12), uvicorn | `backend/main.py` wires routers and the scheduler |
| Scheduling | APScheduler (`AsyncIOScheduler`) | Strava every 6h, Garmin 09:00/18:00, athlete auto-sync 07:30 |
| Storage | SQLite via SQLAlchemy 2 + plain JSON files | DB for time series, JSON for config users edit |
| HTTP client | httpx | Strava, Anthropic, weather |
| Frontend | React 18 + Vite 5, Recharts, lucide-react, react-markdown | No router library; page switch is `useState` in `App.jsx` |
| Styling | Single `index.css` with CSS variables, dark theme | Off-canvas sidebar under 768px |
| Proxy | Nginx | `/api/*` → API, `/` → static SPA |
| Deploy | Docker images built on the server, Portainer stack | Host port 3030 |
| AI | Anthropic Messages API, proxied through the backend | Key kept server-side, never sent back to the browser |

## 3. Repository layout

```
backend/
  main.py              app wiring, scheduler, in-memory sync log, /api/manage/* deploy endpoints
  database.py          SQLAlchemy models (Activity, FitnessSnapshot, GarminDaily, …)
  strava.py            Strava sync + CTL/ATL/TSB
  garmin.py            Garmin Connect sync (garminconnect/garth, MFA code support, token cache)
  secrets_store.py     secrets saved from the Settings page into /data/secrets.json (don't reuse, see section 5)
  routers/             one router per domain: activities, fitness, plan, race, garmin,
                       workouts, mywhoosh, ai, integrations, weather, gear
frontend/
  src/App.jsx          page switch
  src/components/      Sidebar, AssessmentText (markdown renderer for AI output), WeeklyNotice
  src/hooks/useApi.js  tiny fetch hook: { data, loading, error }
  src/lib/             pure helpers (session types, weather rules, terrain checks, hill repeats)
  src/pages/           one file per page
nginx/nginx.conf       reverse proxy config (copied to /data/strava/nginx/default.conf)
build.sh               first-time server setup + image build
deploy.sh              git pull + rebuild + recreate containers
menu.sh                interactive server admin menu (pull, rebuild, logs, backups, cleanup)
portainer-stack.yml    the production stack
data-templates/        seed JSON (races.json)
```

## 4. Patterns worth reusing

These carry over to most self-hosted, single-user apps.

1. **Self-updating deploy from the browser.** The API container mounts the
   git checkout (`/data/<app>`) and `/var/run/docker.sock`, and its image
   includes the Docker CLI plus the compose plugin, copied from `docker:cli`
   rather than installed with apt. `/api/manage/pull`, `rebuild-backend` and
   `rebuild-frontend` run `git pull`, `docker build` and
   `docker compose -p <project> -f portainer-stack.yml up -d --no-deps <svc>`.
   - Gotcha: `docker restart` keeps the old image. Use `compose up` with the
     **same project name Portainer used**, or you get a second, disconnected
     copy of the stack.
2. **Build stamping.** `BUILD_COMMIT`/`BUILD_TIME` build args become env vars
   in the API, and `VITE_BUILD_COMMIT` gets baked into the frontend.
   `/api/admin/version` reports what's actually running, which can differ
   from what's on disk.
3. **Settings come from the environment.** Every credential and setting
   that changes per deployment is read from an env var, loaded from a
   `.env` file that is never committed. See section 5. (This repo also lets
   you save secrets from the Settings page into `/data/secrets.json`. Don't
   carry that over: secrets end up in a plain-text file inside the data
   folder and its backups.)
4. **Server-side LLM proxy.** The browser builds the prompt and POSTs it to
   `/api/ai/...`. The backend adds `ANTHROPIC_API_KEY` from its env, calls Anthropic, and
   logs the model, latency and status. The key never reaches the client.
5. **Logic in code, prose from the LLM.** Recent commits move decisions
   (status badges, emojis, road vs MTB, rep counts) out of prompt
   instructions and into deterministic code. Claude writes the narrative,
   and code decides the facts. Keep doing this.
6. **Config as plain JSON files on a bind mount.** Easy to edit by hand,
   easy to back up, no migrations. SQLite holds only the high-volume time
   series.
7. **Scheduled syncs plus a manual "sync now" button** and an in-memory
   sync log shown on the Admin page.
8. **`menu.sh`.** One interactive script for day-to-day server admin:
   version check (local vs remote vs running image), pull/rebuild, logs,
   backups with rotation, and disk cleanup.
9. **Frontend minimalism.** No state library and no router. `useApi(path)`
   plus one page component per screen kept a 25-page app manageable.

## 5. Secrets and configuration: everything in `.env`

Rule: **no password, token, API key or account ID goes in code, docs,
compose files or JSON config.** Each one is an env var. The real values
live only in a `.env` file on the server (or in Portainer's stack
environment variables), and `.env` is in `.gitignore`.

Commit a `.env.example` that lists the variable names with blank values:

```dotenv
# App
APP_NAME=
APP_PORT=
DATA_DIR=/data
DATABASE_URL=sqlite:////data/app.db

# Strava (https://www.strava.com/settings/api)
STRAVA_CLIENT_ID=
STRAVA_CLIENT_SECRET=
STRAVA_REFRESH_TOKEN=
ATHLETE_ID=

# Garmin Connect
GARMIN_EMAIL=
GARMIN_PASSWORD=

# Anthropic (used by the backend only)
ANTHROPIC_API_KEY=

# Git access on the server, if HTTPS is used instead of an SSH deploy key
GIT_TOKEN=
```

How to wire it up:

- **Compose / Portainer:** give each service `env_file: .env`, or list
  `KEY=${KEY}` under `environment:` and fill the values in Portainer's
  "Environment variables" panel. Never type a value into the YAML.
- **Backend:** read with `os.getenv("KEY")` (`python-dotenv` is already a
  dependency for local runs). Fail at startup with a clear message if a
  required key is missing.
- **Frontend:** never put a secret in a `VITE_*` variable. Vite bakes those
  into the public JS bundle, so anyone who opens the site can read them.
  Only non-secret values (like `VITE_BUILD_COMMIT`) go there.
- **Shell scripts:** `build.sh`, `deploy.sh` and `menu.sh` start with
  `set -a; source .env; set +a` so the app name, paths and port come from
  one place.
- **Git on the server:** use an SSH deploy key. If you must use HTTPS, pass
  `GIT_TOKEN` through a credential helper, never inside the remote URL.
- **Settings page:** show whether each key is set (masked), but don't make
  it editable. Changing a secret means editing `.env` and recreating the
  container.

## 6. Deployment recipe (copy for a new app)

1. On the server: `git clone <repo>`, `cp .env.example .env`, fill in
   `.env`, then `bash build.sh`. Here that's
   `/data/strava` (data) and `/data/strava-training-hub` (git checkout). It seeds the
   Nginx config, and builds the `<app>-api` and `<app>-frontend` images.
2. In Portainer: Stacks → Add Stack → paste `portainer-stack.yml` → Deploy.
   Images use `pull_policy: never` because they're built locally.
3. To ship changes: `bash deploy.sh [frontend|backend|all]`, or use the
   Deploy page in the app.
4. Back up the data directory (`/data/strava`). It holds all the state.

For the next idea, rename `strava-*` in `portainer-stack.yml`, `build.sh`,
`deploy.sh`, `menu.sh` and `nginx.conf`, and pick a new host port.

## 7. Lessons learned

- Hardcoded names are spread across scripts (`strava-api`, `COMPOSE_PROJECT`,
  paths). Next time, put them in `.env` and have every script source it.
- `App.jsx` switches pages with a hand-rolled `useState`, so there are no URLs
  or deep links. Add a router (or hash routing) from day one.
- Some pages grew past 1,000 lines (`WeekPlan`, `Admin`, `Settings`,
  `AICoach`). Split them into components early.
- No tests and no CI. Even a smoke test for the pure `lib/` helpers and the
  CTL/ATL math would have caught regressions.
- **Never commit credentials or data.** See sections 5 and 8.

## 8. Security cleanup needed in this repo

- `README.md` (section "Deploy token") contains a **GitHub personal access
  token** in plain text. (Not copied here.) Revoke it at
  github.com → Settings → Developer settings → Tokens, then remove it from
  the README. It stays in git history, so treat it as compromised.
- `data/strava.db` is tracked by git even though `.gitignore` lists `data/`
  and `*.db`. It contains personal activity data. Remove it with
  `git rm --cached data/strava.db`.
- `.env.example` and `docker-compose.yml` hardcode the Strava athlete ID.
  Leave the value blank in the example file.
- Credentials saved through Settings sit in plain text in
  `/data/secrets.json` and `/data/anthropic_key.json`, and so in every
  backup. Move them to `.env` and delete those files.
- Use SSH deploy keys or a fine-grained token on the server instead of
  embedding a token in the remote URL.

## 9. Starter checklist for the new idea

- [ ] New repo, copy `backend/Dockerfile`, `frontend/Dockerfile`,
      `nginx/nginx.conf`, `build.sh`, `deploy.sh`, `menu.sh`,
      `portainer-stack.yml`, `frontend/src/hooks/useApi.js`
- [ ] `.gitignore` for `data/`, `.env`, `*.db` **before** the first commit
- [ ] Commit `.env.example` (names only, blank values); keep `.env` on the server only
- [ ] Every secret, ID, port and path read from env, in the backend, compose files and scripts
- [ ] No secrets in `VITE_*` variables
- [ ] Router in the frontend from the start
- [ ] Minimal test + CI workflow
- [ ] If using Claude: reuse the `/api/ai` proxy pattern, keep the key
      in the backend's env, and put the facts in code
