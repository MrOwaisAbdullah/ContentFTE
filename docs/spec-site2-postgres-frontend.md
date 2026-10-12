# Spec — Site #2 (WordPress): direct Postgres, separate free-tier keys, operator console

Status: **in progress** (2026-10-12) — §4b tenancy switch (`TENANCY_MODE`, `lib/site_env.py`,
shared-mode slug guard, `scripts/provision_tenant.py`, Discord channel-list) landed;
**Phase 1** (site identity env-ified, 12 files) landed; **Phase 2 slice 2a** (the
`SHEETS_ENABLED=0` gate: `lib/site_env.sheets_enabled()`, loud failure at
`tools/sheet_tool.get_gspread_client`, keyword-tool pointer to the SDK brief
endpoint) landed. **Phase 4 engine backing landed**: `GET /sites/{slug}/queue`,
`GET /sites/{slug}/brief` (read-only), `PATCH /articles/{id}/content`,
`POST /run/{stage}` — the console's REST surface is complete; **console UI landed**
(`console/` Next.js app: login/session, dashboard, queue, articles list/detail
with edit + approve/publish/refresh, stage triggers — §7 Q1–Q6 answered 2026-10-12).
**Phase 3 is console-driven** (user decision 2026-10-12): instance registry +
header switcher (`CONSOLE_INSTANCES`), Sites screen, Provision wizard that
generates the instance env + optional site-row creation — all landed.
Remaining: site-#1 flip (gated on live `verify_cutover.py` drift report);
live provisioning of instance 2 needs the user's new accounts (Neon #2, WP,
Gemini/Cloudflare/Tavily/OpenRouter keys — the wizard's checklist).
Supersedes the "second Google instance + sheet provisioning" approach discussed
earlier the same day: the user decision is **direct Postgres** — site #2 has no
Google Sheets at all.

## 0. Decisions (locked)

| # | Decision |
| :-- | :--- |
| D1 | **Two instances, one codebase.** Site #2 = separate process + separate env file + separate provider accounts. No in-process multi-tenancy (TASKS Phase 2 item "Multi-tenancy + site isolation" stays deferred). |
| D2 | **Postgres direct for site #2 — no Sheets.** This work completes the Sheets→Postgres cutover (TASKS "cutover step 2 flip" + "Postgres migration complete; Sheets retired"). Site #1 flips only after a clean live drift report (`scripts/verify_cutover.py`); until then site #1 stays on dual-write. |
| D3 | The frontend is an **internal operator console** (approve/view/edit/run) — allowed now per TASKS Phase 2 rule ("minimal internal run console"). NOT allowed: customer dashboard, auth/product accounts, billing, white-label. |
| D4 | Frontend consumes the existing **`/sdk/v1` REST surface** (`sdk/server.py`) via the existing plain-fetch client (`sdk/contentfte.ts`). No new protocol. |
| D5 | **Two tenant provisioning modes, one switch `TENANCY_MODE`** (`isolated` \| `shared`, default `isolated`): site #2 today = `isolated` (own DB + own provider envs); future tenants may be `shared` (new `Site` row in the **platform DB**, provider envs shared with the primary instance — the SaaS shape, which runs `shared`). `scripts/provision_tenant.py` provisions either. |

## 1. Why Sheets are not needed for site #2

- The SDK service layer is already Postgres-native: `upsert_site`, `list_articles`,
  `get_brief`, `get_article` (`sdk/service.py`), and `docs/tool-parity-sanity-sheets.md`
  §B concluded Sheets were fully replaced by Postgres + the service layer (B1–B6).
- What still touches Sheets today is the **legacy agent pipeline** (`scripts/run_stage.py`
  ~16 write sites + `tools/sheet_tool.py`): keyword claims, brief/article persistence,
  the approve stamp Discord reacts to, and telemetry worksheets (parity §B8).
  Phase 2 below gates all of it behind one switch.
- Approve already has a DB-capable path: `POST /sdk/v1/articles/{id}/approve`
  (`sdk/server.py:163`). The console uses this instead of a sheet cell.
- Free-tier multiplication still holds for the rest: **Gemini (per API key),
  Cloudflare Workers AI (per account), OpenRouter (per account), Tavily (per key)**.
  Google is only needed later if site #2 wants GSC features.

## 2. Phase 1 — De-hardcode site-#1 constants (prerequisite)

