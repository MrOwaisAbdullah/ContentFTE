# ContentFTE Engine Spec — v1.0

**Status:** Draft for review
**Date:** 2026-10-03
**Phase:** Phase 1 — Engine only. Tenant/SaaS (billing, dashboard, multi-tenancy) is explicitly Phase 2 and out of scope here.
**Related:** Report page "Soro vs ContentFTE Research Report" (competitive context, pricing $29/$79/$149, hybrid model strategy).

---

## 1. Purpose

Build the content engine first: a pipeline that takes a keyword/topic and produces a published, quality-gated, SEO/AEO/GEO-optimized article with images — on WordPress or any custom site. No tenants, no billing, no SaaS dashboard in this phase. Single-operator mode (Owais) with chat approvals (Discord/Telegram/WhatsApp).

## 2. Locked decisions (do not relitigate)

- **Execution model:** DeepSeek V4.1 Flash via OpenRouter (`deepseek/deepseek-v4.1-flash` pinned explicitly; repo still has the old `v4-flash-0731` slug — update it). Research, brief, draft, revision, metadata.
- **Judgment lane:** JEV (already in repo, `lib/jev.py`) for cheap structured micro-decisions: dedup, intent classification, link/category selection, publish routing.
- **Frontier critic lane:** one frontier eval per article (GPT-6 / Claude 5 / Gemini 4 family via OpenRouter, ~$2/$10 planning rate). Eval + improvement guidance only. Re-run only after a failed gate or for high-value content.
- **Quality gate:** nothing publishes below 90/100.
- **Images:** FLUX.2 Klein 4B default ($0.015/image, ~5–8s; text rendering verified in head-to-head test 2026-10-03). Muse Image disqualified (unavailable in PK region). Seedream 4.5 / Nano Banana 2 as manual upgrades. Pexels stock as $0 fallback.
- **Launch targets:** WordPress first, custom sites second (SDK), Shopify later.
- **Storage:** migrate Google Sheets → PostgreSQL (Neon) during Phase 1.
- **Research data — start with OpenSEO hosted, not DataForSEO direct.** Verified 2026-10-04 at openseo.so/pricing: $10/mo base, includes $10 usage/mo (resets monthly), extra top-ups never expire, $0.50 trial, cancel anytime — but an active subscription is required to use it. ~$0.05/keyword search (~28% markup over raw DataForSEO). At 30 posts/mo (~$4.20 usage) the flat $10 covers everything, with rank tracking, site audits, and their MCP server included free. DataForSEO direct ($1 trial → $50 minimum top-up, never expires, ~$0.11/post) is cheaper per-post and wins after ~7–8 months — switch via env when volume is proven. `SEO_DATA_PROVIDER` (`openseo` | `dataforseo` | `off`) abstracts the switch; `off` = manual keyword/SEO data entry, zero data cost.
- **Model selection via env (no hardcoded models):** `WRITER_MODEL` (default `deepseek/deepseek-v4.1-flash`; V4 Flash is cheaper — switchable per cost), `CRITIC_MODEL` (default = current arena top value; 2026-10-03: Gemini 4 / Opus 5.5 class), `SEO_DATA_PROVIDER` (`dataforseo` | `openseo` | `off`). The existing free-Gemini fallback chain stays exactly as-is. **Model-routing refactor happens last** — after the engine works.
- **Tavily deep research is standard for every post** (not an upsell): all posts need deep research for correct facts and sources. 1,000 free credits/mo ≈ 2 clients at 30 posts/mo; beyond that PAYG $0.008/credit (~$0.10/post) or Project $30/mo for 4,000 credits (see §6).

## 3. Phase 1 scope

**In scope:** everything in §5 (engine features), WordPress connector, custom-site SDK, MCP server, Postgres migration, DataForSEO integration, chat approvals, per-post cost tracking.

**Out of scope (Phase 2):** multi-tenancy, user auth, billing/subscriptions, public SaaS dashboard, white-label, API key self-service. Phase 1 runs single-operator; a minimal internal run console (CLI or single-page local UI) is allowed for operations, but no customer-facing SaaS surface.

