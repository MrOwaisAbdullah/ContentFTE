# Development Log

Running record of ContentFTE development sessions. Newest entries first.
Every entry lists what changed, how it was verified, and the commit(s) — so a
future session can reconstruct *why* the code looks the way it does.

> Conventions: append a dated entry per work session (or per merged chunk).
> Never paste secrets (app passwords, API keys) — reference the env var
> instead. Cross-reference `TASKS.md` (task tracker + change table) and
> `docs/phase1-live-run-checklist.md` (acceptance criteria).

---

## 2026-10-16 — Console dashboard audit + wave plan: approval UX is the weakest surface, the image pipeline is invisible

**Commits:** `14d0bbe`

**What** — A plan doc, not code: `docs/console-dashboard-plan.md`. The console (`console/`, Next.js 15) was audited as a whole — full code read plus a live visual pass (engine `:8123` + console `:3001` against the real `contentfte.db`, all 12 routes screenhotted at 1440×900; screenshots kept out of the repo). Findings F1–F8 are written down: no design system and no icons; **the approval flow is one blind click** (raw markdown textarea, no rendered preview/diff/evidence checklist, scores + FAQs dumped as raw JSON); the image pipeline's `meta.images` (`style_pick`/`style_source`, match/clean/theme scores, `0a2be99`/`60bdedb`) renders nowhere; `$0.0000`/dead-column noise; no pending/feedback states on server actions; no per-site switcher on Keywords/Research/Briefs; bare empty states; no responsive handling. The plan keeps everything the console already does (auth, four sheets-parity tabs, stages, sites/instances/provision) and adds: design tokens (`@theme`, dark navy + teal accent + reserved gold), a status-pill scale, sidebar IA (Overview / Approvals / Publish queue / Content / Media / Insights / Logs / Sites / Instances / Provision / Stages), an article-detail blueprint with Preview⟷Edit, approve checklist, SEO-render tab and a Media tab carrying the Jev badges, and six execution waves — Waves 0–1 are pure console-side (zero engine risk and land first), Wave 2 (approvals) needs no engine changes, Wave 3 adds one static image-serving route + optional per-image replace op, Wave 4 adds `/logs` offset. Phase-2 gate respected: no billing/tenancy/public-dashboard/User accounts.

**Verified** — audit is observation, not change: engine + console booted locally, every route shot against live DB data (4 sites / 5 articles / 80 audit rows), both servers stopped afterwards; ports verified free. Zero Python or console-code changes in this commit (docs-only), so the suite is unaffected (last run 423 passed / 1 skipped).

**Next** — execution begins: Wave 0 (tokens/fonts/icons/pills/pending states/empty states/site switchers), then Wave 1 (sidebar shell + Overview KPIs). Each wave its own commit(s) + dev-log entry.

---

## 2026-10-15 — New gemini-router skill: the integration is now teachable (the old guides were still v0.2.0)

**Commits:** `53e7187`

**What** — No skill existed for `gemini-free-router`, and the three tracked router docs (`docs/router-guide.md`, `docs/contentfte-integration.md`, `docs/quota-persistence.md`) all describe the **v0.2.0** era — written before the two rounds of silent-failure fixes this repo then depended on (0.3.0 image parts, 0.4.0 function-calling translation + `thoughtSignature`, 0.4.1 Gemini tool-schema dialect; the repo pin is `^0.4.1`). An agent following those guides would have integrated a router that silently drops images and tools. New tracked public skill `skills/gemini-router/` (`SKILL.md` + `references/config.md` + `references/ops-and-ci.md`): version floors FIRST (with the exact symptom per floor), install/config including the "Say OK" probe-lies lesson, OpenAI client wiring (`model: "auto"`, vision parts, function calling), run + `/healthz` + `/admin`, app-side fallback policy (429 `free_tier_exhausted` vs retryable transport failures), the verified GitHub Actions wiring (ledger cache restore/save, health wait loop, SIGTERM flush, concurrency serialization), the three-check integration gate, and a troubleshooting table. Pointers added: README AI-agents block; superseded banners on the two v0.2.0 guides and quota-persistence; and `contentfte-integration.md`'s "AS IMPLEMENTED" row corrected — both gemma-4 models are disabled (the "Say OK" probe was the lie, not the model).

**Verified** — every claim in the skill traces to a live-verified fact already in this repo: gemma 200-with-empty-content probes (2026-10-15), 0.4.0 function calling + `thoughtSignature` (router repo `918c27a`, 112/112 router tests; SDK round-trip re-verified here), 0.4.1 schema dialect (re-verified with the exact agno dialect), image parts on 0.3.0 (live `prompt_tokens: 1072`), the ledger cache pattern (`pipeline.yml`), and `scripts/test_router_integration.py` (`ALL CHECKS PASSED` on 0.4.1). Docs/artifact-only change — no code touched, suite unaffected (last run 423 passed / 1 skipped).

**Notes** — The skill registers as `gemini-router` (frontmatter parsed by the agent harness). Historical docs stay as-is behind their banners; `TASKS.md` rows untouched (dated tracker).

---

## 2026-10-15 — In-post looks become a Jev decision: theme-matched directions, VLM-verified theme lane, rotate-on-retry

**Commits:** `0a2be99`

**What** — The morning's variety fix still picked the look with a blind hash, and half the styles were generic (flat-vector, duotone-poster) rather than native to the site's visual world. Both halves changed. (1) **Jev picks the look**: `lib/image_vision.choose_inpost_style()` is ONE batched decision — six Nouls, one per candidate art direction, judged against the section's title/summary — ranked best-first; `tools._resolve_inpost_styles()` turns that ranking into the attempt plan, `_generate_image` prompts the top pick, and a theme-lane failure promotes the next-ranked look for the retry (fresh prompt, no old-image reference — a new style is not an edit of the old image). Jev unreachable → the deterministic hash pick (`_pick_inpost_style`, now fallback-only) so image generation never blocks on the decision service. (2) **The looks now match the theme**: all six directions were rewritten inside the site's visual world (deep navy + electric blue/cyan, violet/magenta/amber, premium cinematic finish) — editorial-3d, cinematic-photo, technical-blueprint, isometric-diorama, cinematic-macro, glow-graphic — and the template gained a "site visual world" paragraph every attempt inherits. In-post QA is now topic + clean + **`theme_fit`** (`IMAGE_THEME_THRESHOLD=0.55`, env-tunable): loose enough that any clean medium passes, tight enough to bounce clip-art/generic looks, and the judge is explicitly told NOT to reward copying the hero thumbnail. `revision_guidance` gained a theme-drift branch; the `qa` block, per-attempt trace and image_logs summary row all carry `theme_fit`, `style_pick`, `style_source`, `style_scores`.

**Verified** — suite **423 passed / 1 skipped** (6 new/updated tests: Jev ranking order + state, fail-open, theme lane pass/fail, hash fallback, rotate-on-theme-failure asserting the rotated attempt carries no revision block). Live single attempt (`IMAGE_MAX_REVISIONS=1`, ~$0.0012 + $0.000032 for the style call): the style decision returned a real, discriminating ranking for "prompt caching" — technical-blueprint 0.82, glow-graphic 0.80, isometric-diorama 0.74, editorial-3d 0.73, cinematic-photo 0.66, cinematic-macro 0.61 — the top pick was the one prompted (`style_source=jev`), and the VLM+Jev gate judged the real pixels `clean=0.96`, `theme=0.72`, `text_seen=none`. The topic lane scored 0.45 on that single cheap-4b attempt (no escalation at max_revisions=1); a full run retries via guidance / 9b as before.

**Notes** — Retry semantics now split by failure kind: a theme-lane miss rotates the look; a topic/clean miss keeps the look and re-edits with the previous image + guidance. Thresholds stay env-tunable (`IMAGE_THEME_THRESHOLD`, `IMAGE_MATCH_THRESHOLD`, `IMAGE_CLEAN_THRESHOLD`) if live posts show any lane running hot.

---

## 2026-10-15 — In-post images stop wearing the house thumbnail look: own prompt, style rotation, clean QA lane

**Commits:** `60bdedb`