Introduce `lib/site_env.py` with env reads, **defaults = site #1** (zero behavior
change for the current instance):

| Constant | Env var | Default |
| :-- | :-- | :-- |
| `SITE_BASE_URL` | `SITE_BASE_URL` | `https://owaisabdullah.dev` |
| `SITE_HOST` | derived | `owaisabdullah.dev` |
| `SITE_PREFIX` | derived | `{base}/blog/` |
| `SITE_URL` (GSC property) | `SEARCH_CONSOLE_SITE_URL` optional override | `{base}/` |
| `AUTHOR_PROFILE_API_URL` | optional override | `{base}/api/profile` |

Wire into (inventory 2026-10-12):

| File | Spots |
| :-- | :-- |
| `lib/link_validator.py` | 9–10 (`SITE_HOST`, `SITE_PREFIX`) |
| `lib/search_console.py` | 23 (`SITE_URL`) |
| `discord_bot/bot.py` | 107 (`SEARCH_CONSOLE_SITE_URL`) |
| `tools/sheet_tool.py` | 826 (internal-link regex) |
| `lib/sanity_adapter.py` | 180, 1231 (absolute internal URLs) |
| `tools/tools.py` | 176 (`AUTHOR_PROFILE_API_URL`); 851/887/950/1038 (house image prompt brand/domain) |
| `lib/image_vision.py` | 208 (house-style check text) |
| `blog_agent/blog_agents.py` | 92, 177, 237, 347, 351, 362, 437, 496 (link rules/examples in prompts) |
| `blog_agent/posting_agent.py` | 233 (post URL template) |

Note: prompt strings contain braces (`{{real-slug}}`) — do not naively f-string;
use a build-time replace of the domain token or explicit concatenation.
`_theirprompt.py` is never staged (standing rule).

Deliverable: `.env.example` gains the new keys; full pytest stays green.

## 3. Phase 2 — Postgres cutover completion (sheets-off mode)

Goal: the whole pipeline runs with Sheets **off**; queue + articles + approvals
live in Postgres only. Site #2 gets this from day one; site #1 flips after the
drift gate (TASKS "cutover step 2 flip" / "Postgres migration complete").

| Step | Work | State |
| :-- | :-- | :-- |
| 3a Read path | `STORE_READ_SOURCE=postgres` already exists (`lib/store.py:43,296–301`); rewire `run_stage`/agent queue reads (`list_briefable`, `list_generated_posts`, `find_generated_post`, `keyword_set`) off the switch | API done; flip pending |
| 3b Write path | Gate every sheet write in `scripts/run_stage.py` + `tools/sheet_tool.py` behind one env `SHEETS_ENABLED` (default `1`). When `0`: claim → `keyword_ledger.status`; brief → `Article.meta.brief`; content → `Article.content_md` (+scores/faqs); approve → `Article.status`; no `worksheet.update`/`append_row` | not started |
| 3c Approve flow | Console (and Discord, if kept) call `POST /sdk/v1/articles/{id}/approve` instead of writing the `Approve/Disapprove` cell | REST exists |
| 3d Telemetry (§B8) | `model_usage`/`image_logs` worksheets: when sheets off, skip (no new DB tables in v1) | decision: skip |
| 3e Site #1 flip gate | Run `scripts/backfill_postgres.py`, then `scripts/verify_cutover.py` until clean; only then set site #1 env `STORE_READ_SOURCE=postgres` | TASKS open item |