## 4. Engine architecture

```
Keyword/Topic
  → Triage (JEV: dedup vs existing, keyword cannibalization / intent-overlap check vs ledger, intent classify, go/no-go)
  → Research (DataForSEO keyword data + Tavily tiered search + discourse research: last-30-days Reddit/forums/social language; writes to site keyword ledger §5.16)
  → Brief (angle, outline, SERP gaps, entities, sources, brand DNA injection, intent template selection — briefs pull only from approved/queued ledger rows)
  → Draft (DeepSeek V4.1 Flash)
  → Fact-check (discrete gate: verify every stat/claim against its source — before eval, never after)
  → Evaluate (frontier critic with falsifiable guidance; JEV micro-checks)
  → Revise (loop until ≥90 or max 3 rounds → human review)
  → Images (Klein 4B: 1 thumbnail + 2 in-post; styles; stock fallback; IPTC provenance tags)
  → Internal linking (existing fetch_internal_links_tool; harden per §5.6)
  → Publish (WordPress / SDK / MCP: HTML + Markdown alternate + llms.txt) in draft or auto mode
  → Feedback (GSC loop → ledger status updates won/lost → decay detection → refresh briefs; monthly AI share-of-voice check; 30/60-day batch rotation review)
```

Model routing per stage:

| Stage | Model | Notes |
|---|---|---|
| Triage, micro-decisions | JEV (`typesafe/jev-1.13`) | <1500ms, typed answers |
| Research, brief, draft, revision, metadata | DeepSeek V4.1 Flash | Off-peak scheduling (outside 06:00–09:00 & 11:00–15:00 PKT weekdays); OpenRouter provider pinned to DeepSeek route |
| Evaluation + guidance | Frontier (GPT-6 / Claude 5 / Gemini 4 fam) | 1 pass/article; $2/$10 planning rate |
| Images | FLUX.2 Klein 4B | $0.015/image |

---

## 5. Feature specifications

### 5.1 Brand DNA (voice profiles)

**Objective:** every article sounds like the client, not like a generic AI.
**Current state:** not implemented.
**Spec:**
- Per-site profile: 3–5 sample URLs or pasted samples → DeepSeek distills into a structured profile (tone sliders: formal↔casual, terse↔expansive; reading level; signature phrases; banned phrases/clichés; POV: first/second person).
- Profile stored in Postgres, versioned. **Implementation rule (Agrici pattern): the profile is auto-loaded at the system-prompt level for the brief, draft, eval, and image-prompt agents — never passed as an optional parameter.** Brief agent injects the profile into draft context; eval agent scores "voice match" as a separate 0–100 sub-score (weight 15% of the 90+ gate).
- CLI command to (re)build a profile from samples; re-run when client approves new samples.
**Acceptance:** two articles on the same keyword for two different brand profiles are distinguishable by a blind reviewer; voice sub-score present in every eval report.

### 5.2 Quality gate hardening

**Objective:** make the 90+ gate explainable and trustworthy.
**Current state:** eval + revision loop exists; JEV exists.
**Spec:**
- Eval report becomes structured: overall score + sub-scores (accuracy, depth, SEO, voice, originality, **citability** — per-passage quotability for AI engines, per §5.8). Any sub-score <80 blocks publish even if overall ≥90.
- **Falsifiable guidance:** every critic improvement recommendation must carry (a) the observation it rests on, (b) "how would we know this failed?", (c) a leading indicator to watch. Guidance without a falsifiability check is rejected and regenerated — vague feedback ("make it more engaging") is a P0 defect in the eval itself.
- JEV checks run pre-eval: duplicate-of-existing (vector similarity vs published corpus), search-intent match, category fit. Failures route to human before burning frontier-eval tokens.
- Every publish decision writes an audit row: scores, model IDs, token usage, cost, revision count.
**Acceptance:** no article with any sub-score <80 reaches publish; audit row exists for 100% of published articles.

### 5.3 Fact grounding