**What** — Every AI-generated in-post image reused the featured house template (cinematic 3D, navy-cyan, character-led), so body images across posts read as the same look. Body images now have their own genre end to end: `_image_plan(attempt, slot)` never typesets in-post (retries escalate the model, not typography); a new `_INPOST_IMAGE_PROMPT_TEMPLATE` + `_build_inpost_prompt` pick one of six looks (editorial-3d, cinematic-photo, flat-vector, isometric, macro, duotone-poster) deterministically per section topic — same pick on retries/re-runs, different posts vary; zero text via the hard closing rule; and `lib/image_vision` judges a new `clean` lane for in-post (text-free, uncluttered, no garbled shapes; `IMAGE_CLEAN_THRESHOLD=0.6`, env-tunable) instead of the house-style lane, which featured still uses unchanged. VLM framing, judge fallbacks, `validate_thumbnail`, `revision_guidance`, the `qa` block (now carries slot/clean/style_pick) and both tool docstrings are slot-aware; the stock-first gate and the featured path are untouched.

**Verified** — suite 417 passed / 1 skipped (8 new tests: plan, prompt isolation, deterministic style pick, clean-vs-style lanes, in-post guidance, end-to-end `_generate_image`). Live: 5 real generations (~$0.034, ~3.1k of the 10k daily neurons) — textless held on every attempt; the clean lane caught klein-4b baking/garbling text twice (0.04 / 0.08, once rendering "OWVAISABOLH.HON.DEV") and passed clean attempts at 0.86–0.95; two topics produced two distinct looks, consistent within each topic's retries (prompt caching → flat-vector, vector databases → duotone-poster). The mid-prompt "default to no people" did NOT stick (4/4 early attempts had a human element — once hands with extra fingers), so the no-people rule moved into a final closing block per this repo's own "last-instruction-wins" lesson; the last sample came back a pure abstract node network, no people, no text.

**Notes** — One topic sample scored `matches_blog` 0.62, a hair under the 0.65 topic floor (in a full run that escalates to 9b). Both image thresholds stay env-tunable if live posts show the topic lane running hot; stock already passes most sections, so the AI fallback is a quality bar, not a quota.

---

## 2026-10-15 — jev-1.14 adopted for text; live probe proved native images need TypeSafe's direct API

**Commits:** `5618352`

**What** — TypeSafe's jev-1.14 (released 2026-10-14) ships native image input ("danger zone"), a Box question type, and 262K long-context. Before wiring it, we probed the surface this repo actually calls (~15 live calls, <$0.0002 total): `typesafe/jev-1.14` works for text over `POST https://openrouter.ai/api/alpha/decisions` (response echoes the resolved snapshot `typesafe/jev-1.14-20261014`) — but the route **silently drops `assets`**: invalid base64 still 200s, the documented "every asset must be referenced or 400" rule is not enforced, two visually opposite images produce identical near-uniform answers, and `input_tokens` never scale with image size. OpenAI-style `input_image` parts are 400 (`state`/`questions` validation — the alpha route is System One format only), `/api/v1/decisions` is 404, multipart is rejected, and `typesafe/jev-router` doesn't exist on this route. Native images are documented only on TypeSafe's direct API (`https://api.typesafe.ai/v1/systemone` + `TYPESAFE_API_KEY` + `TypeSafe-Danger-Zone-Images: true`), which this repo doesn't have — so the VLM caption→judge bridge stays for image gates and we pinned `typesafe/jev-1.14` (exact id, not the moving `jev-preview`/`~typesafe/jev-latest` aliases) for text decisions in `lib/jev.py`, `discord_bot/jev_helper.py`, `.env`/`.env.example`.

**Verified** — smoke through the repo's own `call_jev_sync` on the new pin: resolved `typesafe/jev-1.14-20261014`, 370 in-tokens, $0.0000155; full pytest suite **409 passed / 1 skipped**. The local (gitignored) `.claude/skills/jev-system-one` docs got the full surface matrix + the 1.14 image-assets spec so nobody re-learns it by probing.

**Open** — moving image QA to direct-pixel Jev calls needs a `TYPESAFE_API_KEY` (decision pending). In-post image variety (slot-aware prompts + QA gate) remains queued as its own workstream.

---

## 2026-10-15 — First live content run through the router: two undefined-name crashes fixed in `run_stage.py`

**Commits:** `ce8b074`, `dd2ed1a`

**What** — The content stage (CI, on `6b112b0`) generated a complete post — title, 6 FAQs, TL;DR, repurpose bundle, video-script seed, Quality Score **92** (the eval loop had revised a 58 draft) — then died with `Stage 'content' failed: name 'source_brief' is not defined`, exit 1. Not an agent bug and not a router bug: `scripts/run_stage.py::_ensure_content_persisted()` — the deterministic save the stage falls back to when the agent doesn't append the row to `generated_posts` itself — read `source_brief`, a name that only exists as a local inside `run_content()`. Any such run crashed *after* paying for the whole generation, with nothing persisted. The function now takes the brief explicitly (mirroring `_enforce_keyword_gate`) and reads Secondary Keywords once via a shared `_brief_secondary_keywords()` helper — written on both the append path and the malformed-row repair path (the repair path used to blank that column).

**Second fix, same class** — a pyflakes sweep of the file caught a latent twin from `b3fcf1a` (2026-09-17): `run_search_performance_review()`'s low-impressions branch logs `ctr`/`position`, but both were assigned *after* the early return — the first weekly review whose rotation picked a post with < 50 impressions would have red-failed the same way. Fixed by lifting the two reads above the check (`get_page_performance` always returns the full dict, so this is safe).

**Verified** — regression test drives `_ensure_content_persisted`'s append path against a stubbed sheet and asserts the persisted row carries the brief's Secondary Keywords; `tests/test_keyword_flow.py` 19 passed / 1 skipped; full suite **409 passed / 1 skipped**; `pyflakes scripts/run_stage.py` clean. Remaining live check: re-dispatch the content stage — the failed run persisted nothing (`content_briefs` row still `Generated=No`), so the same brief gets picked up and regenerated cleanly.

---

## 2026-10-15 — gemini-free-router via npm: local Gemini proxy, cross-run quota persistence, OpenRouter fallback

**Branch:** `feature/router-integration` → `master` · **Commits:** `5bf8f51`, `2637ac3`, `8519676`, `d54665b`

**What** — Gemini traffic now runs through the `gemini-free-router` npm package (published 0.2.0 → 0.3.0 by this work) as a local proxy: `GFR_BASE_URL` in `.env` flips `blog_agent/custom_runner.py::get_gemini_client()` to `http://127.0.0.1:8787/v1` (unset = legacy direct-Google fail-safe, inactive in practice). `router.yaml` uses `fleet_mode: merge` (fleet=12) with both gemma-4 models **disabled**: 2026-10-15 instruction-following probes showed gemma-4-31b-it answering HTTP 200 with empty content or planning text that ignores the prompt — a 200 never triggers failover, and its 14,400 RPD would poison auto-picks. Vision QA routes through the router too (`IMAGE_VLM_ENDPOINT` → router ≥ 0.3.0, which translates `image_url` → `inline_data`/`file_data`; a 0.2.x router silently drops images, so the floor is documented in `.env.example`). The judge (`scripts/compare_results.py`) follows the same policy: explicit `JUDGE_URL` > `GFR_BASE_URL + /chat/completions` > legacy direct Google.

**Quota persistence across CI runners** — `pipeline.yml` starts the router per run and round-trips `data/` through `actions/cache` (run-scoped key `gfr-ledger-${{ github.run_id }}-${{ github.run_attempt }}`, restore-prefix `gfr-ledger-`), with `concurrency: contentspark-pipeline` serializing runs and a SIGTERM stop + cache save on `if: always()`. First CI dispatch (run `38628120374`, stage=content) succeeded with every router step green and cache `gfr-ledger-38628120374-1` saved — free-tier accounting now survives ephemeral runners ("no reset"). `IMAGE_VLM_ENDPOINT` added to the stage job env so vision lands in the same ledger.

**Validation (live, this session)** — `scripts/test_router_integration.py` green (`ALL CHECKS PASSED`, fleet=12, gemma disabled). T1 real generation via router (860-word article, ledger `served:1`). T3 fleet-exhausted router → 429 `code=free_tier_exhausted` + `retry-after` → chain walked all 9 Gemini models → `deepseek-v4-flash` via OpenRouter. T2 router STOPPED → `APIConnectionError("Connection error.")` had been classified non-LLM and *aborted* the run (defect) → fixed in `is_llm_error` (builtin `ConnectionError`, openai `APIConnectionError`/`APITimeoutError`, connection/DNS/timeout keywords are now retryable) → re-test `DOWN_OK`. Service-layer E2E (`submit_article` → `generate_content` → `get_article`): briefed→drafted, revise loop fired (809w < 900 floor → auto-revise → accepted), persisted delivery payload, $0.0034 / 24,285 tokens, test rows cleaned (5 real articles untouched). Engine suite **408 passed / 1 skipped**, incl. fixing `_INPOST_IMAGE_RE` (`[^)\s]+` → `[^)]+`): space-containing Windows image paths truncated at the first space, so the featured-image rescue skipped perfectly good AI images.

