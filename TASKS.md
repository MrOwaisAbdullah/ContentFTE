# ContentFTE — Master Task Tracker

**Branch:** `contentfte-phase1-engine-wp-sdk`
**Spec:** `docs/Content FTE Research/ContentFTE-Engine-Spec-v1.md` (v1.0, 2026-10-03)
**Playbook:** `docs/Content FTE Research/ContentFTE-Tactics-Playbook.md`
**Rule:** Model router + fallbacks (`blog_agent/custom_runner.py`) are touched **LAST**. Nothing in Phase 1 edits that file.
**SaaS rule:** Phase 2 (billing, multi-tenancy, public dashboard) is deferred until engine + WP + SDK are live.

Update this file on every commit: `[ ]` → `[x]` + date + commit hash.

---

## Phase 1A — Engine improvements (current focus)

### A0. Foundation / infra
- [x] 2026-10-06 — New branch `contentfte-phase1-engine-wp-sdk` created
- [x] 2026-10-06 — `lib/db.py` — Postgres (Neon via `DATABASE_URL`) + sqlite fallback; tables: sites, brand_profiles, keyword_ledger, articles, cost_ledger, audit_log, seo_cache
- [x] 2026-10-06 — `lib/ledger.py` — §5.16 lifecycle, priority_score, next_keyword, briefable_rows, cannibalization guard, cluster coverage, rotation review, article lineage
- [x] 2026-10-06 — `lib/seo_provider.py` — §5.14 `SEO_DATA_PROVIDER` (`off`/`openseo`/`dataforseo`), 30-day cache, sandbox mock, manual-entry mode
- [x] 2026-10-06 — `lib/brand_dna.py` — §5.1 versioned per-site profiles + system-prompt auto-inject helper
- [x] 2026-10-06 — `lib/factcheck.py` — §5.3 discrete claim-extract → verify gate (runs BEFORE eval)
- [x] 2026-10-06 — `lib/eval_gate.py` — §5.2 sub-scores, <80 floor, falsifiable check, audit writer (9/9 tests pass)
- [x] 2026-10-06 — `lib/geo.py` — TL;DR, FAQ/Article JSON-LD, sameAs, `llms.txt`, `.md` alternate, IndexNow payload
- [x] 2026-10-06 — `lib/cost_ledger.py` — §5.10-6 per-post cost ledger
- [x] 2026-10-06 — `lib/wordpress.py` — §5.11 REST connector skeleton (media, taxonomy, guards, draft/auto, refresh)
- [x] 2026-10-06 — `sdk/server.py` + `sdk/python_client.py` + `sdk/contentfte.ts` — §5.12 routes, per-site keys, idempotency, audit
- [x] 2026-10-06 — `mcp_server/server.py` — §5.13 7 tools skeleton
- [x] 2026-10-06 — `tests/test_phase1_engine.py` — 9/9 green; `.env.example` + `pyproject`/`requirements` deps declared
- [x] 2026-10-06 — Wire brief agent: pull ONLY from `approved`/`queued` ledger rows (`get_next_brief_task_tool`, transitional `register_brief_task_tool` bridge from research_data); intent-template selection (`lib/brief_templates.py` + `get_brief_template_tool`); discourse appendix (Reddit/forums 30d via tavily `time_range="month"`); SERP-gap (exactly 3 missed subtopics); ledger close (`mark_brief_saved_tool` → briefed)
- [x] 2026-10-06 — Wire draft agent: Brand DNA inject (startup), TL;DR 40–60w open block (`tldr_block` format), question-form H2s + 2–4 sentence direct answers (AEO §5.7), PAA capture, offer catalog (§5.5: `get_offer_catalog_tool`, brief decides placement, draft max 2 mentions + 1 CTA, `rel="sponsored"` for affiliates), repurpose bundle (LinkedIn + X thread) + video-script seed in Output JSON → persisted to `generated_posts` (self-healing trailing columns)
- [x] 2026-10-06 — Wire eval agent: voice + citability sub-scores (§5.1/§5.2 six-sub-score report), falsifiable guidance enforcement (observation/fail_check/leading_indicator), fact-check ordering stated (§5.3: gate runs before eval, eval never replaces it), AEO checklist scoring (TL;DR/Sources missing → seo capped at 79)
- [x] 2026-10-06 — Sources box (title+publisher+link, §5.4 — generator ends every post with `## Sources`, old Sources-ban removed, Related Posts ban kept) + outbound 200-check pre-publish gate (`lib/link_validator.validate_links` strips non-200 links pre-save in run_stage + WP `pre_publish_checks`; eval surfaces HEAD failures)
- [x] 2026-10-06 — Internal-link hardening (§5.6): `lib/linkguard.py` (extract/classify, hygiene gate 3-8 internal + 1-3 external + no exact-match anchor >2x, inbound_counts, rescue_order stable-sort) + `tools/linkguard_tool.py` (`check_link_hygiene_tool`, `fetch_rescue_links_tool` — GROQ `content[].markDefs[].href` inbound scan, orphan-first with `inbound`/`needs_rescue`), generator wired (rescue→jev_rank tie-break, final hygiene gate before return)
- [x] 2026-10-07 — Image pipeline update: VLM relevancy gate (stock-first for in-post, AI-only thumbnail), IPTC `TrainedAlgorithmicMedia`, per-image cost log
- [ ] Tactics wiring (§5.15): prompts cite skill pack; PAA atomization pages; comparison pages (`[Client] vs [Competitor]`); cluster planning
- [ ] GSC decay job → auto refresh briefs (republish+301 major / in-place minor, bump `dateModified`); monthly share-of-voice log
- [x] 2026-10-06 — `.env.example` additions: `DATABASE_URL`, `SEO_DATA_PROVIDER`, `OPENSEO_*`, `DATAFORSEO_*`, `WP_*`, `SDK_MASTER_KEY`, `INDEXNOW_*`, `BING_WMT_*` (`WRITER_MODEL`/`CRITIC_MODEL` noted, wired last with router)
- [ ] Sheets → Postgres cutover (dual-write then retire Sheets)

