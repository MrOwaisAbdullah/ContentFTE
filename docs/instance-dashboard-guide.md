# Instance, Search Console, Discord & dashboard env guide

Operator runbook for adding a brand-new site to an existing ContentFTE
deployment: creating the instance in the console dashboard, wiring Search
Console, the Discord bot, and the env vars the dashboard reads. Complements
`docs/service_setup.md` (raw credentials) and `docs/site-onboarding-flow.md`
(article lifecycle).

## 1. Concepts

- **Instance** = one engine process with its own `.env` and (usually) its own
  DB. The console dashboard holds a registry of instances (`baseUrl` + `apiKey`)
  and routes every call per-request (`console/lib/instances.ts`).
- **Site** = a row in the engine DB (`Site` table) keyed by `slug`, with
  `site_type` (`wordpress` | `custom`), `base_url`, and `settings` JSON.
- **Search Console property** = per-site, resolved from `Site.settings.search_console_site_url`
  or derived from `base_url + "/"`.
- **Discord** = one bot process per instance (own token + webhook).

## 2. Create a new instance in the dashboard

### 2a. Env-declared (read-only in the UI)

Set `CONSOLE_INSTANCES` in the console's env (JSON array):

    CONSOLE_INSTANCES=[{"name":"acme","baseUrl":"https://engine.acme.com","apiKey":"..."}]

Or the single-instance fallback:

    ENGINE_BASE_URL=https://engine.acme.com
    ENGINE_API_KEY=...

Env entries show up as `env` origin in the Instances page and cannot be
edited/removed from the UI (edit the env instead).

### 2b. UI-managed (file-backed)

Instances page -> "Add instance": name, baseUrl, apiKey. Stored in
`instances.json` next to the console (origin `file`). Editable/removable from
the UI. Env entries win on a name collision.

### 2c. Engine side (per instance)

Each instance runs its own engine process with its own `.env`:

    DATABASE_URL=postgresql+psycopg://...   # or sqlite for dev
    SDK_MASTER_KEY=<shared secret matching console apiKey>
    API_KEY=<engine auth>

Provision the DB schema once (`lib/db.py` init_db / `create_all`) and run
`scripts/migrate_lean_schema.py` if upgrading an older DB.

## 3. Connecting Search Console (one service account, many properties)

1. In Google Cloud (the SA's project), enable the **Search Console API** once.
2. In each property's Search Console: Settings -> Users and permissions ->
   add the service-account email (`...@...iam.gserviceaccount.com`) as
   **Restricted** (the UI may show "Email not found" for @gserviceaccount.com
   addresses - that is a UI bug; the add still works).
3. Set `GOOGLE_CREDENTIALS` (full JSON, single line) in the instance's env.
   The same SA serves every property; caches are keyed by a credential
   fingerprint, so two SAs in one process never share a cache slot.
4. Optional override: set `Site.settings.search_console_site_url` to a
   URL-prefix (`https://example.com/`) or domain property (`sc-domain:example.com`)
   when the derived `base_url + "/"` is wrong. Otherwise it is derived.
5. Verify: `GET /sdk/v1/search-console` (or MCP `contentfte_search_console`,
   or the GSC column on the console Sites page). Status is tri-state:
   `connected: true/false/null` (null = API could not be asked, never a false
   "disconnected").

## 4. Discord bot (per instance)

1. Create a Discord application + bot in the Discord developer portal; copy
   the bot token.
2. Set in the instance's env:
   - `DISCORD_BOT_TOKEN` - the bot token
   - `DISCORD_WEBHOOK_URL` - channel webhook for stage notifications
   - `DISCORD_GUILD_ID` / channel allow-list as needed
3. Deploy the bot container (`discord_bot/Dockerfile` copies only `bot.py` -
   the bot has no filesystem access to `brain/`; that is why review feedback
   lives in Sheets/DB, not files). One bot process per instance.
4. The bot appends approve/reject decisions to the `review` worksheet (and,
   after this wave, the DB `review_feedback` table via the engine). Do not
   run one bot for two tenants (shared-bot routing is not implemented).

## 5. Dashboard env reference

Console (`console/`):
- `CONSOLE_INSTANCES` / `ENGINE_BASE_URL` / `ENGINE_API_KEY` - instance registry
- `CONSOLE_SESSION_SECRET` (or equivalent) - auth cookie signing

Engine (per instance `.env`):
- `DATABASE_URL` - Postgres (Neon) or sqlite for dev
- `SDK_MASTER_KEY` - must match the console's apiKey for that instance
- `API_KEY` - engine auth
- `GOOGLE_CREDENTIALS` - Sheets + Search Console SA
- `GEMINI_API_KEY`, `OPENROUTER_API_KEY` - LLMs
- `TAVILY_API_KEY`, `SERPAPI_KEY`, `PEXELS_API_KEY`
- `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` (optional)
- `SANITY_PROJECT_ID`, `SANITY_DATASET`, `SANITY_API_TOKEN`,
  `SANITY_DEFAULT_AUTHOR_ID`, `SANITY_DEFAULT_AUTHOR_NAME`
- `WP_BASE_URL`, `WP_USERNAME`, `WP_APP_PASSWORD`, `WP_RENDER_TARGET` (WP sites)
- `DISCORD_BOT_TOKEN`, `DISCORD_WEBHOOK_URL`
- `SHEETS_ENABLED` - keep 1 until cutover sealed (dual-write stays active)

## 6. Verification checklist

- Instances page lists the new entry and switching works (cookie `console_instance`).
- Sites page shows the new site with a GSC status (connected/true/false/null).
- `GET /sdk/v1/search-console` returns the property list for that site.
- Discord bot responds in its channel and logs an approve/reject to `review`.
- A test article runs briefed -> drafted -> approved (with note) -> published.

## See also

- `docs/service_setup.md` - full credential table + Google Sheets setup
- `docs/site-onboarding-flow.md` - article lifecycle (briefed/drafted/approved/published)
- `docs/instances-isolation.md` - per-instance connection scoping + known gaps
- `docs/postgres-cutover.md` - Neon cutover runbook
- `docs/dev-log.md` - change history
