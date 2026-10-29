# Moving CoachQuest from SQLite to Postgres (and back)

CoachQuest runs on SQLite by default: one file, `data/coachquest.db`. It can also run on
Postgres, in its own container next to the API. Moving copies every table into Postgres with
`app.movedb`, which only **reads** the SQLite file. The file stays exactly as it was, so going
back is one line in `.env`.

Plan about 15 minutes. The site is down for a minute or two while the data is copied, so
nothing is written halfway through. Run everything as root in your CoachQuest folder (where
`.env`, `deploy.sh` and `data/` are).

## 1. Prepare (site stays up)

1. **Update and rebuild.** This image has the Postgres driver and the copy tool:

   ```bash
   bash deploy.sh
   ```

2. **Make a password** for the database (letters, digits, `-` and `_` only, since it goes in a URL):

   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

   Add it to `.env`:

   ```
   POSTGRES_PASSWORD=the-password-you-just-made
   ```

   Leave `DATABASE_URL` as it is for now (`sqlite:////data/coachquest.db`).

3. **Back up SQLite** (menu option 7, or):

   ```bash
   mkdir -p backups && sqlite3 data/coachquest.db ".backup 'backups/before-postgres.db'"
   ```

4. **Start Postgres** and wait until it says `healthy`:

   ```bash
   set -a; source .env; set +a
   docker compose -p "$COMPOSE_PROJECT" -f docker-compose.yml up -d db
   docker compose -p "$COMPOSE_PROJECT" -f docker-compose.yml ps db
   ```

   Its data lives in `./pgdata` (or `PG_DATA_PATH` in `.env`).

## 2. Copy (site down for a minute or two)

Use the same terminal as step 4 above: it loaded `.env`, which the commands below need
(`$COMPOSE_PROJECT`, `$POSTGRES_PASSWORD`). In a new terminal, first run `set -a; source .env; set +a`.

1. **Stop the API**, so nothing is written while copying:

   ```bash
   docker compose -p "$COMPOSE_PROJECT" -f docker-compose.yml stop api
   ```

2. **Copy.** The source is the SQLite file from `DATABASE_URL`; the target is Postgres:

   ```bash
   docker compose -p "$COMPOSE_PROJECT" -f docker-compose.yml run --rm --no-deps api \
     python -m app.movedb --to "postgresql+psycopg://coachquest:${POSTGRES_PASSWORD}@db/coachquest"
   ```

   It lists each table with "copied of read", then ends with
   **"Row counts checked: the target matches. The source wasn't changed."**
   It may also list a few things "Fixed on the way" (text longer than its column, links to
   rows that were deleted). SQLite allowed those; Postgres doesn't. If it says
   **CHECK FAILED** or stops with an error, don't switch: start the API again
   (`bash deploy.sh backend`) and you're still on SQLite. Send me the output.

3. **Switch.** In `.env`, keep the old line as a comment and add the Postgres one, with the
   password written out (not `${...}`):

   ```
   # DATABASE_URL=sqlite:////data/coachquest.db
   DATABASE_URL=postgresql+psycopg://coachquest:the-password-you-just-made@db/coachquest
   ```

4. **Start it on Postgres.** `deploy.sh` now also starts the `db` container:

   ```bash
   bash deploy.sh backend
   ```

5. **Check:**
   - sign in;
   - open My training, a plan, Routes;
   - Admin → Storage says "Postgres database coachquest".

## 3. Backups on Postgres

`bash backup.sh` (menu option 7) makes `backups/coachquest-pg-<date>.sql.gz` with
`pg_dump`, keeping the last 14. **Menu option 10** turns a nightly backup at 02:17 on or off:
it adds or removes one line in root's crontab, makes a backup straight away to test, and logs
each run to `backups/backup.log`. The menu shows whether it's on and the latest backup.

To restore one into an empty database:

```bash
gunzip -c backups/coachquest-pg-DATE.sql.gz | docker compose -p "$COMPOSE_PROJECT" -f docker-compose.yml exec -T db psql -U coachquest coachquest
```

Keep `.env` safe too. Its `TOKEN_ENCRYPTION_KEY` unlocks the Strava, Garmin and Intervals
links in any backup.

## Going back to SQLite

**A. Right after switching** (nothing important happened on Postgres yet): put the old line back
in `.env` and redeploy. The SQLite file is exactly as you left it in step 2.

```
DATABASE_URL=sqlite:////data/coachquest.db
```

```bash
bash deploy.sh backend
```

Anything written while on Postgres (new rides synced, plans, comments) isn't in that file. New
rides sync again from Strava, Garmin and Intervals.icu; other changes are lost. If they matter,
use B.

**B. Keeping what happened on Postgres:** copy Postgres back into a new SQLite file, then use that.

```bash
docker compose -p "$COMPOSE_PROJECT" -f docker-compose.yml stop api
docker compose -p "$COMPOSE_PROJECT" -f docker-compose.yml run --rm --no-deps api \
  python -m app.movedb --from "postgresql+psycopg://coachquest:${POSTGRES_PASSWORD}@db/coachquest" \
  --to sqlite:////data/coachquest-from-postgres.db
```

Then in `.env`:

```
DATABASE_URL=sqlite:////data/coachquest-from-postgres.db
```

```bash
bash deploy.sh backend
```

Postgres keeps its data in `./pgdata` until you delete that folder, so you can switch again later.

## Portainer

If you run the stack from Portainer instead of `deploy.sh`, add
`COMPOSE_PROFILES=postgres` to the stack's environment variables, so the `db` service starts too.
