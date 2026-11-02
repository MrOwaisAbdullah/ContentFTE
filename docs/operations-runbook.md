# Operations runbook

What keeps the engine observable and recoverable. Every item below is optional and off until configured; none of
them changes behaviour for an instance that ignores them.

| Concern | What exists | How to turn it on |
|---|---|---|
| Is it answering? | `GET /health` (liveness) and `GET /ready` (database, auth and tenancy checks; 200/503, no secrets) | `.github/workflows/uptime.yml` pings `/ready` every 15 min and posts to Discord. Set repo secrets `ENGINE_BASE_URL` and `DISCORD_WEBHOOK_URL`. |
| Errors | Sentry, scrubbed before sending (no request bodies, cookies, auth headers, or secret-looking strings) | `uv sync --extra monitoring`, then `SENTRY_DSN=...` (`SENTRY_ENVIRONMENT`, `SENTRY_RELEASE`, `SENTRY_TRACES=0`). |
| Request tracing | `X-Request-ID` on every response and log line; `LOG_FORMAT=json` for log shippers | Always on; `LOG_FORMAT=json` to switch format. |
| Things that need a human | Budget exceeded / 90% warning, cadence overdue, readiness failing | `python scripts/alerts_check.py` (schedule it daily); posts to `DISCORD_WEBHOOK_URL`, silent when all is well. |
| Who did it? | Every audit row carries `payload.actor` (`platform` or `site:<slug>/<key label>`) | Always on. |
| Backups | `python scripts/backup_db.py --dir <path> --keep 14` (SQLite online backup, or `pg_dump`) | Schedule it. On Neon also enable point-in-time restore in the project settings. |
| Schema changes | Alembic (`alembic.ini`, `migrations/`); baseline `0001` | `uv sync --extra migrations`. Existing database: `alembic stamp 0001`. New change: add a numbered file in `migrations/versions/`, then `alembic upgrade head`. |
| Secrets in the database | Fernet encryption of WordPress password, IndexNow/Bing keys, Discord webhook, delivery secret | `SECRETS_KEY=...`, then `python scripts/encrypt_site_secrets.py` (see `.env.example`). |
| Site deliveries | A custom-site webhook that fails on publish is queued in `delivery_outbox` and retried (1m, 2m, 4m ... up to 6h, 8 attempts) under the same delivery id; giving up raises a `delivery_failed` alert | Schedule `python scripts/process_outbox.py` every few minutes. |
| Several workers | Publish / generate / stage runs and `Idempotency-Key` replay are single-flight across processes (database leases) | Automatic. |

## Restoring

* **SQLite:** stop the engine, replace the database file with the chosen `contentfte-*.sqlite3`, start it.
* **Postgres:** `pg_restore --clean --if-exists --no-owner --dbname "$DATABASE_URL" contentfte-<stamp>.dump`
  (take a fresh dump first; restore into a scratch database before production if you can).
* After a restore, run `alembic current` - it should print the revision you expect.

## Migrations, in practice

The engine still creates missing **tables** on startup (`init_db`), so a brand-new table needs no migration. A new
**column** on an existing table does not reach an existing database that way - that is what a revision is for.
Write it with `op.add_column(...)`; SQLite is handled by Alembic's batch mode (`render_as_batch` is on).

## Things only you can do

* Create and store `SECRETS_KEY` / `INSTANCES_KEY` outside the repository, and back them up separately from the
  database - losing the key loses the secrets.
* Set the repository secrets above and, in GitHub, move the pipeline secrets into a `master`-only Environment.
* Rotate the Google service-account key (SEC-22).