**Also** — `npm pkg fix` in the router repo (bin-path normalization, `958e868`); docs added: `docs/router-guide.md`, `docs/quota-persistence.md`, `docs/contentfte-integration.md` (AS-IMPLEMENTED table); `.env.example` router/vision/judge block; TASKS.md A4. Untracked by design: `docs/SPEC Free Gemini Router.md`.

**Follow-up (later 2026-10-15) — tool-calling gap, found by the first scheduled CI runs** (research 08:05Z / brief 09:39Z, both red). Both failed with EMPTY agent output (`Final output (str):` blank, `completion_tokens: 0`, `1 raw response`/`0 new items`): the router's OpenAI-compat layer silently DROPPED `tools`/`tool_choice` and never mapped `tool_calls`/`functionCall`/`role:"tool"`, so the Triage/Brief agents' sheet-tool declarations never reached Gemini and flash-lite answered 200-with-nothing (the Agents SDK was blameless — with no functions visible, an agent told "use only sheet data" just returns empty; reproduced byte-for-byte with the engine's exact Triage prompt, with vs without `tools`). Fixed in the router as **v0.4.0** (full request/response/SSE function-calling translation + Gemini 3 `thoughtSignature` memoization so signed calls survive the replay — router repo `918c27a`, dev-log §1.21, 112/112 tests). Bumped `gemini-free-router` **^0.3.0 → ^0.4.0** (`package.json` + lock; under 0.x semver `^0.3.0` cannot admit 0.4.0); `scripts/test_router_integration.py` → `ALL CHECKS PASSED` on 0.4.0. Live SDK round-trip through the router (read → `update_row` → final text from sheet data) verified pre-bump. **Second defect, found by the research re-run the same day** — after the bump, tool declarations reached Gemini but the request 400'd on the tool *schema dialect*: Gemini's `Schema` is a strict OpenAPI subset and rejects the strict-mode JSON-Schema keywords agno/Pydantic emits (`additionalProperties: false`, `$defs`/`$ref`, `anyOf`-null Optionals). Fixed in the router as **v0.4.1** (whitelist schema converter `geminiSchema()` — router dev-log §1.22) and bumped here `^0.4.0 → ^0.4.1` (`^0.4.0` already admits the fix; lock refreshed); integration gate re-passed, and the round-trip re-verified with the exact agno dialect before the bump.

---

## 2026-10-12 — Site #2 spec, tenancy, Postgres cutover 3a/3b, operator console

**Branch:** `master` · **Commits:** `0fed8a4`, `78d7d80`, `42b2487`, `03216d0`, `ef77644`, `152a800`, `9ed7e29`, `576734b`, `f1fa283`, `0bf74c0`, `47cc61e`
**Tests:** 408 passed / 1 skipped pytest · console `npm run build` clean (14 routes) · sdk `tsc --noEmit` clean

### Goal
Ship the spec'd path to a second, isolated blog instance (WordPress, separate
provider accounts, **direct Postgres — no Google Sheets at all**) plus an internal
operator console, on `master`, with site #1 unchanged until the drift gate clears.
Plan of record: `docs/spec-site2-postgres-frontend.md`. User decisions locked in §7:
console in `console/`, full §5 MVP, second instance as a separate process on one
machine, Discord kept (reaction approvals stay for site #1), no ALTERs in v1.

### What changed
- **Spec** (new): phases, env key inventory, sheet-parity mapping, §7 Q1–Q6
  answered; §3 carries the 3a/3b design note written during implementation.
- **Phase 1** (`0fed8a4`): site identity env-ified into `lib/site_env.py` (9 files
  inventoried); defaults = site #1, so the running instance is identical until an
  env var says otherwise.
- **Tenancy**: `TENANCY_MODE=isolated|shared` — shared mode *refuses* the silent
  default-tenant fallback (cross-tenant misattribution guard);
  `scripts/provision_tenant.py`. Discord multi-tenant: one bot token = one gateway
  process, so same-bot-across-tenants = one process +
  `DISCORD_APPROVAL_CHANNEL_IDS` comma list (legacy single id honored;
  `on_raw_reaction_add` filters membership).
- **Phase 2a** (`42b2487`): `SHEETS_ENABLED` (call-time read, default on) — every
  sheet call funnels through `get_gspread_client()`, so `0` fails loudly instead of
  deep inside google-auth; `get_keyword_tool` points at the SDK brief endpoint.
  Verified the SDK path (`sdk/service.py`, `sdk/server.py`) has zero gspread
  imports at any level — sheets-off pipeline = REST → service → DB.
- **Phase 2 3a/3b** (`0bf74c0`): `tools/sheet_tool.manage_sheet_data` gained a
  Postgres branch ahead of the gspread retry loop — one choke point, so no agent
  prompt, stage, or tool call changed. Derived views rebuilt per call in append
  order (`row_index` = position + 2):
  - `research_data` ← `keyword_ledger` + `research_snapshot` (`Generated` derives
    from a brief on that row *or any row sharing its subject*),
  - `content_briefs` ← rows with `snapshot.brief` (`Generated` = the
    `content_generated` marker the stage sets when it deletes the row),
  - `generated_posts` ← `articles`,
  - **`approved_unpublished`** ← articles with `status == "approved"`. Required,
    not cosmetic: the Preparation Agent's `get_row(row_index=2)` is how a
    sheets-off instance picks the next post to ship; a no-op read there means
    `NO_POSTS_FOUND` forever. Nothing writes to it; `delete_row` is a no-op.
  Writes map header → field (brief columns → `research_snapshot.*`, post columns →
  `content_md`/`scores`/`meta`, stamps/unknown → `snapshot`/`meta.sheet_stamps`,
  never fail); `row_index=1` writes and `research_data.delete_row` are no-ops.
  Two design traps found while implementing:
  1. **Join rule** — sheets addresses `research_data`/`content_briefs` by
     *subject* while `lib.store` keys the row by *primary keyword*. `append_row`
     therefore resolves the target row by keyword, then subject, and merges the
     snapshot: a naive upsert parks the brief on a second row and freezes
     `Generated=No` on the research row (unbreakable brief loop).
  2. **Direct mirrors** — appends call `mirror_keyword`/`mirror_brief`/
     `mirror_article` directly rather than the `DUALWRITE_ENABLED`-gated
     `mirror_sheet_append`, and keep the exact `"Row appended to {worksheet}."`
     phrasing `run_stage` string-matches. Sheet-only trailing columns
     (`Created At`, `Source URLs/Titles`, image/check stamps) are stashed into the
     row's JSON buckets.
  Unmapped worksheets (claims_audit, published_posts, review, telemetry) keep
  Sheets while enabled and return `[]` reads / `skipped:True` writes when off
  (spec 3d — logs already mirror to `audit_log`). Keyword claim/release get a
  Postgres path (first non-terminal row with no research summary, no brief, no
  `claimed_at`; the process-local `_keyword_claim["source"]` decides where release
  writes back) gated on `not sheets_enabled()` **only** — `ContentSpark_Keywords`
  is unmapped, so site #1's mixed mode must keep reading the real sheet for topic
  discovery. `ensure_worksheet_exists` no-ops. `run_stage.
  _get_successful_published_posts` derives repurpose candidates from published
  `articles` under the same switch.
- **Console** (`03216d0` → `f1fa283`): `console/` Next.js 15 App Router + React 19
  + Tailwind v4 — server-only engine access (`ENGINE_BASE_URL`/`ENGINE_API_KEY` →
  `X-Site-Key`, the key never reaches the browser), operator password + HMAC
  HttpOnly cookie, `(console)` route group running `requireSession()`. Sheets-layout
  parity by user request: Dashboard → Articles (sub-tabs Content/Keywords/Research/
  Briefs) → Logs → Sites/Instances/Stages/Provision; instance registry
  (`CONSOLE_INSTANCES` + runtime `instances.json`) with cookie-based switcher;
  provision wizard generates the instance `.env` (secrets never stored, shown once);
  Add-keyword form → `POST /sdk/v1/articles` → detail actions (Generate/Approve/
  Publish/Refresh/Stage-images). **Engine fix: `upsert_site` was create-only** — the
  console's documented create/upsert silently no-op'd; it now updates
  name/`site_type`/`base_url` when non-empty and returns `updated`, with the client
  defaults flipped `"custom"` → `""` so an omitted field can't downgrade a
  `wordpress` row. Also fixed en route: a greedy `/queue`→`/keywords` replace that
  rewrote an engine API path (404 red box), and a Get-Content/Set-Content
  round-trip that re-encoded a page as Latin-1 (mojibake) — replaced by tool-based
  edits for UTF-8 files.
- **MCP/SDK parity** (`0bf74c0`): 7 new tools `contentfte_{queue,research,briefs,
  logs,approve_article,update_content,run_stage}` with input models and background
  single-flight stages (`_stage_lock`/`_running_stages`/`_stage_tasks`);
  `sdk/python_client.py` and `sdk/contentfte.ts` mirror them.
- **Console health** (`0bf74c0`): `SiteHealth` + a dashboard "Site health" section —
  parallel per-site fetch with `.catch(()=>null)` so one dead instance never blanks
  the page.

### Verification (commands + observed result)
- `pytest tests/ --basetemp=D:/opencode-npm-temp/pytest-basetemp -q` → **408
  passed, 1 skipped**. New `tests/test_pg_cutover_choke.py` (12): header contract
  (`posts[:10] == lib.store._POST_HEADERS`), row addressing, A1 ranges, brief →
  research `Generated` derivation and re-research merge, brief delete →
  `content_generated`, article status/score writes, unmapped no-ops, `clear_sheet`
  refusal, **`approved_unpublished` publish-read contract**, claim idempotence/
  release/terminal skip, sheets-on keeps gspread, published-posts derivation.
  `test_manage_sheet_data_disabled_serves_postgres` asserts the gspread client is
  never constructed. `tests/test_api_mcp.py` +15 → parity.
- `console`: `npm run build` clean (14 routes; `.next` removed first — never build
  while `npm run dev` holds :3000), then dev restarted with `OPERATOR_PASSWORD`,
  `SESSION_SECRET`, `ENGINE_BASE_URL` in the process env (console has no
  `.env.local`).
- Authed smoke (session cookie forged in Python — PS 5.1's `New-Object
  HMACSHA256` mishandles it; header passed via `curl.exe -H @file` because PS 5.1
  splits native-arg strings containing spaces): `/` → 200 with per-site health
  cards (ledger counts, WP config missing, robots/sitemap checks incl. a real
  ConnectionError), and the served HTML re-checked byte-level for U+2014/U+00A7/
  U+00B7 — no mojibake (console only displays these as `A¿` because the terminal
  re-encodes UTF-8 as cp1252).
- Engine `:8000` and console `:3000` dev servers left running (logs:
  `D:\opencode-npm-temp\{engine,console}-dev.log`).

### Open / next
- [ ] **Live sheets-off e2e** (spec §6 item 2) — next priority: scratch DB +
  `SHEETS_ENABLED=0`, `content` → `post` stages, approve via REST, publish to
  LocalWP. Only remaining check needing no new infra.
- [ ] TASKS 44/47 flip: `backfill_postgres.py` → clean `verify_cutover.py` → env
  (needs the live store; mapped tabs freeze at flip, which is the intent).
- [ ] Instance #2 end-to-end on the real WordPress site (2nd Neon/providers/WP).
- [ ] Console e2e pointed at instance #2, then site #1 observed over one run.
- [ ] Standing rules: `_theirprompt.py` is never staged; no literal secrets in
  code/docs/commits.

---

## 2026-10-10 — Live-run defects (image/SEO/keywords) + model fleet migration
**Branch:** `master`
**Tests:** 366/366 pytest + 1 skip (site repo absent), sdk `tsc --noEmit` clean

### Goal
Four things surfaced from a live post run on 2026-10-08 plus a model
deprecation notice:
1. A featured-image failure published a post Studio **could not publish**
   (mainImage + alt are required) while Discord and the sheet both said
   "Published".
2. The generator and eval prompts both instruct secondary keywords
   ("2–3 uses each") but **nothing ever supplied them** — the model invented
   or skipped the rule. `lib/models.ContentBrief.keywords` described exactly
   the data we now have a column for and went unread.
3. A Sanity post had no SEO title/description/focus keyword/TL;DR fields —
   WordPress gets them as Yoast/Rank Math meta.
4. `gemini-3.5-flash` retired; the fallback chain still listed it.

### What changed
- **`lib/seo_keywords.py`** (new, pure): `parse_keywords` (split/dedupe/cap 3,
  every drop reported), `keyword_placement` (title/H2-H3/body slot counts),
  `check_keywords` → gate with `{pass, checked, counts, missing, guidance}`.
  Fails **open** when no targets supplied. Density warning is length-aware
  (`max(0.8%, 8/body_words)`) so a 130-word compact page isn't flagged for one
  natural mention while a 2500-word post still is.
- **Sheet (4 columns):** `Topic/YT Transcript · Primary Keyword · Secondary
  Keywords · Status`, resolved by header name via `_column_index` /
  `KEYWORD_SHEET_COLUMNS`. The previous `update_cell(i, 2, …)` was hardcoded to
  column 2 — with Status at column 4 it would have overwritten the primary
  keyword on every claim (same bug existed in `release_keyword_claim`).
- **Carry-through:** sheet → `research_data(+2 cols)` → ledger
  `research_snapshot` → `content_briefs(+1 col)` → **`generated_posts(+1 col,
  new — the brief row is deleted the moment it graduates, so publish had no
  other sheet source)** → Sanity `secondaryKeywords[]`. No keyword is ever
  invented; absent stays absent.
- **Hard gate on both surfaces:** `sdk/service._content_checks` →
  `keyword_usage` check + hard block after the revise loop;
  `scripts/run_stage._enforce_keyword_gate` runs *before* the
  `generated_posts` write. Secondaries are gated, the primary is not (gating
  the ledger topic rejected 14 legitimate drafts in the first cut).
- **Model fleet:** removed both retired 3.5 entries; added
  `gemini-3.6/3.7/3.8-flash`, `gemini-2.5-flash`, `gemini-3-flash-preview`,
  `gemma-4-26b-a4b-it`, `gemma-4-31b-it` — **each probed live** against
  `:generateContent` before adding. `gemini-2.5-flash-lite` rejected:
  404 "no longer available to new users". Retired ids keep their cost-ledger
  prices (historical rows must keep pricing correctly). OpenRouter free tier is
  an explicit `OPENROUTER_FREE_MODELS` tuple replacing the `openrouter/free`
  auto-router, with a **shared** 50 RPD enforced as a sum (correction from
  review: OpenRouter's free allowance is account-level, not per-model — three
  entries each billed 50/day would allow 150 calls and be rate-limited on the
  third).
- **Image failure:** nested image agents moved off `gemini-flash-latest`
  (87.95% measured error) to the 500-RPD lite — nested `as_tool()` runs never
  see `run_with_fallback`, so the pin is the only fallback they get. Prep agent
  now retries `generate_image_tool` **directly** (deterministic house prompt +
  Cloudflare, so no LLM call can 503) before giving up, and promotes an
  AI in-post image into the featured slot. `post_to_sanity_tool` reports
  `needs_image`/`doc_state`; `run_post` sends a ⚠️ instead of 🌐 Published.
- **Sanity:** `seoTitle`/`seoDescription`/`focusKeyword`/`tldr`/`secondaryKeywords`
  as optional-with-warning fields (never `required()` — that is the
  publish-blocker pattern). `sdk/sanity/` ships the whole studio (schema, env,
  config, `lib/seo.ts` with the one `seoTitle ?? title` /
  `seoDescription ?? summary` rule, webhook route). Documented in the new
  `skills/contentfte/references/sanity.md`, linked from SKILL.md step 0, the
  SDK table, pitfalls and the reference table.

### Verification
- 366/366 pytest (49 new across `test_keyword_gate`, `test_keyword_flow`,
  `test_seo_fields`, `test_model_fleet`, `test_post_image_failure` — the last
  two also assert no retired model and no live credential is in the shipped
  files).
- Live probes for every new model, and a deliberate-error injection to prove
  the sanity package's typecheck is not a false green.
- Keyword flow round-tripped end to end: parse → brief block → per-slot counts →
  pass on a draft that uses all three targets, blocked with an exact
  per-keyword report on one that drops one.
- Site repo (Owais-Abdullah) `tsc --noEmit` exits 0 with its schema edits.

### Bugs the tests caught mid-build
- `_column_index` computed `primary_pos` and never returned it.
- `research_snapshot_keywords` only handled dicts — the ledger hands over a
  JSON string, so keywords were silently dropped at exactly the point the
  operator supplied them.
- `mirror_keyword`/`mirror_article` were missing the new kwargs, so the
  dual-write mirror failed (non-fatally) and would have dropped the targets.
- Density cap over-flagged short drafts; replaced with the length-aware cap.

### Open
- The live site's `app/api/revalidate/route.ts` still has an inline IndexNow
  key and a default secret — treat as compromised and rotate; the packaged
  route reads env only.
- LLM gemini-flash-latest pins elsewhere (blog_agents 447/513/552/669/909,
  research_agent 119/223/271/517) still sit on the 87.95%-error model; not
  touched here because it changes per-agent behaviour, not just a retired id.

---

## 2026-10-08 — Auto-derived taxonomy (categories + tags) for WP posts
**Branch:** `contentfte-phase1-engine-wp-sdk`
**Tests:** 276/276 pytest (28 new)

### Goal
New engine posts landed on the site default category with **zero tags**: the
Article path submits title-only briefs (comparison driver, MCP
`generate_article`), `_wp_push` only read `brief.categories/tags`, and the
old sheet flow's taxonomy decision (`get_existing_categories_tool` +
`jev_classify_category` in the posting agent) was never ported. Operator
decision: lexical prefer-reuse first, **JEV judges the no-match case**
(reuse vs propose-new), backfill the 3 live comparison posts too.

### What changed
- **New `lib/taxonomy.py`** (pure): `derive_tags` / `resolve_category` /
  `derive_taxonomy`. Categories precedence: publisher brief/meta →
  prefer-reuse lexical match vs the site's existing categories (token
  containment scores 1.0 else Jaccard ≥ 0.34, specificity tie-break) →
  **JEV Choice judge** (`_jev_judge`: env-gated `OPENROUTER_API_KEY`, one
  call max, every failure swallowed → None) → title-cased propose-new.
  Tags stay deterministic (keyword phrase + salient tokens; stopwords,
  numerics and generic CMS nouns stripped; case-insensitive dedupe; cap 5).
  Every result carries `category_source`/`tag_source`
  (`brief|meta|lexical|jev_reuse|jev_new|new|derived`) for observability.