### A1. Acceptance (from spec Appendix A — engine subset)
- [ ] Postgres migration complete; Sheets retired
- [ ] Brand DNA profiles working; voice sub-score in eval
- [ ] 90+ gate with sub-score floor (no sub-score <80 publishes)
- [ ] Fact grounding: zero unsourced numeric claims in audit sample; fact-check runs before eval
- [ ] Sources box + 200-checked outbound links on every article
- [ ] Eval: citability sub-score present; all critic guidance falsifiable
- [ ] Triage: cannibalization / intent-overlap check before brief
- [ ] Ledger: zero articles without keyword row; priority queue always has next keyword; rotation decision log per site
- [ ] Brief: discourse appendix + intent template; briefs pull only from approved/queued rows
- [ ] GEO: `.md` alternate per article; monthly share-of-voice log
- [x] Images: IPTC provenance tags; alt text; per-image cost logged
- [ ] Internal linking hardened (diversity, orphan rescue)
- [ ] TL;DR + FAQ + schema on every article
- [ ] `llms.txt` per site; entity sameAs in schema
- [ ] 3 images/post, cost logged
- [ ] GSC decay job running monthly
- [ ] DataForSEO/OpenSEO in every brief (or manual fields when `off`); 30-day cache
- [ ] Tavily metering per site; pause-and-flag when budget exhausted (no under-researched publish)
- [ ] Per-post cost ledger complete

---

## Phase 1B — WordPress adapter (§5.11) — REST first, plugin later

- [x] 2026-10-06 — `lib/wordpress.py` — `WordPressConnector` (Application Passwords / Basic auth), media upload, Yoast meta payload, on-demand taxonomy, pre-publish guards, draft/auto modes, refresh
- [ ] Text rendering: full HTML (headings/lists/tables/FAQ/CTA blocks), shortcode-safe
- [ ] Image rendering: featured upload + set thumbnail; in-post at H2 breaks + alt; srcset left to WP core
- [ ] Internal-link fetch via WP REST → feeds internal-linking agent
- [ ] Meta: Yoast / Rank Math / AIOSEO fields + Article + FAQ JSON-LD
- [ ] Taxonomy: categories/tags created on demand from brief mapping
- [ ] Guards: duplicate prevention, slug collision (`-2`, `-3`), outbound 200-check, draft (default new sites) vs auto modes
- [ ] Refresh: `dateModified` bump, featured-image replace on refresh
- [ ] MCP interop note: deep site ops via WP/Elementor MCP, not re-implemented
- [ ] Acceptance: end-to-end gated article → test WP with meta+schema+featured image+category, zero manual steps

