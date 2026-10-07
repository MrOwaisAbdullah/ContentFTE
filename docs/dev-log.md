# Development Log

Running record of ContentFTE development sessions. Newest entries first.
Every entry lists what changed, how it was verified, and the commit(s) — so a
future session can reconstruct *why* the code looks the way it does.

> Conventions: append a dated entry per work session (or per merged chunk).
> Never paste secrets (app passwords, API keys) — reference the env var
> instead. Cross-reference `TASKS.md` (task tracker + change table) and
> `docs/phase1-live-run-checklist.md` (acceptance criteria).

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
  README refreshed for the published SDK.
- Tests: `tests/test_wp_render.py` (accordion, plain mode, empty), 
  `tests/test_elementor.py` (accordion widget, FAQ-off-the-html-widget,
  publish branch). +3 tests → 212.

### Open at end of session
- [ ] Full-generation acceptance re-run (run 4 used seeded content).
- [ ] Push/merge the branch (23 commits ahead of `master`).
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