- **`lib/wordpress.py`**: `list_terms(kind, per_page=100)` — paginated
  read of existing categories/tags (`hide_empty=false`, 10-page cap),
  fail-open so a taxonomy read never blocks a publish.
- **`sdk/service.py`**: new `_article_taxonomy()` — derives once and caches
  in `meta["taxonomy"]` (assign-before-commit pattern) so publish and
  refresh apply the *same* terms; skips the site-taxonomy read when the
  publisher already supplied categories. Wired into `_wp_push` (default
  category demoted to last-resort safety net; `wp` response gains `tags` +
  `category_source`) and `refresh_article` (first refresh of an old post
  derives + caches — that's the backfill path — later refreshes reuse;
  response and audit payload now carry categories/tags).
- **`mcp_server/server.py`**: publish docstring documents auto-derivation.
- **`tests/conftest.py`**: offline JEV guard stubs `call_jev_sync` (the
  Decision API call, LIVE-gated) so the REAL `jev_classify_category` runs
  and falls back to `action=propose_new` — the tool's choice criteria, the
  none-of-these escape, and action mapping stay fully exercised while no
  test can reach the network. Deliberately **not** clearing
  `OPENROUTER_API_KEY`: agent modules read it at import (`tools/tools.py`
  `load_dotenv`) — the first full-suite run caught the KeyError in 4
  agent-wiring tests and the env deletion was reverted.