---

## Phase 1C — Custom-site SDK + MCP (§5.12 / §5.13)

- [x] 2026-10-06 — SDK server routes: `POST /articles`, `GET /articles/{id}`, `POST /articles/{id}/approve`, `POST /articles/{id}/publish` (409 until approved), `GET /articles/{id}/content`, `GET /sites`, `POST /sites` (upsert), `GET /sites/{slug}/health`; events `article.ready` / `article.published` / `article.needs_review` returned in responses; browser CORS (`SDK_CORS_ORIGINS`, open default) for React/Next/Astro
- [x] 2026-10-06 — Auth per-site API keys (`X-Site-Key` + `SDK_MASTER_KEY`); idempotency keys; retries with backoff (client-side, 3× exp); audit-log every submit/approve/publish
- [x] 2026-10-06 — Client libs: JS/TS (`sdk/contentfte.ts`, frontend-first — plain fetch, no deps) + Python (`sdk/python_client.py`), retry/backoff both, quickstarts in docstrings + `sdk/quickstart.md` (React/Next.js/Astro patterns, key-location guidance)
- [ ] Acceptance: fresh Next.js site publishes first article via SDK in <30 min (dogfood)
- [x] 2026-10-06 — MCP server tools: `contentfte_list_sites`, `contentfte_get_brief`, `contentfte_generate_article`, `contentfte_get_article_status`, `contentfte_get_image`, `contentfte_publish_article`, `contentfte_site_health` — mounted at `/mcp` (streamable HTTP, json_response) + stdio fallback; tools consume `sdk/service` only (never the DB)
- [ ] Acceptance: Claude Code brief → generate → status → publish end-to-end via MCP (needs real generation wired behind `generate_article`; stub row works today)

---

## Phase 1.5 — Local Business Factory upsell (spec §7, after engine live)

- [ ] Converted tenants → ContentFTE sites (business profile/services/location → Brand DNA + offer catalog)
- [ ] Publish via SDK against Astro renderer; visual editor stays human touch-up
- [ ] Pexels wiring shared with §5.9 VLM gate (wire once)
- [ ] JEV reuse for triage/publish routing
- [ ] Package: website + 8–12 posts/mo retainer + monthly proof report (posts, GSC movement, AI citations, cost ledger)
- [ ] Sell service first (revenue + training data) before self-serve SaaS

---

## Phase 2 — SaaS platform (DEFERRED — do not build in Phase 1)

Spec §9 preview only. Allowed now: minimal internal run console (CLI/local single-page) for operators. NOT allowed: customer dashboard, auth, billing.

- [ ] Multi-tenancy + site isolation
- [ ] Auth
- [ ] Stripe / Lemon Squeezy billing ($29/$79/$149) + usage metering + overage credits
- [ ] Customer dashboard (calendar, approvals, cost transparency, AI-visibility)
- [ ] API key self-service
- [ ] White-label (Scale tier)
- [ ] Model-routing refactor (LAST — after engine works): `WRITER_MODEL` default `deepseek/deepseek-v4.1-flash`, `CRITIC_MODEL` arena-top-value, remove old `v4-flash-0731` slug, keep free-Gemini fallback chain

---

## Open questions (spec §10)

1. [ ] Postgres schema approved (draft in `lib/db.py` — review before cutover)
2. [x] WordPress: REST-only v1 (answered 2026-10-04) — plugin later as SaaS distribution move
3. [ ] Frontier critic default: benchmark GPT-6 Sol vs Sonnet 5.5 vs Gemini 4 Argon on 10 samples → set `CRITIC_MODEL`
4. [ ] Factory retainer price (must absorb ~$8/mo content + Tavily overage past 2 clients)
5. [ ] Image style presets — which 4 ship at launch?
6. [ ] `SEO_DATA_PROVIDER=off` manual-entry UX — CLI form or markdown brief template?

---

## Log