**Objective:** kill hallucinations — the #1 trust killer in this category (see Jolt review incident in research).
**Current state:** Tavily research exists in pipeline.
**Spec:**
- Draft agent extracts factual claims (stats, dates, prices, named entities) into a claim list.
- Each claim must carry ≥1 source from the research step. Claims without a source are flagged to the revision agent: either find a source (Tavily) or soften/remove the claim.
- Deep research is **standard for every post** (Tavily advanced multi-step; see §6 economics). No lite tier — factual accuracy is the product. If a site's Tavily budget is exhausted, the run pauses and flags the operator rather than publishing under-researched content.
- **Gate ordering (Agrici):** fact-check runs as a discrete pass *before* the frontier eval — the critic never spends tokens on unverified claims. Draft → fact-check → revise → eval, not draft → eval.
**Acceptance:** published articles contain zero unsourced numeric/date claims in a sampled audit; sources section present.

### 5.4 Sources & citations

**Objective:** visible trust signals for readers and for AI-search citation.
**Spec:** every article ends with a "Sources" box (title + publisher + link). Inline, use natural attribution ("According to DataForSEO…"). Never invent URLs — link checker validates every outbound link returns 200 before publish; dead links are dropped or replaced.
**Acceptance:** 100% of outbound links return 200 at publish time (checked, not assumed).

### 5.5 Product & business mentions

**Objective:** articles can mention the client's products/services (critical for the Local Business Factory upsell, §7) without reading as spam.
**Spec:**
- Per-site "offer catalog": product/service names + one-line descriptions + target URLs, managed per site.
- Brief agent decides placement (max 2 natural mentions + 1 CTA block). Mentions must be topically relevant — eval agent penalizes forced placement.
- Disclosure: affiliate/external product mentions get `rel="sponsored"`; client-owned get normal internal links.
**Acceptance:** CTA block present where brief calls for it; no more than 2 in-body mentions; sponsored tags correct.

### 5.6 SEO core

**Objective:** every article is technically publish-ready.
**Current state:** internal linking implemented; stock + AI images implemented.
**Spec:**
- Internal linking (harden existing): 3–8 links/article, anchor-text diversity check (no exact-match anchor >2x), orphan-page rescue (prefer linking to pages with <3 inbound links), links preserved across revisions (already done).
- Meta: title (≤60 chars, keyword-fronted), description (≤160), OG tags.
- Schema: Article + FAQPage JSON-LD on every post; Organization/WebSite once per site.
- Slugs: collision handling (append -2, -3), Unicode-safe.
- Duplicates: URL + title + vector-similarity check before publish.
- IndexNow ping on publish (Bing/Yandex) **plus Bing Webmaster Tools API submission** — concrete mechanism, not just the ping. XML sitemap maintained per site.
**Acceptance:** sample audit scores 100/100 on RankMath/Yoast checks for meta+schema+slug; zero duplicate publishes in logs.

### 5.7 AEO (answer-engine optimization)

**Objective:** win the answer box / AI-overview citation.
**Spec:**
- Every article opens with a 40–60 word direct answer block ("TL;DR") after the H1.
- Question-form H2s mirroring "People also ask" phrasing (from DataForSEO SERP data); each followed by a 2–4 sentence direct answer, then elaboration.
- FAQ section (4–8 Q&As) feeding the FAQPage schema (§5.6).
- Definition-style sentences for key terms ("X is…").
**Acceptance:** TL;DR + FAQ present in 100% of articles; eval agent scores AEO structure as a checklist item.

### 5.8 GEO (generative-engine / AI-search visibility)

**Objective:** be cited by ChatGPT/Claude/Gemini/Perplexity, not just ranked by Google.
**Spec:**
- `llms.txt` generator per site (root file: site summary, key pages, content policies) — deployed via WordPress connector and SDK.
- Entity grounding: every article declares its entities (people, products, places) with sameAs links (Wikidata/Wikipedia/official sites) in schema.
- Quotable stat blocks: key statistics formatted as standalone, self-contained sentences (AI engines lift these verbatim). **Citability scoring:** eval agent scores passages on AI-quotability (self-contained? attributed? concise?) as a sub-score; revision agent rewrites low-citability passages.
- **Agent readiness:** publish pipeline emits a Markdown alternate of every article at a predictable URL (`.md` alongside HTML) — agents and LLMs prefer it. Lighthouse Agentic Browsing checks and WebMCP readiness on the roadmap; llms.txt now.
- **AI share-of-voice (metric, not lite log):** monthly scripted prompts to ChatGPT / Gemini / Perplexity / AI Overviews / AI Mode with category questions; record brand-mention share per site over time. This becomes the Factory retainer report's centerpiece proof metric (Phase 1.5). Full dashboard is Phase 2.
**Acceptance:** llms.txt deployed on all managed sites; entity sameAs present in schema; `.md` alternate published per article; monthly share-of-voice log exists.