- **Tests**: `tests/test_taxonomy.py` (25: precedence, lexical/JEV/propose
  lanes, env gate, caps, None-tolerance, catch-all guard, action honoring,
  JEV-tool none-escape) + `test_wp_publish.py` (+3 net:
  derive-when-brief-lacks-it, propose-new vs existing, refresh
  derive→cache-reuse with `list_terms` called exactly once, default-
  category safety net; fake connector gained `list_terms`/`existing_terms`).
- **`scripts/backfill_taxonomy.py`** (new): refreshes every published
  `comparison-run` article (link-guard retry like the driver) and read-back
  verifies stored category/tag IDs through the WP REST API; exit 1 on any
  failure.

### Live backfill (LocalWP `speedline`) — two judge defects caught + fixed
First run (3/3 "verified") exposed that **every post came back
`category_source=jev_reuse` → `Uncategorized`** — two structural flaws:
1. **Catch-all reuse**: "Uncategorized" means *no category*, and the JEV
   choice question only offers the candidates it receives — with the site's
   categories being exactly `["SEO", "Uncategorized"]`, the judge was
   forced to "reuse" the catch-all (and later, alone among real options,
   "SEO" for all three posts, including the auth comparison).
2. **`action` ignored**: `_jev_judge` read only `parsed["category"]`, so
   `action=propose_new`/fallback payloads (forced choice / `existing[0]`)
   were honored as reuses.

Fixes: `CATCH_ALL_CATEGORIES` filtered from candidates before both lanes
(`resolve_category`); `_jev_judge` honors `action="reuse"` only;
`jev_classify_category` now always offers
`"(propose new: none of these fit)"` in its criteria (both existing
consumers — engine + old posting-agent prompt — already documented that
signal, the question just never provided it). Stale `meta["taxonomy"]`
caches cleared via a one-off script, backfill re-run:

| post | category (source=new) | tags |
|---|---|---|
| Haiku 5.5 vs DeepSeek V4.1 | Anthropic Haiku 5.5 Vs Deepseek V4.1 Flash | phrase + Anthropic, Haiku, Deepseek, V4 |
| Astro vs React/Next.js | When To Choose Astro Over React Or Nextjs | phrase + Astro, React, Nextjs… |
| Better Auth vs Auth.js | Better Auth Vs. Auth.Js (Next.Js) | phrase + Better, Auth, js, Next |

All 3 read back through the WP REST API with distinct real categories,
status `publish`, tags intact — `backfill: 3/3 posts verified`, exit 0.

### Verification
- `python -m pytest tests/ -q --basetemp=D:/opencode-npm-temp/.test-tmp-phase1/pytest-final2`
  → **276 passed, 1 warning, 93s** (248 → 276; intermediate run after the
  first commit: 271).
- Lexical test proves reuse ("AI Agents" matched from
  "ai agent tools…", `category_source == "lexical"`) and `meta.taxonomy`
  persisted; refresh test proves the cache is reused across two refreshes;
  catch-all/action/none-escape tests pin the live-observed guards.

### Open / next
- Live re-verify a fresh publish on speedline when the Cloudflare image
  quota resets (shared with the quality-fix batch above).

---

## 2026-10-08 — Production quality-fix batch: revise loop, focus keyphrase, image staging, per-call cost pricing, quota guard
**Branch:** `contentfte-phase1-engine-wp-sdk`
**Tests:** 248/248 pytest (219 baseline + 29 new), ~67s

### Goal
Close the defect batch found on the published comparison posts (short posts,
no first-try images, images injected after the FAQ, stale year, empty Yoast
focus keyphrase, missing internal/citation links), plus the two operator
asks: **cost-ledger pricing per LLM call** (TASKS A1 item 66, $0.00 gap) and
an **image-provider quota guard** (Cloudflare 10k-neuron daily burn).

### What changed
- **Quality gates + bounded revise loop** (`sdk/service.py`): pure helpers
  `_content_checks` (word floor `GEN_MIN_WORDS` default 900, TL;DR, Sources,
  FAQs, stale-year regex `in 20(?:1\d|2[0-5])`, summary) + `_content_sections`
  (H2 index skips Sources/FAQ); `generate_content` runs one feedback retry
  when `CONTENTFTE_REVISE=1` (default) — failing checks fed back as
  `PREVIOUS DRAFT FAILED THESE CHECKS` (prompt side: `lib/generation.py`
  `render_prompt` reads `GEN_MIN_WORDS` at call time).