Out of scope here: Postgres schema redesign (TASKS open question "Postgres schema
approved" — review `lib/db.py` before any ALTER; current schema suffices for v1).

## 4. Phase 3 — Provision instance #2 (console-driven)

Provisioning is driven from the operator console (user decision 2026-10-12:
"instance manage should also be done using frontend"), not from hand-edited
env files or scripts. The console gains three things:

1. **Instance registry + switcher.** `CONSOLE_INSTANCES` env on the console
   (JSON array `[{name, baseUrl, apiKey}]`; when unset the registry is the
   single instance from `ENGINE_BASE_URL`/`ENGINE_API_KEY`). The header
   switcher sets a `console_instance` cookie (name, validated against the
   registry); every engine call resolves through it. One console manages
   site #1's instance, site #2's instance, and any future one.
2. **Sites screen.** Per selected instance: list sites (type/base_url) and
   create/upsert a site row via existing `POST /sdk/v1/sites`.
3. **Provision wizard** (`/provision`). Collects slug, name, site type,
   base URL, WP username + app password, optional SDK key (server-generated
   on request), then:
   - **Generates the instance's `.env`** for the second process — every key
     in the table below, secrets left as paste-here placeholders except the
     SDK key the operator asked the wizard to generate. Downloadable;
     never stored by the console.
   - Optionally **creates the Site row** on the currently selected instance
     (for an already-running engine).
   - Shows the remaining manual checklist (Neon project, provider
     accounts, process start) with per-step copy.

Manual steps that stay human (external accounts): second Neon project →
`DATABASE_URL`; new Gemini / OpenRouter / Cloudflare / Tavily accounts →
their keys; the WordPress site itself (WP admin + Application Password).

Key inventory the wizard emits (from the decision tables above):

1. **DB**: second Neon project (free tier) → `DATABASE_URL` in instance-2 env.
   Dev fallback: local `contentfte.db` (sqlite) as today.
2. **Site row**: `upsert_site(slug, name, site_type="wordpress", base_url=…)`
   (now also possible from the console Sites screen);
   WP creds stay env-driven (`WP_BASE_URL`/`WP_USERNAME`/`WP_APP_PASSWORD` — already
   supported, `lib/wordpress.py:45`).
3. **Instance-2 env** (generated by the console `/provision` wizard):

   | Group | Keys |
   | :-- | :-- |
   | Engine | `API_KEY`, `TENANCY_MODE=isolated`, `DEFAULT_SITE_SLUG`, `DATABASE_URL`, `SHEETS_ENABLED=0`, `STORE_READ_SOURCE=postgres`, `SDK_CORS_ORIGINS` |
   | WordPress | `WP_BASE_URL`, `WP_USERNAME`, `WP_APP_PASSWORD` |
   | Models | `GEMINI_API_KEY` (new account), `OPENROUTER_API_KEY` (new account), model envs per TASKS model-fleet rules |
   | Images | `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` (new Workers account) |
   | Research | `TAVILY_API_KEY` |
   | Optional | `INDEXNOW_KEY`, GSC creds, Sanity creds (not needed for WP push) |
   | Site branding | `SITE_BASE_URL`, `SITE_PREFIX`… (Phase 1) |
   | Ops | `DISCORD_WEBHOOK_URL` (new webhook) |

4. **Run**: second checkout/copy of this repo on the same machine (or its own VPS/Dokploy
   service), `uvicorn`/`run_stage` with the instance-2 env. Follow
   `docs/site-onboarding-flow.md` §1 (WordPress flow) + §5 (minimal e2e).

## 4b. Deployment modes — the `TENANCY_MODE` switch (isolated vs shared)

We must support **both** tenant shapes and pick per instance with one env var
(implements D5). `lib/site_env.py` owns the mode (`tenancy_mode()` /
`is_shared_mode()`, read at call time).

| | `TENANCY_MODE=isolated` (default) | `TENANCY_MODE=shared` |
| :-- | :-- | :-- |
| Shape | Self-contained instance: own DB, own provider envs, own process | New tenant **in the platform DB**; provider envs shared with the primary instance (SaaS will run this) |
| `DATABASE_URL` | Own Neon project (or local sqlite) | The shared platform DB |
| Site row | `DEFAULT_SITE_SLUG` = own slug | **Explicit `site_slug` required** — `get_or_create_site` refuses the silent default fallback (`lib/store.py`), so a misconfigured process can never write into another tenant's data |
| Branding | Own `SITE_BASE_URL` / prompts via Phase 1 envs | Same envs, overridden per tenant (`SITE_BASE_URL`, `SITE_PREFIX`, `AUTHOR_PROFILE_API_URL`) |
| Provisioning | `scripts/provision_tenant.py --mode isolated` → prints the checklist (§4) | `scripts/provision_tenant.py --mode shared --slug … --site-type wordpress --site-url …` → creates the `Site` + Brand DNA row in the current DB, prints the env overrides the tenant process needs |
| Google Sheets | None (`SHEETS_ENABLED=0`) | None (`SHEETS_ENABLED=0`) |
| Discord | Own bot token **or** console-only approvals | See Discord below — shared bot, per-tenant servers |

### Discord per tenant (same bot account, different servers; SaaS: user's own server)

Facts that drive the design (Discord API + discord.py docs, verified 2026-10-12):

- **One bot token = one gateway process.** A second process with the same token
  is disconnected (identify/session conflict; sharding only starts at 2,500
  guilds). So "same bot account across tenants" means **one bot process routing
  many guilds**, not one bot process per tenant.
- **Webhooks are per-channel and independent of the bot** — draft
  notifications (`DISCORD_WEBHOOK_URL`) are already tenant-safe: each instance/
  tenant just gets its own webhook URL. No code change.
- A bot may freely join many guilds (invite per server); events carry
  `channel_id`/`guild_id`, so routing is a filter, not a fork.

| Concern | Isolated (site #2 today) | Shared bot (many tenant servers) | SaaS future (user's own server) |
| :-- | :-- | :-- | :-- |
| Bot process | Own `DISCORD_BOT_TOKEN` per instance (own bot app invited to the tenant's server), or no bot (console approvals only) | **One** bot process; `DISCORD_APPROVAL_CHANNEL_IDS` = comma-separated channel list (one per tenant server). Reaction handler filters `payload.channel_id in APPROVAL_CHANNEL_IDS` | Same shared bot; user invites the platform bot to **their** server during onboarding |
| Tenant routing | Process env is the tenant | v1: channel list only (single tenant-store per process). v2 (SaaS): `guild_id → Site.settings.discord_guild_id` lookup, approve via `POST /sdk/v1/articles/{id}/approve` | `guild_id` → tenant `Site` row → that tenant's DB slice |
| Webhooks | Own `DISCORD_WEBHOOK_URL` | Own URL per tenant | Per-tenant webhook created at onboarding |
| Approvals write | Sheet cell / REST | REST per resolved tenant | REST per resolved tenant |

Env contract (both modes): `DISCORD_BOT_TOKEN`, `DISCORD_APPROVAL_CHANNEL_IDS`
(comma list; legacy `DISCORD_APPROVAL_CHANNEL_ID` still honored — first entry),
`DISCORD_WEBHOOK_URL` (per tenant), optional `DISCORD_GUILD_ID` (reserved for
the SaaS guild→tenant lookup).


## 5. Phase 4 — Operator console (frontend)

Single-operator internal app in `console/` (Next.js 15 App Router + Tailwind).
**Layout decision (user, 2026-10-12): the console follows the same tab
structure as the Google Sheets workbook** — keywords, research, brief,
content, and the other logs — so the two surfaces are muscle-memory for the
operator.
**Grouping decision (user, 2026-10-12): keyword, research, brief, and content
live *under* one Articles section** (single top-nav entry → sub-tabs
Content/Keywords/Research/Briefs), so they are managed together instead of as
four scattered top-level screens.

### Sheet → console screen mapping (Postgres-backed)

| Sheets tab | Console screen | Postgres source |
| :-- | :-- | :-- |
| keyword ledger | **Keywords** (Articles → `/articles/keywords`) | `keyword_ledger` (via `GET /sites/{slug}/queue`) |
| research_data | **Research** (Articles → `/articles/research`) — subject, intent, volume, difficulty, summary, primary/secondary keywords, Generated flag | `keyword_ledger` + `research_snapshot` JSON (`GET /sites/{slug}/research` — **new**) |
| content_briefs | **Briefs** (Articles → `/articles/briefs`) — brief content, FAQs, sources, summary; rows that have one | `keyword_ledger.research_snapshot.brief/faqs/sources` (`GET /sites/{slug}/briefs` — **new**) |
| generated_posts + approved_unpublished | **Content** (Articles → `/articles`) — title, Quality Score, Summary, Approve/Disapprove + Published states | `articles` (`GET /articles`, rows extended with quality + summary) |
| model_usage_log, image_logs, audit worksheets | **Logs** (`/logs`) — usage + audit + cost rows | `audit_log` (`action=usage.model`/`usage.image`/publish actions) + `cost_ledger` (`GET /logs` — **new**) |

**Usage-log gap:** `log_model_usage`/`log_image_usage` append to Sheets only,
so a `SHEETS_ENABLED=0` instance would lose every row. They now also append a
best-effort `audit_log` row (payload = the sheet's columns) — the console
Logs screen reads that on both instances; site #1 keeps its sheets too.

### Console REST surface

| Screen | Backing call (existing unless noted) |
| :-- | :-- |
| Dashboard: queue counts, site health | `GET /sdk/v1/sites`, `GET /sdk/v1/sites/{slug}/health` |
| **Keywords** (ledger sheet) | `GET /sdk/v1/sites/{slug}/queue` — **landed** (rows + per-status counts, read-only; parity §B1) |
| **Research** (research_data sheet) | `GET /sdk/v1/sites/{slug}/research` — **new** (keyword rows + `research_snapshot` research fields) |
| **Briefs** (content_briefs sheet) | `GET /sdk/v1/sites/{slug}/briefs` — **new** (rows with `research_snapshot.brief`; the existing `…/brief` peek stays as "next briefable") |
| **Logs** (usage + audit sheets) | `GET /sdk/v1/logs` — **new** (`audit_log` + `cost_ledger`, kind filter) |
| **Content** list + detail (view markdown, scores, FAQ) | `GET /sdk/v1/articles` (rows + quality/summary), `GET /sdk/v1/articles/{id}`, `…/content` |
| **Edit** content | `PATCH /sdk/v1/articles/{id}/content` — **landed** (updates `content_md`, edits logged to `meta.edit_log` + audit; approved → reopened to generated, published keeps status; no re-gate — regenerate is the re-score path) |
| **Approve / reject** | `POST /sdk/v1/articles/{id}/approve` (exists) |
| Publish / refresh / stage images | `POST …/publish`, `…/refresh`, `…/stage-images` (exist) |
| WP + Elementor build | existing `/sdk/v1/wp/*`, `/sdk/v1/elementor/*` |
| Run a stage | `POST /sdk/v1/run/{stage}` — **landed** (wraps `run_stage.STAGE_HANDLERS` in a background task; 404 unknown, 409 overlap, 503 if the engine can't import) |
| Sites screen (create/upsert rows) | `POST /sdk/v1/sites` (upsert — existing) |
| Instances screen (add/edit/remove/switch) | console-local `instances.json` merged with `CONSOLE_INSTANCES` env (no engine call) |

Auth: operator password → session cookie; engine `API_KEY` stays server-side
(route-handler/server-action pattern per Next.js docs: `verifySession()` guard,
mutations in `'use server'` actions with revalidate). No user tables.

## 6. Phase 5 — Verification

1. Phase 1: full pytest (baseline 366 passed / 1 skipped) + `grep -i owaisabdullah`
   over code (excluding `_theirprompt.py`, docs, this spec) → only site_env defaults.
2. Phase 2: run `content` + `post` stages with `SHEETS_ENABLED=0` on a scratch DB;
   article lands in `articles`, approve via REST, publish to a LocalWP target.
3. Site #1 flip: `verify_cutover.py` clean → flip env → one real scheduled run observed.
4. Instance #2: end-to-end one keyword → brief → content → approve → WP publish on
   the real WordPress site; confirm no Google calls (no `GOOGLE_CREDENTIALS` set).
5. Console: e2e on instance #1 (dogfood), then point env at instance #2.

## 7. Work order & open questions

Order: **Phase 1 → Phase 2 → Phase 3 → Phase 4** (console can start after Phase 1
against instance #1; Phase 2's 3c/3a make it honest).

Open questions (answered 2026-10-12):

1. Console location: **`console/` in this repo** (Next.js 15 App Router +
   Tailwind; shares env + `/sdk/v1` with the engine).
2. Console MVP scope: **the full §5 table** (dashboard, queue, articles
   view/edit, approve/publish/refresh/stage-images, run-stage triggers).
3. Discord: **keep both** — site #1 keeps reaction approvals; the console
   becomes the primary control surface; Discord stays a parallel path.
4. Site #2 hosting: **same machine, second process** (own checkout/env;
   VPS later if needed).
5. `lib/db.py` schema: no ALTERs planned for v1 — current schema suffices
   (see §3 out-of-scope note); revisit before any cutover ALTER.
6. Shared-bot v2 (guild→tenant lookup): confirmed deferred to the SaaS
   phase; v1 ships channel-list routing only.

## References

- `docs/tool-parity-sanity-sheets.md` §B — Sheets→Postgres operation map
- `docs/site-onboarding-flow.md` — WP site flow + env vars
- `docs/service_setup.md` — site #1 setup (Google/Discord parts become optional for site #2)
- `sdk/server.py`, `sdk/service.py`, `sdk/contentfte.ts` — REST + client
- TASKS.md — "cutover step 2 flip", "Postgres migration complete; Sheets retired",
  Phase 2 console rule, "Multi-tenancy + site isolation" (deferred)