| Date | Change |
|---|---|
| 2026-10-06 | Tracker created; branch `contentfte-phase1-engine-wp-sdk`; A0 foundation modules added (db/ledger/seo_provider/brand_dna/factcheck) |
| 2026-10-06 | API-first layering: `sdk/service.py` (canonical ops) → REST (`sdk/server.py`) → MCP (`mcp_server/server.py`, 7 `contentfte_*` tools) mounted at `/mcp` in `main.py` + Brand-DNA startup injection; 17/17 tests green (`tests/test_phase1_engine.py` + `tests/test_api_mcp.py`); full-app smoke: MCP initialize/tools-list/tools-call 200. Fixes: MCP DNS-rebinding allow-list (421 on non-localhost Host → `MCP_ALLOWED_HOSTS`), sqlite dispose-before-delete in fixtures, client retry/backoff, submit audit |
| 2026-10-06 | Frontend-first SDK (React/Next/Astro): browser CORS (`SDK_CORS_ORIGINS`), `POST/GET /sdk/v1/sites`, `POST /articles/{id}/publish` (409 until approved), retry/backoff in both clients, `sdk/quickstart.md`; 18/18 tests |
| 2026-10-06 | Brief agent wired (§5.16): `lib/brief_templates.py` (5 intent templates, pure), `tools/ledger_tool.py` (pull/register/template/mark_briefed), brief_agent instructions (ledger-first, discourse appendix, SERP gaps, entities), `tavily_search_tool` +`time_range`; 23/23 tests (`tests/test_brief_wiring.py` added) |
| 2026-10-06 | Draft agent wired (§5.5/§5.7/tactics): `tools/offer_tool.py` (brand-profile offers, max 2+1 limits), TL;DR 40–60w + question-H2 AEO blocks, offer placement decided in brief / capped in draft, repurpose bundle + video-script seed Output JSON → `generated_posts` new trailing columns; 27/27 tests (`tests/test_draft_wiring.py` added) |

| 2026-10-06 | Agent wiring completion (lines 31-33): eval agent gate-ordering + AEO checklist (TL;DR/Sources missing caps seo 79), generator `## Sources` box + `lib/link_validator` 200-check pre-save, internal-link hardening `lib/linkguard.py` + `tools/linkguard_tool.py` (hygiene gate, orphan rescue) wired into generator; 37/37 tests |
| 2026-10-06 | Markdown element fidelity + Sanity v6: `lib/markdown_parser.py` fixed (ordered lists via `list_data.type`, uniform dedent vs code-fence, nested list levels + deferred nested lists, GFM tables `_type:table` rows/cells, fenced `code` blocks with language, inline HTML marks underline/strike/highlight, standalone+inline images as image blocks), `_portable_text_to_markdown` reverse extended (code/table/strike/underline/highlight/asset-url), adapter pinned `v2026-07-28` (env `SANITY_API_VERSION`, deprecation-header logging), generator instructions now allow tables/highlight/code. **Perspective fix probe-confirmed live**: new pins hide drafts from id queries by default ? `_build_query_endpoint` defaults `perspective=raw` (doc lookups) with `published` pinned on live-site pools (fetch_internal_links, list_posts, linkguard inbound, link validation). Site repo (Owais-Abdullah, uncommitted): blockContentType + table/code members, CustomComponent table renderer w/ cell spans, `npx tsc --noEmit` clean. Live roundtrip probe on real API: create draft ? read raw ? all 10 element checks OK ? delete. 63/63 tests (`tests/test_markdown_elements.py`, `tests/test_query_perspective.py` added) |
| 2026-10-07 | Image pipeline (line 34, §5.9): new `lib/image_provenance.py` (IPTC `trainedAlgorithmicMedia` via XMP — JPEG APP1 + PNG iTXt, replace/idempotent, never raises) wired into `_generate_image_cloudflare` after temp write; `lib/image_vision.score_topic_relevancy` (VLM pixels → Jev Noul → 0-100, `IMAGE_STOCK_RELEVANCY_THRESHOLD` default 0.90, fail-open); `tools/sheet_tool` image_logs headers +`Cost (USD)`/`Slot`/`Latency (ms)`/`Prompt` with self-heal; `tools/tools.py` `_image_cost_usd` map, `slot` plumbed through generate/stock logs, new `_download_image_to_temp` + `_select_inpost_image` + `select_inpost_image_tool` (Pexels→VLM gate ≥90 stock else Klein AI, both-fail→skip+flag), `generate_image_tool` refactored to `_generate_image` core; agents: insertion agent uses gated select tool, selection agent has NO stock fallback (featured always AI, returns empty+flagged), preparation agent drops stock fallback (IMAGE_URL empty + sheet flag); adapter `post_blog` publishes without mainImage when no image (no `_ref:null`). 84/84 tests (`tests/test_image_pipeline.py` +21) |