- **Focus keyphrase**: `_focus_keyphrase(meta, brief)` (brief wins; first
  non-empty title-ish token) wired into the WP meta payload
  (`lib/wordpress.py`) and the service publish/refresh paths →
  `_yoast_wpseo_focuskw` no longer empty; meta description capped ≤155.
- **Internal/citation links**: `lib/generation.py` `build_brief_payload`
  exposes `internal_links`/`site_base_url`/`sources` from `brief_meta` and
  `render_prompt` instructs the draft to link them.
- **Images first-try, in the right place**: `_stage_images_for` runs at
  publish (and via new `POST /sdk/v1/articles/{id}/stage-images` + MCP
  `contentfte_stage_images`): featured + 1–2 in-post images (`want = 2 if
  words >= 1300 else 1`), in-post target = **second H2**, alt
  `{keyword}: {heading}` / summary-truncated; staged paths persisted as
  `meta["image_staging"]` (skip path is idempotent — only written when a
  featured image exists). `lib/wp_render.py` injection boundary fixed so
  images land **before** the FAQ block, not after.
- **Quota guard** (`tools/tools.py` `_generate_image`): pre-loop
  `_QUOTA_MARKERS` ("429", "rate limit", quota text) short-circuits to
  `{"error": "...quota exhausted...", "quota": True}` with
  `IMAGE_QUOTA_COOLDOWN_S` (default 3600) breaker — stock/Pexels unaffected.
- **Per-call LLM pricing** (`lib/cost_ledger.py`): `LLM_PRICES_USD_PER_MTOK`
  table (gemini-3.5-flash-lite/flash, deepseek… prefix match) + `usage_cost`
  → `(0.0, {})` on empty, `detail.price_source` recorded;
  `service.generate_content` merges `blog_agent.generation.LAST_USAGE` via
  `_merge_usage` and calls `record_cost(kind="llm", …)` → **closes TASKS A1
  item 66** (ledger was persisting $0.00).
- **SQLAlchemy JSON in-place mutation bug (root cause of lost writes)**:
  mutating `art.meta[...]` in place *after* an earlier `session.commit()`
  makes the change permanently invisible — the in-memory "committed" object
  mutates with it, flush history shows no net change, **no UPDATE fires**
  (proved with SQL-level echo: Article dirty with the right dict, only the
  audit-log INSERT emitted). Fixed at both sites (`stage_images`,
  `publish_article`): compute costs first, assign `art.meta = dict(meta)`
  **once**, *then* `record_cost`'s commit flushes meta + ledger row together.
  Repro kept at `D:\opencode-npm-temp\opencode\debug_publish.py`.
- **Test hygiene**: new `tests/conftest.py` autouse `_isolated_env` —
  `CONTENTFTE_REVISE=0` + deletes live creds (`CLOUDFLARE_API_TOKEN`,
  `CLOUDFLARE_ACCOUNT_ID`, `PEXELS_API_KEY`, `WP_*`) from module globals
  unless `CONTENTFTE_TEST_LIVE`; `.env` never loaded by tests (only `main.py`).
- **New tests**: `tests/test_quality_fixes.py` (29) — checks/revise loop,
  link graph, staging placement + persistence, quota guard, pricing, focus
  keyphrase, wp_render boundary, MCP/REST parity (`tests/test_api_mcp.py`).
- **Docs/env**: `.env.example` documents `CONTENTFTE_REVISE`,
  `GEN_MIN_WORDS`, `IMAGE_STAGING_DIR`, `IMAGE_QUOTA_COOLDOWN_S`,
  `LLM_PRICE_INPUT_PER_M`/`LLM_PRICE_OUTPUT_PER_M`; local `.env` sets
  `CONTENTFTE_REVISE=1`, `GEN_MIN_WORDS=900`,
  `IMAGE_STAGING_DIR=D:\opencode-npm-temp\contentfte_images` (C: is full —
  staging must live on D:). Driver `scripts/generate_compare_articles.py`
  simplified to rely on engine-side staging.

### Verification
- `python -m pytest tests/ -q --basetemp=D:/opencode-npm-temp/.test-tmp-phase1/pytest-fix1`
  → **248 passed, 1 warning (starlette anyio deprecation), 66.9s**.
- Persistence fix proved at SQL level: final `meta.image_costs_recorded: True`
  in sqlite; `test_stage_images_persists_section_aware_rows` asserts the
  committed meta directly.
- Test-safety audit: no test performs network calls (creds scrubbed;
  `log_image_usage` stubbed in quota tests).

### Open / next
- Merge to `master` — user said **"Not yet"** (re-ask after this commit).
- Cutover flip (TASKS 44/47) deferred by user; no live Postgres.
- Cloudflare daily quota exhausted → live speedline verification
  (post 104 fresh/regen: ≥900w, images before FAQ on first publish,
  focus keyphrase, internal links, year 2026, staging writes on D:) waits
  for reset.

---

## 2026-10-08 — Engine vs. baseline comparison run + per-post time/token logging
**Branch:** `contentfte-phase1-engine-wp-sdk`
**Tests:** 219/219 pytest

### Goal
Controlled old-vs-new quality comparison: last 25 published sheet posts
(`ContentSpark/generated_posts`, `Published=Yes`) vs 3 fresh engine posts
(Haiku 5.5 vs DeepSeek V4.1 Flash, Astro vs React/Next.js, Better Auth vs
Auth.js) — judged on facts/tone/style/length/images + structure/SEO — and
add **local wall time** + **token usage** per post to the comparison.

### What changed
- `scripts/compare_results.py` — end-to-end comparison tool: identical
  parser both sides (words/FAQ/links/images/readability/AI-isms/SEO+structure
  checklists), live published-page checks (title/meta/JSON-LD/OG/H1/img+alt),
  **Gemini judge** (identical rubric, temp 0, model fallback chain, SHA1-keyed
  cache), weighted verdict → `docs/engine-vs-baseline-report.md`, plus a new
  **Ops: local time & tokens** section — new per-post wall/tokens from
  `phaseD_results.json`, old LLM-time/call-count bucketed from
  `model_usage_log` into `Created At` windows (old tokens: never logged).
- `scripts/generate_compare_articles.py` — Phase D driver: submit → generate
  (word-count guard, ≤3 attempts) → AI images (featured `_generate_image`,
  inpost `_select_inpost_image` stock-first) → approve → publish/refresh,
  `--regen` mode, writes `phaseD_results.json` (words, gen/wall/img/total
  seconds, tokens, gate/WP state).
- `scripts/recover_compare_images.py` — re-attached run-1 AI images after the
  driver's local-path staging bug (`urlopen` on `c:\…`) + Cloudflare daily
  neuron-quota exhaustion in run 2: mtime clustering (>40s gaps → 6 clusters)
  → VLM-ranked winners (`image_vision.validate_thumbnail`, engine's own
  blog+style+passed rank) → stage `meta.images` → `refresh_article`.
- **Engine usage capture**: `blog_agent/generation.py` gained
  `LAST_USAGE` (aggregated from `RunResult.raw_responses[].usage` — agents
  0.19 exposes no top-level `.usage`) reset per call; `service.generate_content`
  measures `wall_s` around the generate fn and persists
  `meta.generation.{wall_s,usage:{requests,input_tokens,output_tokens,total_tokens}}`.
  No signature change; `custom_runner` untouched (off-limits).

### Verification
- `python -m pytest tests/ -q --basetemp=D:/opencode-npm-temp/.test-tmp-phase1/pytest-feat4`
  → **219/219** (note: basetemp parent dir must exist or `tmp_path` errors).
- Full compare run: **weighted verdict new 74.6 vs old 70.0** (new: tone
  93.3, structure 86, images 100, style 66.7, seo 80; old: facts 79.2 vs
  66.7, length 68.8 vs 46.7 — 910.8 vs 522 words).
- Ops numbers: new avg **20.2s gen wall / 14,128 tokens / 76.0s total** per
  post vs old **2,042.7s LLM latency + 24.9 calls** per post.
- 3 posts live on LocalWP `speedline` (WP REST ok=True), each with AI
  featured + inpost images and alt text (verified via page `<img>` grep).
