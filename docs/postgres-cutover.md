# Postgres switch (DATABASE_URL)

Everything that reads/writes content — the engine, SDK routes, operator
console, Discord worker and the stage scripts — goes through `lib.db`, which
stores in whatever `DATABASE_URL` points at:

- unset → local sqlite `./contentfte.db` (dev/test default, zero setup)
- `postgresql+psycopg://...` → Postgres (Neon free tier works; spec:
  `docs/spec-site2-postgres-frontend.md`)

Swapping is: **create the database → move your data → point the URL → restart.**
The console needs no changes (it only talks to the engine over HTTP).

## 1. Create the database

Create a database (e.g. a Neon project) and copy its connection string. Keep
the `+psycopg` driver marker — that's the Python driver this project installs:

```
postgresql+psycopg://user:pass@ep-xxx.region.aws.neon.tech/contentfte?sslmode=require
```

## 2. Move your local data (fresh installs can skip)

The live store is `contentfte.db`; the one-shot copy preserves primary keys
(so `cost_ledger` / `audit_log` article links stay intact) and advances the
Postgres id sequences afterwards:

```powershell
# dry run first if you like; the target can be the same URL from .env
python scripts/copy_sqlite_to_postgres.py --dry-run `
  --target "postgresql+psycopg://user:pass@.../contentfte?sslmode=require"
python scripts/copy_sqlite_to_postgres.py `
  --target "postgresql+psycopg://user:pass@.../contentfte?sslmode=require"
```

Re-running is safe — rows merge by primary key, so it's a no-op that also
propagates edits made after the first copy. Run it against a *fresh*
database; a target that already holds different rows with the same unique
keys (e.g. a Google-Sheets backfill) would collide — that legacy path is
`scripts/backfill_postgres.py`, not this script.

## 3. Point everything at it

Add to `.env`:

```
DATABASE_URL=postgresql+psycopg://user:pass@.../contentfte?sslmode=require
```

Optional, for a Sheets-free instance (spec §3):

```
SHEETS_ENABLED=0            # stage scripts write DB/direct, no sheet writes
STORE_READ_SOURCE=postgres  # stage reads come from the DB, not the sheets
```

Restart the engine (and any stage workers). First boot runs
`Base.metadata.create_all` — additive, never destructive.

## 4. Verify

Against a **throwaway** database (the test writes and cleans up its rows):

```powershell
$env:TEST_PG_URL='postgresql+psycopg://.../contentfte-test?sslmode=require'
uv run python -m pytest tests/test_postgres_smoke.py -q
```

That runs the real cycle on PG: copy a seeded sqlite store in (sequences
reset), then list sites, copy an article over, submit + approve a new one
(id beyond the copied max — proves no sequence collision), record a stage
run, read the logs.

Then boot the engine and spot-check with the console:

```powershell
uv run uvicorn main:app --port 8123
curl -H "X-Site-Key: $env:SDK_MASTER_KEY" http://127.0.0.1:8123/sdk/v1/sites
```

## Notes

- Images do not move into the database — `meta.images` rows store file
  paths. On a server, set `IMAGE_STAGING_DIR` to a persistent volume
  (default is the OS temp dir, which is wiped on reboot); publish/refresh
  re-upload from it.
- sqlite remains the default for dev/test whenever `DATABASE_URL` is unset,
  so the unit suite needs no database server.
- The copy script's source defaults to `sqlite:///./contentfte.db` (repo
  root); point `--source` elsewhere if your file lives elsewhere.