### 5.9 Image engine

**Objective:** every post ships illustrated; images are a feature, not an afterthought (top Soro complaint category).
**Current state:** stock (Pexels) + generated selection exists; decision 2026-10-03: FLUX.2 Klein 4B default.
**Spec:**
- Per post: 1 featured thumbnail (1200×630) + 2 in-post images (1024w). Model: `black-forest-labs/flux.2-klein-4b` via OpenRouter (~$0.015/image, ~5–8s; text rendering verified).
- Style presets per site (photoreal, flat vector, 3D render, minimal) stored in brand profile; image prompt built from article brief + style.
- Featured image uploaded to WordPress media library and set as post thumbnail; in-post images inserted at H2 breaks with alt text = section summary.
- **In-post image selection = VLM relevancy gate (not blind AI generation):** for each of the 2–3 in-post slots, fetch the best Pexels stock candidate for the paragraph topic → JEV + vision model scores image↔paragraph relevancy 0–100 (same pattern as LBF's `AI_IMAGE_VERIFY` / `AI_VISION_MODEL` env). Score ≥90 → use the free stock image. Score <90 → generate with Klein 4B. The featured thumbnail is always AI-generated (brand control).
- Ultimate fallback: publish without image + flag.
- Store per image: prompt, model, cost, generation ms (feeds cost transparency + editor regen). **Every AI-generated image carries IPTC `TrainedAlgorithmicMedia` provenance metadata** — forward-looking signal, zero generation cost.
**Acceptance:** 100% of posts have a featured image; alt text present; per-image cost logged.

### 5.10 Hidden tricks & differentiators

These are the non-obvious edges competitors don't advertise:
1. **GSC feedback loop → decay refresh:** monthly job pulls GSC data; articles with >30% click decay over 90 days get an auto-generated refresh brief (new stats, new FAQ entries, re-publish as updated). Content refresh is a retention feature, not just acquisition.
2. **Competitor SERP-gap briefs:** brief agent receives top-3 ranking URLs' headings (DataForSEO SERP) and must list 3 subtopics they miss — the draft's unique angle. **Discourse appendix:** brief includes a last-30-days scan of what people actually say about the topic (Reddit/forums/social, API-free) — real questions, complaints, and phrasing that feed PAA, fan-out queries, and authentic voice.
3. **Orphan rescue linking** (§5.6): internal-link agent prioritizes pages with few inbound links.
4. **Update timestamps:** refreshes bump `dateModified` in schema (freshness signal).
5. **Programmatic local pages (upsell tie-in):** template engine for location/service pages (Local Business Factory, §7) — same quality gate applies. **Brief types:** Compact Keyword landing pages (400–500 words, exact-match H1, CTA), **comparison pages** ("[Client] vs [Competitor]" — fact-checked, neutral-toned, competitors linked), dedicated PAA pages for high-value questions. The brief agent selects an **intent template** (how-to, comparison, listicle, landing…) per article; templates are versioned with the tactics playbook.
6. **Per-post cost ledger:** every article carries its full input cost (LLM + images + data). Shown to operator; becomes the Phase 2 "radical transparency" customer feature.
**Acceptance:** decay job runs monthly and produces ≥1 refresh brief per site with decaying content; cost ledger row per article.

### 5.11 WordPress connector

**Objective:** first-class publishing to WordPress (launch priority #1).
**Build order:** REST connector first (Application Passwords — no plugin review, fully manageable, ships now). A wordpress.org **plugin** comes later as the SaaS distribution move (discoverability, one-click install). The connector must already do everything the plugin would do, so the plugin is a packaging step, not a rewrite.
**Spec — the connector must handle:**
- **Text rendering:** full HTML body with headings, lists, tables, FAQ blocks, CTA blocks; shortcode-safe (no raw shortcodes emitted unless allowlisted).
- **Image rendering:** featured image uploaded to media library and set as post thumbnail; in-post images uploaded + inserted at H2 breaks with alt text; srcset left to WP core.
- **Internal link fetch:** pull the site's existing posts/pages via REST to feed the internal-linking agent (existing `fetch_internal_links_tool` generalized to WP REST).
- **Meta:** Yoast / Rank Math / AIOSEO fields (title, description, canonical, OG), Article + FAQ JSON-LD (via meta or schema plugin fields).
- **Taxonomy:** categories/tags created on demand from the brief's mapping.
- **Guards:** duplicate prevention (§5.6), slug collision handling, outbound link 200-check pre-publish, draft (default for new sites) vs auto-publish modes.
- **Refresh:** updates `dateModified`, replaces featured image on refresh when applicable.
- **MCP interop:** WordPress ships its own MCP adapter and Elementor has MCP support — ContentFTE's MCP server (§5.13) stays the content-pipeline interface; for deep site ops (theme/layout changes) route through WP/Elementor MCP rather than re-implementing.
**Acceptance:** end-to-end publish of a gated article to a test WP site with meta, schema, featured image, and correct category — no manual steps.

### 5.12 Custom-site SDK

**Objective:** any custom/headless site integrates in minutes (launch priority #2).
**Spec:**
- REST API: `POST /articles` (submit brief/keyword), `GET /articles/{id}` (status, scores, cost), `POST /articles/{id}/approve`, `GET /articles/{id}/content` (HTML + metadata + images), webhooks (`article.ready`, `article.published`, `article.needs_review`).
- Auth: per-site API keys. Idempotency keys on all mutating calls; retries with backoff; every action audit-logged.
- Client libraries: JS/TS first, Python second. Docs with copy-paste quickstart.
**Acceptance:** a fresh Next.js site publishes its first article via SDK with <30 min integration (dogfooded on a test site).

### 5.13 MCP server

**Objective:** let AI assistants (Claude Code, etc.) drive ContentFTE directly.
**Spec tools:** `list_sites`, `get_brief`, `generate_article`, `get_article_status`, `get_image`, `publish_article`, `site_health`.
**Acceptance:** Claude Code can brief → generate → check status → publish an article through the MCP server end-to-end.

### 5.14 SEO data engine (OpenSEO hosted / DataForSEO / manual)

**Objective:** briefs grounded in real demand, with minimum day-one spend.
**Decision 2026-10-04: start with OpenSEO hosted** (verified at openseo.so/pricing).
**Provider selection via `SEO_DATA_PROVIDER` env:**
- `openseo` (default at start): hosted at $10/mo — includes $10 usage/mo (resets each cycle), extra top-ups never expire, $0.50 trial, cancel anytime. ~$0.05/keyword search, ~$0.08/backlink overview, ~$1.09 AI brand check; GSC data free. At 30 posts/mo (~$4.20 usage) the flat $10 covers it. Bonus: rank tracking, site audits, and their MCP server (`openseo.keyword_research` etc.) usable directly from the pipeline or Claude Code — free operator tooling. Caveat: included $10 resets monthly (use-it-or-lose-it); subscription must stay active.
- `dataforseo`: direct API when volume is proven. $1 trial → **$50 minimum top-up, funds never expire** ≈ ~450 posts of runway (~15 mo at 30 posts/mo). ~$0.11/post raw. Wins on per-post cost after ~7–8 months at 30 posts/mo. Free Sandbox (mock data) for build/test.
- `off`: no API calls. Keywords, volume, difficulty, intent, SERP notes entered **manually** per brief. Zero data cost; slower workflow. The honest bootstrap mode.
**Spec (when provider is on):** per keyword — search volume, keyword difficulty, intent classification, SERP snapshot (top 10 titles/headings for gap analysis in §5.10-2). Cached 30 days per keyword.
**Scaling reference (OpenSEO freelancer/agency estimator, verified 2026-10-04):** 370 keyword searches + 30 backlink checks + 200 local SERP checks + 15 sites × 20 keywords tracked weekly ≈ **$26.61/mo** ($10 base + $16.61 extra usage). ≈ **$1.77/site/mo at 15 clients** — data cost stays negligible at Factory scale. Local SERP checks (Google Maps/Local Finder via MCP, ~$0.005 each) are the cheap fit for local-client rank tracking; AI brand checks ($1.09 each) are the expensive one — use sparingly.
**Acceptance:** every brief contains volume/difficulty/intent + 3 SERP gaps (or the manual fields when `off`); cache hit rate visible in logs; monthly data spend per site logged.

### 5.15 Tactics library (playbook + skill pack)

**Objective:** the engine's tricks come from a maintained library, not hardcoded prompt lore.
**Spec:** two sibling resources, same content, two shapes —
- `ContentFTE-Tactics-Playbook.md`: the full distillation of both source systems — **Edward Sturm** (@buildinpublic) and **Daniel Agrici** (@AgriciDaniel; `claude-seo` 18.2k★ / `claude-blog` 2.3k★, MIT) — with per-tactic engine-wiring tables and source dates.
- `~/workspace/skills/seo-pack/`: the same knowledge as a Claude Code skill pack (`SKILL.md` + 13 `references/` files) so brief/draft/eval agents and any Claude Code session can load it directly.

Gray-area tactics are never named in product/docs/UI — only their white-hat mechanism is implemented, quietly (see skill pack `references/gray-policy.md`). The brief, draft, and eval agents reference the skill pack; the playbook is the human-readable source of truth. Re-check sources monthly and append new tactics with source + date; never remove silently.
**Acceptance:** brief/draft/eval prompts cite the skill pack; PAA atomization and video-script-seed outputs exist per article.

### 5.16 Site keyword ledger (campaign memory)

**Objective:** the engine works a *campaign*, not one-off posts. Every site has a remembered set of researched keywords it commits to for 30–60 days; nothing gets briefed off-ledger.
**Spec:**
- **Ledger table (Postgres):** one row per keyword per site: `keyword`, `intent` (informational/commercial/transactional/local), `volume`, `difficulty`, `priority_score`, `cluster_id`, `status` (`researched → approved → queued → briefed → drafted → published → ranking → won | lost | retired`), `target_url`, `research_snapshot` (volume/difficulty/SERP top-10 captured at brief time), `added_at`, `review_at` (30 or 60 days out, per site setting).
- **Lifecycle rule:** brief agent may only pull from `approved`/`queued` rows. No keyword, no brief — kills random one-off topics.
- **Priority scoring:** `priority_score = (volume × intent_value × winnability) / difficulty`, where `intent_value` weights transactional > commercial > informational, and `winnability` derives from domain authority vs SERP competitor strength. Engine always works the highest-scoring queued keyword next.
- **Cannibalization guard:** before a keyword enters `approved`, it must pass the intent-overlap check against all non-retired ledger rows (extends §5.3 triage). Overlap → merge into the existing row or differentiate the angle; never two rows competing.
- **Cluster mapping:** each keyword is assigned to a hub-and-spoke cluster at research time. The ledger tracks **cluster coverage %** (keywords with published pages ÷ keywords in cluster) — topical authority compounds at cluster level, not per keyword.
- **Coverage tracking per keyword:** PAA questions captured, fan-out queries targeted, atomized pages created, internal links placed. Progress is visible per keyword, not just "posts published."
- **Article lineage:** every article row references its `keyword_id` + the research snapshot. Later we can audit whether the research was right (predicted vs actual performance).
- **SERP snapshots & drift alerts:** `research_snapshot` stored at brief time; monthly re-check. If the SERP shifts materially (new strong competitor, AI Overview appears/disappears), flag the keyword's brief/page for update.
- **Ranking feedback loop:** rank tracking (GSC / OpenSEO) writes back to the ledger: `ranking` → `won` (page 1, stable) or `lost` (decayed past threshold). Lost keywords auto-generate refresh briefs (§5.10-1); won keywords free their slot for the next batch.
- **GSC query mining:** monthly job finds queries the site already earns impressions for with no targeting page → auto-suggests new ledger rows for operator approval. Formalizes what the cluster is accidentally winning.
- **Batch rotation ritual:** every 30/60 days (per site), operator reviews the ledger: retire `won` and dead keywords, approve the next research batch. Full history is kept — a retired loser is never blindly re-targeted.
- **Content calendar view:** the queue rendered as a 30/60-day calendar (keyword → scheduled week). Phase 1: operator-visible in the run console; Phase 2: customer dashboard (fills a known competitor gap — none of them have a real calendar).
**Acceptance:** zero published articles without a ledger row; priority queue always has a defined "next keyword"; rotation review produces a dated decision log per site.

---

## 6. Tavily economics & deep research (standard)

Tavily is **not** free infrastructure. Verified pricing 2026-10-03:

| Tier | Credits/mo | Price |
|---|---|---|
| Researcher (free) | 1,000 | $0 |
| Pay-as-you-go | — | $0.008/credit |
| Project | 4,000 | $30/mo |
| Bootstrap | 15,000 | $100/mo |

Basic search = 1 credit; advanced = 2 credits.

**Per-post budget:** deep research ≈ 6 advanced searches = 12 credits ≈ **~$0.10/post** at PAYG.

**Free-tier capacity:** 1,000 credits ÷ 12 credits/post ≈ **~83 posts/mo ≈ 2 clients at 30 posts/mo.** The 3rd client pushes into paid: Project $30/mo for 4,000 credits (≈333 posts) is the next step up.

**Product rule (corrected 2026-10-04):** deep research is **standard on every post** — factual accuracy is the product, not a tier. There is no lite-research upsell. Tavily is metered per site; when a site's budget is exhausted the run pauses and flags the operator (§5.3). The Local Business Factory bundle (§7) absorbs the cost into its retainer price rather than itemizing it.

## 7. The Local Business Factory (existing — ContentFTE plugs in)

The Factory **already exists** (Octively Local Business Factory repo): Next.js Studio dashboard, Node API server, site renderer (Astro renderer + visual editor, not yet polished), PostgreSQL (Neon/Drizzle), Upstash Redis/QStash, Cloudflare wildcard domains, MCP server (`lbf_create_site`, `lbf_list_tenants`, …), Jev decision points throughout, 9 vertical profiles, 16 template families, Pexels image-service (currently unwired), and `AI_IMAGE_VERIFY` / `AI_VISION_MODEL` env (VLM image gate — the pattern §5.9 reuses). **No new hosting needed.**

ContentFTE slots into the existing pipeline at **Convert → Upsell**:

```
Discover → Score → Generate → Outreach → Convert → Upsell
                                                  ▲
                                          ContentFTE engine
                                          (SEO blogging retainer)
```

**Integration points (Phase 1):**
- **Site inventory → ContentFTE:** converted tenants (on `*.octively.com` or custom domains) become ContentFTE sites automatically — business profile, services, location feed the Brand DNA (§5.1) and offer catalog (§5.5).
- **ContentFTE → renderer:** publish via the SDK (§5.12) against the Astro renderer; the renderer's visual editor stays the human touch-up surface.
- **Pexels wiring:** the Factory's unwired image-service + ContentFTE's VLM relevancy gate (§5.9) are the same work — wire once, both benefit.
- **Jev reuse:** Factory's Jev decision infrastructure (template choice, name validity) extends to ContentFTE's triage/publish routing.

**Package (to be validated):** done-for-you website (Factory) + ContentFTE SEO retainer (8–12 posts/mo, local service/location pages via §5.10-5, GMB-aware topics) + monthly proof report (posts, GSC movement, AI-visibility citations, cost ledger). Deep Research cost is absorbed in the retainer price, not itemized.

This is Phase 1.5: sell the service first (revenue + training data), build self-serve SaaS (Phase 2) second.

## 8. Unit economics (Phase 1, per post)

| Input | Cost |
|---|---|
| DeepSeek V4.1 Flash (research/brief/draft/revision, off-peak; `WRITER_MODEL` switchable to cheaper V4 Flash) | ~$0.01 |
| Frontier eval (1 pass; `CRITIC_MODEL` swappable) | ~$0.03 |
| JEV micro-decisions | ~$0.002 |
| Images (1 AI thumbnail + in-post via VLM gate; mostly free stock) | ~$0.02 |
| DataForSEO/OpenSEO (~$0.11 raw; ~$0.14 via OpenSEO hosted markup, inside the $10/mo flat at start) | $0.11 |
| Tavily deep research (6 advanced, standard on every post) | ~$0.10 |
| **Total per post** | **~$0.27** |

30 posts/mo ≈ **$8/mo** all-in (+$10 OpenSEO base = ~$18/mo total data+content at start; drops to ~$8/mo when migrated to DataForSEO direct). At $29/mo starter: ~60–70% gross margin before hosting/ops. With `SEO_DATA_PROVIDER=off` (manual): ~$0.16/post.

**Factory scale:** at 15 retainer clients, OpenSEO data ≈ $26.61/mo total (~$1.77/site/mo) — data cost does not meaningfully move with client count.

## 9. Phase 2 preview (deferred, not specced)

Multi-tenancy & site isolation, auth, Stripe/Lemon Squeezy billing for $29/$79/$149 tiers, customer dashboard (calendar, approvals, cost transparency, AI-visibility), API key self-service, white-label (Scale tier), usage metering & overage credits. Spec'd after the engine is live and the Factory upsell is selling.

## 10. Open questions

1. Postgres schema design — draft before migration.
2. ~~WordPress: dedicated plugin vs REST-only connector for v1?~~ **Answered 2026-10-04:** REST connector (Application Passwords) for v1 — manageable, no review process; wordpress.org plugin later as the SaaS distribution move.
3. Frontier critic default: benchmark GPT-6 Sol vs Sonnet 5.5 vs Gemini 4 Argon eval quality on 10 sample articles — then set `CRITIC_MODEL`.
4. Factory retainer price point — validate against first clients (must absorb ~$8/mo content cost + Tavily overage past 2 clients).
5. Image style presets — which 4 styles to ship at launch?
6. `SEO_DATA_PROVIDER=off` manual entry UX — minimal CLI form or markdown brief template?

---

## Appendix A — Phase 1 acceptance checklist

- [ ] V4.1 Flash pinned explicitly; old slug removed
- [ ] Postgres migration complete; Sheets retired
- [ ] Brand DNA profiles working; voice sub-score in eval
- [ ] 90+ gate with sub-score floor (no sub-score <80 publishes)
- [ ] Fact grounding: zero unsourced numeric claims in audit sample; fact-check gate runs before eval
- [ ] Sources box + 200-checked outbound links on every article
- [ ] Eval: citability sub-score present; all critic guidance falsifiable
- [ ] Triage: keyword cannibalization / intent-overlap check before brief
- [ ] Ledger: zero published articles without a keyword row; priority queue always has a defined next keyword; rotation review decision log per site
- [ ] Brief: discourse appendix + intent template selection; briefs pull only from approved/queued ledger rows
- [ ] GEO: `.md` alternate published per article; monthly share-of-voice log
- [ ] Images: IPTC provenance tags on AI-generated images
- [ ] Internal linking hardened (diversity, orphan rescue)
- [ ] TL;DR + FAQ + schema on every article
- [ ] llms.txt deployed per site; entity sameAs in schema
- [ ] 3 images/post (Klein 4B), alt text, cost logged
- [ ] GSC decay job running monthly
- [ ] WordPress end-to-end publish (meta, schema, featured image)
- [ ] SDK dogfooded on a test Next.js site (<30 min integration)
- [ ] MCP server end-to-end via Claude Code
- [ ] DataForSEO in every brief; 30-day cache
- [ ] Tavily metering per site; graceful degradation without Deep Research
- [ ] Per-post cost ledger complete