- Judge artifact noted in methodology: judge knowledge cutoff predates the
  newest model releases → f=1 on the new Haiku article *and* the old
  DeepSeek-V4.1 article (hits both sides).

### Open / next
- `cost_ledger` persists $0.00 — per-call pricing not wired (new TASKS A1
  open item; tokens are captured but unpriced).
- Cloudflare daily image quota (10k neurons) is easy to burn in QA loops —
  consider quota-aware backoff before run day.
- Merge to `master` re-ask; cutover (TASKS 44/47) still deferred per user.

---

## 2026-10-08 — npm package renamed to `content-fte` (0.3.0)
**Branch:** `contentfte-phase1-engine-wp-sdk`
**Tests:** 219/219 pytest + SDK typecheck/build/smoke 20/20

- Renamed the npm package **`@owais-abdullah/contentfte` → `content-fte`**
  (user: the scoped name is too long). Updated `sdk/package.json` (name +
  version **0.3.0**), install/import specifiers in both READMEs, quickstart,
  the skill (`SKILL.md` + `references/stacks.md`), `docs/site-onboarding-flow.md`,
  `docs/phase1-feature-map.md`, `ContentFTEArticle.tsx`, `contentfte-prose.css.d.ts`.
  Historical dev-log/TASKS/dogfood rows intentionally keep the old name.
- The `0.2.1` publish attempt failed **404 → real cause 401** (`npm whoami`
  Unauthorized): the npm login session had expired (npm reports scoped PUTs as
  404 when unauthenticated) — re-login fixed it.
- **`content-fte@0.3.0` LIVE** on npm (no similarity-guard clash; bare
  `contentfte` stays blocked vs `contentful`). Round-trip verified from a clean
  consumer: `npm i content-fte` → ESM + CJS `ContentFTEClient`/
  `ContentFTEArticle` + `contentfte-prose.css` export all resolve.
- Old package **deprecated** (`0.0.0-stage`, `0.1.0`, `0.2.0`) with
  "renamed to content-fte" so installs show a warning.
- Dogfood processes (uvicorn `:8123`, `next dev` `:3000`) stopped — ports free.

---

## 2026-10-07 — L80 live acceptance ✓ + FAQ accordion + packaging
**Branch:** `contentfte-phase1-engine-wp-sdk` (23 commits ahead of `master`)
**Commits:** `9c2c2cc` (this session) ← `fe30ff7` ← `3ea31cd` ← `5bb0a53` ← `bba7522` ← `0e445e1`
**Tests:** 212/212 green (`python -m pytest tests/ -q`)

### Goal
Close TASKS line 80 — end-to-end gated article → test WordPress with
meta + schema + featured image + category, **zero manual steps** — and make
FAQs render as an accordion on both render targets.

### Live acceptance (LocalWP `speedline`, WP 7.1)
`scripts/acceptance_wp.py` walks: upsert WordPress site → submit brief →
real generation → stage featured/in-post images → approve (gate) → publish
(WP push inside the same call) → verify over WP REST. Reports a PASS/FAIL
checklist mirroring `phase1-live-run-checklist.md` §6.

Attempt log (kept because the failures were instructive):

| # | Result | Cause / fix |
|---|---|---|
| 1 | crash in generation | `blog_agent/hooks.py` printed a brand dict containing emoji 🚀 to a **piped cp1252 stdout** → `UnicodeEncodeError` inside `on_tool_end`, surfaced by the SDK as "Error running tool". Fixed by forcing UTF-8 stdout/stderr at import (`errors="replace"`). |
| 2 | 13/14 checks | Block-serialization check read `content.rendered` — `the_content`/`do_blocks()` **strips** `<!-- wp:` delimiters from rendered output. Fixed: check `content.raw` (context=edit). Real generation this run: 490 words, score 95. |
| 3 | stalled | The generation LLM HTTP call hung; killed at the 900 s budget (pre-existing Gemini/fallback flakiness; model router is off-limits per TASKS 119). |
| 4 | **14/14 PASS** | Content seeded so the run exercised render→publish→verify without the flaky LLM step (real generation already proven in run 2). |
| manual | **PASS** | Opened the post in Gutenberg via `agent-browser`: no "Attempt Block Recovery", 5 `core/details` parsed, shared `name="contentfte-faq"` intact. |

Final evidence (run 4), post_id **97**:
```
[PASS] post created over WP REST — post_id=97 status=draft
[PASS] Gutenberg block serialization — 20 blocks (raw content)
[PASS] headings rendered (H2 present)
[PASS] JSON-LD script injected — application/ld+json
[PASS] Article schema @type present
[PASS] FAQ schema @type present
[PASS] FAQ accordion rendered — 5 <details> item(s)
[PASS] CTA block rendered
[PASS] featured image set — media_id=95 1280x720
[PASS] in-post image in body — wp-content/uploads src
[PASS] category assigned — SEO
[PASS] SEO meta persisted — _yoast_wpseo_metadesc=How ContentFTE pushes a complete SEO art
[PASS] excerpt/meta description rendered
--- 14 checks, 0 failed ---
```

Environment notes (no secrets here — see `.env`/session env):
- Site `speedline` runs on **HTTP only** (`http://speedline.local`); HTTPS fails.
- **Yoast SEO 28.6** installed + activated over the `/wp-json/wp/v2/plugins`
  REST route (the `SEO meta persisted` check was SKIP before the plugin existed;
  `WPConfig` sends Yoast/RankMath/AIOSEO meta keys unconditionally, WP drops the
  unregistered ones).
- REST auth = WordPress **application password** in `WP_APP_PASSWORD`
  (minted once; not stored in the repo).

### FAQ is now always an accordion
**Native (Gutenberg, default):** `lib/wp_render.render_faq_block` emits a
`core/heading` ("Frequently Asked Questions") plus one **`core/details` block
per item** — `<details class="wp-block-details" name="contentfte-faq"><summary>Q</summary>`
with the answer as inner `core/paragraph` blocks. Shared `name` gives
one-open-at-a-time behaviour where browsers support it.

- Save markup was verified against the *running* WP 7.1 core, not guessed:
  `wp-includes/blocks/details/block.json` (attrs `showContent`/`summary`/`name`),
  the block-library `save()` source, and `getCommentAttributes` (which omits
  **sourced** attrs and values equal to their **default** → comment stays bare
  `<!-- wp:details -->`).
- Editor validation is whitespace-tolerant (`isEquivalentHTML` compares
  non-whitespace tokens) → formatting can't trigger recovery; tags/attrs/text
  must match, and they do.

**Elementor:** the FAQ no longer rides inside the html widget. `PreparedPost`
now carries `faqs`; elementor mode writes a native **Accordion widget**
(`lib/elementor._faq_accordion_widget`) — schema taken from
`elementor/includes/widgets/accordion.php` @ 4.2.3 (`tabs` repeater with
`tab_title` / `tab_content`, 7-hex `_id`s). A plain-`<details>` FAQ section is
still written into the fallback post content so the page keeps its FAQs if
Elementor is bypassed. Wired through `publish()` → `_write_elementor` and
`sdk/service.elementor_build`.

Non-block mode (`blocks=False`) renders the same accordion as plain
`<details>` inside `<section class="faq-block">` (custom-site / fallback HTML).

### Also in this entry
- `scripts/acceptance_wp.py`: block check on raw content; FAQ check now asserts
  `<details>`/`<summary>`; Yoast guidance updated.
