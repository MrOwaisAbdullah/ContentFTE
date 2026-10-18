# Per-Instance Connection Isolation

How every external connection is scoped so two instances (sites) cannot
bleed into or interfere with each other. Audited 2026-10-18 during the
Search Console / extended-backfill wave.

## The isolation model

An **instance** = one site = one engine process with its own `.env` and
(often) its own database. The console's instance registry
(`console/lib/instances.ts`) holds `{baseUrl, apiKey}` per instance and
every outbound call resolves its target **per request** from that registry
(`console/lib/engine.ts`) — never from module state. Two instances never
share a process, so process-global state (module caches, singletons) is
per-instance *by construction*.

Within one engine process the DB `Site` row is the per-site identity
(`Site.settings` JSON). Where a process can hold more than one site
(shared mode, `TENANCY_MODE=shared`), the connections below are keyed so
they cannot cross.

## What is isolated (and how)

| Connection | Scoping | Where |
| --- | --- | --- |
| Console → engine | per-request instance registry (baseUrl + apiKey) | `console/lib/instances.ts`, `console/lib/engine.ts` |
| Search Console SA token | cache keyed by credential fingerprint (`_creds_fingerprint`) | `lib/search_console.py` |
| Search Console `sites.list` cache | same fingerprint key — two SAs never share the cached property list | `lib/search_console.py` |
| GSC property per site | `resolve_site_property(base_url, settings)`: `Site.settings.search_console_site_url` wins, else `base_url + "/"` | `lib/search_console.py`, `sdk/service.py::get_search_console_status` |
| gspread client + spreadsheet handle | cache keyed by credential fingerprint | `tools/sheet_tool.py` |
| WordPress publish/refresh/brief-links | `Site.settings["wp"]` = `{base_url, username, app_password}` wins over process `WP_*` env | `sdk/service.py::_wp_config` |
| Tavily spend | metered per `site_id` + month | `lib/tavily_meter.py`, `TavilyUsage` |
| Brand voice | `BrandProfile` row per `site_id` | `lib/db.py` |
| Discord bot / webhook | per-instance env (`DISCORD_BOT_TOKEN`, `DISCORD_WEBHOOK_URL`) — one bot process per instance | `discord_bot/bot.py`, `scripts/run_stage.py` |
| Stage single-flight (`/sdk/v1/run/{stage}`, MCP) | per engine process — instances are separate processes, so the lock never spans instances | `sdk/server.py`, `mcp_server/server.py` |
| DB engine | one `DATABASE_URL` per process (isolation = own DB) | `lib/db.py` |

Credential fingerprint pattern (shared by GSC + gspread): every cached
Google connection is keyed by a hash of the *active*
`GOOGLE_CREDENTIALS` (or `GOOGLE_CREDENTIALS_PATH` file content). If two
instances ever configure different service accounts in one process, each
gets its own token/client/cache slot — the first instance's credentials
are never frozen in for the second.

## Known gaps (shared mode only — not reachable in isolated instances)

These are single-process-per-site safe today; they matter only if
`TENANCY_MODE=shared` is used to serve multiple sites from one engine:

1. **Discord shared-bot routing.** A multi-channel bot filters by
   channel-id allow-list but every data path behind the filter is
   single-store (`discord_bot/bot.py` reaction handler). The design fix —
   guild → `Site.settings.discord_guild_id` routing — is specced in
   `docs/spec-site2-postgres-frontend.md` but not implemented. Do not run
   one bot for two tenants until it is.
2. **Post-id-scoped WP ops** (`wp_post`, `_elementor_client`) resolve
   credentials from env only — the routes carry a WP post id, no article,
   so there is nothing to resolve a site from.
3. **Brand DNA at startup** — `main.py` injects the first site's profile
   into the module-level agents; per-article loading (`art.site_id`)
   belongs with the shared-mode wave.
4. **`SeoCache`** is keyed by `(provider, keyword)` without `site_id` —
   keyword-global data, benign today; add `site_id` if per-tenant SEO
   provider credentials ever land.
5. **`_keyword_claim`** (Sheets mode claim row) has no site dimension —
   Sheets mode is single-site by definition (`SHEETS_ENABLED=0` on
   Postgres-native instances).

Rule of thumb for new connections: read credentials at call time, key
every cache by the credential fingerprint or the site slug, and never
snapshot env into module globals at import time.
