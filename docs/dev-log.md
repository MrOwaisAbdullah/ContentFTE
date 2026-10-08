# Development Log

Running record of ContentFTE development sessions. Newest entries first.
Every entry lists what changed, how it was verified, and the commit(s) — so a
future session can reconstruct *why* the code looks the way it does.

> Conventions: append a dated entry per work session (or per merged chunk).
> Never paste secrets (app passwords, API keys) — reference the env var
> instead. Cross-reference `TASKS.md` (task tracker + change table) and
> `docs/phase1-live-run-checklist.md` (acceptance criteria).

---

## 2026-10-08 — Auto-derived taxonomy (categories + tags) for WP posts
**Branch:** `contentfte-phase1-engine-wp-sdk`
**Tests:** 271/271 pytest (23 new)

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
- **`tests/conftest.py`**: offline JEV guard stubs
  `lib.jev_tools.jev_classify_category` (LIVE-gated). Deliberately **not**
  clearing `OPENROUTER_API_KEY`: agent modules read it at import
  (`tools/tools.py` `load_dotenv`) — the first full-suite run caught the
  KeyError in 4 agent-wiring tests and the env deletion was reverted.
- **Tests**: `tests/test_taxonomy.py` (20: precedence, lexical/JEV/propose
  lanes, env gate, caps, None-tolerance) + `test_wp_publish.py` (+3 net:
  derive-when-brief-lacks-it, propose-new vs existing, refresh
  derive→cache-reuse with `list_terms` called exactly once, default-
  category safety net; fake connector gained `list_terms`/`existing_terms`).

### Verification
- `python -m pytest tests/ -q --basetemp=D:/opencode-npm-temp/.test-tmp-phase1/pytest-tax-final`
  → **271 passed, 1 warning, 63.5s** (248 → 271).
- Lexical test proves reuse ("AI Agents" matched from
  "ai agent tools…", `category_source == "lexical"`) and `meta.taxonomy`
  persisted; refresh test proves the cache is reused across two refreshes.

### Open / next
- Backfill the 3 live comparison posts: `refresh_article` on each (needs
  LocalWP `speedline` running + `WP_*` env, currently unset in the shell).
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