- `docs/phase1-feature-map.md`: FAQ row rewritten (accordion).
- `docs/site-onboarding-flow.md` (new): step-by-step WordPress **push** and
  custom React/Next/Astro **pull** flows, incl. **where `site_type` is set**
  (`wordpress`|`custom` only — no per-framework value) and an
  `html` vs `markdown` vs `markdown_alternate` note (Astro renders
  `payload.markdown`; the engine's pre-rendered `html` is optional).
  Astro render options documented: `marked`, a **content-loader
  `renderMarkdown()`** (Astro's own remark/rehype pipeline — the true
  equivalent of `react-markdown`), or a framework island
  (`react-markdown` / `svelte-exmarkdown` / `markdown-it`).
  README refreshed for the published SDK.
- `docs/tool-parity-sanity-sheets.md` (new): every Sanity + Google Sheets
  operation mapped to its ContentFTE equivalent for WordPress / custom sites,
  with a gap table. Result: **full parity** except two custom-only inputs
  (internal-link source, image hosting) that need a product decision.
- **Parity tools added** (service → REST → MCP → clients):
  `list_articles` (`GET /sdk/v1/articles`, `contentfte_list_articles`),
  `refresh_article` (`POST /articles/{id}/refresh` — updates an existing WP post
  in place via `WordPressConnector.update_post`, status untouched; custom sites
  return a pull/re-deliver note), and `wp_post` read-back
  (`GET /wp/posts/{id}` → `WordPressConnector.get_post` with `context=edit` for
  raw content + registered SEO meta). Uniform tests for each.
- **`llms.txt` exposed** (site-level GEO §5.8): `service.llms_txt` composes the
  site index from its published articles (`lib.geo.generate_llms_txt`) →
  `GET /sdk/v1/sites/{slug}/llms.txt` + `contentfte_llms_txt` + clients. Fix en
  route: `list_articles` now returns the **resolved** slug (`_resolve_slug`)
  instead of the often-empty column — so `.md`/llms URLs are correct. Sitemap
  stays site-owned.
- **`skills/contentfte/SKILL.md`** (new, public): an agent-facing skill for
  installing the SDK and implementing it per stack — Next.js/React, Astro,
  Vue/Nuxt, Svelte/SvelteKit, plain HTML, WordPress (push), and MCP. Thin
  `SKILL.md` + `references/stacks.md` (code per stack) + `references/api.md`
  (routes/tools/payload/lifecycle). Written with the skill-creator-pro pattern
  (Before-Implementation context gathering, decision tree, pitfalls, verification).
- Tests: `tests/test_wp_render.py` (accordion, plain mode, empty), 
  `tests/test_elementor.py` (accordion widget, FAQ-off-the-html-widget,
  publish branch). +3 tests → 212.

### Open at end of session
- [ ] Full-generation acceptance re-run (run 4 used seeded content).
- [ ] Push/merge the branch (23 commits ahead of `master`).
- [x] Republished npm **`0.2.0`** — **LIVE** (npmjs.com/package/@owais-abdullah/contentfte)
      with the new client methods (`listArticles`, `refreshArticle`, `wpPost`, `llmsTxt`).
- [x] **Next.js dogfood (TASKS 90) PASSED** — a fresh Next app (agent-driven, using
      only `skills/contentfte/SKILL.md`) rendered a published article end-to-end in
      ~25 min. Findings + fixes in `docs/dogfood-nextjs-report.md`: **FAQ is now a
      `<details>` accordion** in the React renderer + **`payload.faq_html`** for
      non-React sites; typed client returns; `get_article` returns the resolved
      slug; skill/docs fixed for llms.txt (serve `.llms_txt`), Next 15/16
      `await params`, slug→id, `.md` route, Tailwind preflight.
- [x] **npm publish `@owais-abdullah/contentfte@0.1.0`** — **LIVE**
      (https://www.npmjs.com/package/@owais-abdullah/contentfte). Path there:
      the unscoped `contentfte` name was **rejected by npm's similarity guard**
      vs `contentful` (`E403 … try renaming to '@owais-abdullah/contentfte'`),
      so the package was scoped + all install/import docs updated (`eac5942`);
      the PUT then needed a 2FA one-time password (`EOTP`, auth-and-writes) —
      published via the CLI web-auth prompt (`npm publish --access public`).
      Registry note: right after publish the packument showed a placeholder
      `0.0.0-stage` ("staged publishing") for a few minutes before `0.1.0`
      became `latest`. Verified end-to-end from the public registry: clean
      consumer `npm i` → ESM + CJS `ContentFTEClient`/`ContentFTEArticle`
      import, `renderToStaticMarkup` → `<h1>`, heading id, `==mark==`, and the
      CSS path resolves.
- [ ] TASKS 92 (live MCP session), 90 (Next.js dogfood), 44/47 (Postgres cutover flip).

---

## Commit history — ContentFTE Phase 1 (`contentfte-phase1-engine-wp-sdk`)

| Date | Commit | Subject |
|---|---|---|
| 2026-10-07 | `9c2c2cc` | L80 live acceptance + FAQ accordion + hooks UTF-8 fix |
| 2026-10-07 | `fe30ff7` | L80: gated article → WordPress publish in one call (meta+schema+images+categories) |
| 2026-10-07 | `3ea31cd` | Real generation behind `generate_article` (TASKS/§5.5) |
| 2026-10-07 | `5bb0a53` | Native Elementor render target (supersedes EMCP wiring) |
| 2026-10-07 | `bba7522` | npm polish: README + lint-clean exports (publint / arethetypeswrong) |
| 2026-10-07 | `0e445e1` | Package the SDK as npm `contentfte` (one install) + unified `/content` payload |
| 2026-10-07 | `9c1a4d1` | Wire Elementor MCP (msrbuilds/elementor-mcp EMCP Tools): opencode.json + elementor-publish skill |
| 2026-10-07 | `875681e` | Default to Gutenberg block serialization (no manual Convert to Blocks) |
| 2026-10-07 | `13febb6` | docs: Phase 1 feature map + WP rendering/editability answer |
| 2026-10-07 | `b6532d0` | Fix script CLIs for direct execution (sys.path bootstrap, ASCII help) |
| 2026-10-07 | `21543ea` | docs: Phase 1 live-run checklist |
| 2026-10-07 | `1e896fb` | Phase 1.5: custom-site (Astro/Next) delivery payload + webhook push |
| 2026-10-07 | `2e8c455` | Phase 1.5: business profile → Brand DNA + offer catalog |
| 2026-10-07 | `7058a9b` | Ledger guarantees: article-keyword lineage, queue health, rotation log |
| 2026-10-07 | `8a19caf` | Wire Phase 1A acceptance: Tavily metering, SEO metrics, triage, cost ledger |
| 2026-10-07 | `2cbb86b` | Cutover step 2 tooling: Postgres read API + drift verifier |
| 2026-10-07 | `82d5927` | Phase 1B: WordPress body rendering, images, meta/schema, JSON-LD |
| 2026-10-07 | `e90c3ff` | Sheets → Postgres cutover step 1: dual-write mirror + backfill |
| 2026-10-07 | `b60ab27` | Add GSC decay job (refresh briefs) + monthly AI share-of-voice |
| 2026-10-07 | `2508cfc` | Remove named sources from seo-pack SKILL.md |
| 2026-10-07 | `1ab61e6` | Wire tactics library: skill pack, PAA atomization, comparison pages, cluster planning |
| 2026-10-07 | `cdf03ef` | Add image pipeline: VLM relevancy gate, IPTC provenance, per-image cost log |
| 2026-10-07 | `2765c14` | Add ContentFTE Phase 1: engine modules, API/SDK/MCP layer, agent wiring, markdown element fidelity, Sanity v6 pin |

## Earlier history (pre-Phase 1)

| Date | Commit | Subject |
|---|---|---|
| 2026-10-05 | `56bd7c5` | Cheap-first image router, no-text/watermark prompt rules, retries |
| 2026-10-04 | `ec52aa4` | VLM + Jev image QA loop, house thumbnail prompt, image_logs auditing |
| 2026-10-03 | `3f7c31c` | Rename project references to ContentFTE |
| 2026-10-03 | `a360d0c` | Fix pipeline tool-name mismatches, dead agent hooks, Tavily response handling |
| 2026-09-24 | `010f88e` | Fix hallucinated URLs: deterministic link validator + Jev external guard |
| 2026-09-24 | `82507f3` | Add TypeSafe Jev decision gates across content pipeline |
| 2026-09-17 | `588f760` | Bump version to 1.0.0 and add project keywords/classifiers |
| 2026-09-17 | `b3fcf1a` | Fix pipeline schedule, topic rejection feedback, search rotation, sheet logs |
| 2026-09-08 | `31582ad` | Rebrand to ContentFTE: Autonomous AI Content Employee (Digital FTE) |
| 2026-09-08 | `7256bfc` | LICENSE: switch to CC BY-NC 4.0 |
| 2026-09-05 | `449595e` | Auto-log approved posts to brain/ coverage history |

> Full raw history: `git log --date=short --pretty=format:"%h | %ad | %s"`.
> Detailed change table for this phase: `TASKS.md` (bottom).

---

## How to add an entry

```md
## YYYY-MM-DD — <short title>

**Branch:** …  **Commits:** …  **Tests:** N/N

### Goal
### What changed
### Verification (commands + observed result)
### Open / next
```
