# Phase 1 Feature Map

What was added/removed on `contentfte-phase1-engine-wp-sdk` vs `master`,
and why it matters. **72 files added · 18 modified · 4 removed · +9,751 lines · 166 tests.**

---

## 1. New capabilities

### 1.1 Content engine (`lib/`)
| Module | What it does | Benefit |
|---|---|---|
| `db.py` | SQLAlchemy models (Site, Brand, KeywordLedger, Brief, Article, ImageLog, ShareOfVoice, TavilyUsage, AuditLog); sqlite fallback | Real database under the old Sheets-only pipeline: queries, audits, idempotent re-runs |
| `brand_dna.py` | Versioned brand profile: tone sliders, banned phrases, signature phrases, reading level | Consistent voice across every post; safe for client brands |
| `brief_templates.py` | Structured brief builders (PAA, comparison, local, disambiguation) | Briefs are reproducible, not ad-hoc prompts |
| `tactics.py` + `tools/tactics_tool.py` | 13-ref SEO playbook: PAA atomization → `/faq/` pages, Comparison Page Spec, Cluster Plan, keyword intent classifier | More content surface per keyword → more ranking coverage |
| `decay.py` + `scripts/decay_job.py` | GSC click-decay detection (>30% over 90d) → auto refresh briefs (major/minor), keyword ledger → `lost` | Content stays fresh automatically; ranking losses trigger work, not silence |
| `share_of_voice.py` | Monthly AI-visibility share-of-voice per brand | Sellable metric to clients (AI search is the new SERP) |
| `cost_ledger.py` + `tools/ledger_tool.py` | Per-article + per-image costs, rotation review, queue health | No surprise API bills; proves ROI per post |
| `eval_gate.py`, `factcheck.py`, `linkguard.py` | Pre-publish QA: score gates, claim verification, dead-link checks | Fewer embarrassing posts; less manual review |
| `image_provenance.py`, `image_vision.py` | IPTC AI-provenance stamp (JPEG APP1/PNG iTXt), VLM topic-relevancy ≥90/100 gate | Compliance + no off-topic stock photos |
| `store.py` + `scripts/backfill_postgres.py`, `verify_cutover.py` | Sheets↔Postgres dual-write, read API, drift report | Zero-risk cutover: flip only after a clean drift gate |
| `wp_render.py`, `wordpress.py` | Markdown → WP-safe HTML, Yoast/RankMath/AIOSEO meta, Article+FAQ JSON-LD, WP REST publish | One-command publish with full SEO metadata |
| `custom_site.py` | Astro/Next payload (HTML + `.md` + schema) + `SITE_PUBLISH_WEBHOOK` push | Non-WP sites consume the same content |
| `factory.py` + `tools/factory_tool.py` | Business profile → Brand DNA + offer catalog (§7) | Onboard a local business in one call → retainer revenue |
| `tavily_meter.py`, `seo_provider.py` | API budget metering, keyword metrics | Cost-bounded research |

### 1.2 Access layers (new — repo had none)
- **`sdk/`** — REST service (`service.py` → `server.py`), Python client, and the **npm package `content-fte`** (`sdk/package.json`, one `npm install content-fte`): typed TS client + React renderer (`ContentFTEArticle` — title `<h1>`, GFM, `==highlight==` → `<mark>`, heading ids, FAQ section, Article+FAQPage JSON-LD, sanitized via rehype-sanitize) + framework-agnostic `contentfte-prose.css`. Built with tsup (ESM+CJS+`.d.ts`), smoke-tested via `react-dom/server`. Quickstart in `sdk/quickstart.md` (React/Next/Astro/plain-HTML patterns). **Published:** [`content-fte@0.1.0`](https://www.npmjs.com/package/content-fte) on npm.
- **`mcp_server/`** — `contentfte_*` tools over Streamable HTTP → Claude Code/any agent drives the pipeline.

### 1.3 Agent wiring (modified)
20+ new tools wired into brief/draft/eval/insertion/posting agents; image pipeline
(stock-first, VLM+Jev gate, fail-open, per-slot cost log); prompts cite the SEO skill pack.

### 1.4 Skill pack (`skills/seo-pack/`, 14 files)
Tracked SEO playbook usable by any agent run (was untracked/generic before).

### 1.5 Jobs (`pipeline.yml` + scripts)
Monthly decay cron, cutover tooling, Discord-gated approvals unchanged.

## 2. Removed
- `QWEN.md` (stale doc), 3 stray `tmp*.png` — **nothing functional deleted.**

---

## 3. How the blog renders (text, tables, images, code)

`lib/wp_render.py` emits **Gutenberg block-delimited HTML** (default) into
`post_content` via the WP REST API — every top-level element is wrapped in
`<!-- wp:… -->` so the post opens in the block editor as **real blocks, with no
manual "Convert to Blocks" step**. `blocks=False` returns plain HTML (used for
the Astro/Next custom-site payload).

| Markdown | Emitted (block mode) |
|---|---|
| `# H1`…`### H3` | `<!-- wp:heading -->` / `<!-- wp:heading {"level":3} -->` + `<hN>` |
| paragraphs | `<!-- wp:paragraph --><p>…</p>` |
| `- / 1.` nested lists | `<!-- wp:list -->` / `<!-- wp:list {"ordered":true} -->` |
| `>` | `<!-- wp:quote -->` + `<blockquote class="wp-block-quote"><p>…</p>` |
| GFM table | `<!-- wp:table -->` + `<figure class="wp-block-table"><table>…` |
| ` ```lang ` fence | `<!-- wp:code -->` + `<pre class="wp-block-code"><code>` (escaped; language class omitted — it would fail block validation) |
| `---` | `<!-- wp:html --><hr>` (zero-validation escape hatch) |
| `**b** *i* `code` ~~s~~ ==mark==` | `<strong> <em> <code> <del> <mark>` |
| `![alt](src)` / `[t](u)` | `<img>` / `<a>` inside the paragraph block (prose brackets escaped `&#91;` vs shortcodes) |
| FAQ | accordion — `core/details` blocks: `<!-- wp:details --><details class="wp-block-details" name="contentfte-faq"><summary>Q</summary>` + inner `core/paragraph` answers (plain `<details>` inside `<section class="faq-block">` in non-block mode) |
| CTA | `<!-- wp:html --><section…><aside class="cta-block">…` (custom classes round-trip verbatim) |
| in-post images | `<!-- wp:image --><figure class="wp-block-image"><img … /></figure>` injected after the nth heading block's closing comment |
| schema | `<script type="application/ld+json">` (Article + FAQPage) |

No CSS/JS is shipped — front-end styling comes from the theme (unstyled-but-valid
if the theme adds none). Residual risk: block *validation* compares our markup to
Gutenberg's regenerated save markup; anything that mismatches shows an
"Attempt Block Recovery" prompt (content is never lost). Checklist step 6
verifies a clean open on a real WP; `blocks=False` is the escape hatch.

## 4. Is it editable? (WordPress vs Elementor vs raw HTML)

**Answer: it is NOT code-only editing, and no manual conversion is needed.**

### WordPress block editor (Gutenberg) — yes, visual editing, zero clicks
- Posts are published **already serialized as blocks** (`<!-- wp:heading -->`,
  `<!-- wp:paragraph -->`, `<!-- wp:table -->`, `<!-- wp:image -->`, …) — they
  open directly as Heading/Paragraph/Table/Image/Code blocks with normal
  toolbars. The "Convert to Blocks" step does not exist in this flow.
- Elements we can't guarantee byte-identical to Gutenberg's save markup (hr,
  FAQ/CTA custom classes) are wrapped in `<!-- wp:html -->`, whose raw source
  round-trips verbatim — **never** a validation warning.
- Docs: `wordpress/gutenberg` — *freeform README*, *rawHandler*,
  *Serialization and parsing*, *Block Edit and Save > Validation*.

### Elementor sites — two supported paths
1. **Zero-setup (works today):** Elementor **Theme Builder → single post
   template** with a **Post Content** widget. Our block HTML renders inside the
   template, styled by the design; the writer edits in the WP block editor
   (Edit with WordPress). Elementor's own JSON is untouched.
2. **Native Elementor documents — BUILT:** since Elementor 3.27 its document
   meta is registered with `show_in_rest`, so the same WP application-password
   connection reads/writes layouts — **no MCP server, no plugin of ours**:
   - Switch: `WP_RENDER_TARGET=elementor` (or
     `build_prepared_post(render_target="elementor")`) renders the body as
     **plain HTML** (no block comments) for Elementor's `html` widget;
     default stays `blocks` (Gutenberg). FAQ/CTA render unwrapped too.
   - `lib/elementor.py` — `ElementorClient` (OPTIONS probe → is
     `_elementor_data` in the REST schema?), pure `build_blog_page_data()`
     (one container > heading widget + html widget, 7-char hex ids like the
     editor), `elementor_meta()`. `_elementor_data` is a **string** holding a
     plain JSON **array of root elements** — not the legacy
     `{"version":"0.4","content":[…]}` wrapper (accepted on read only).
   - `WordPressConnector.publish()` creates the post **first** (plain-HTML
     fallback content), then writes the document → an Elementor failure
     **fails open** (`result["elementor"]={"ok":false,"error":…}`) and can
     never duplicate the post.
   - Ops on every surface: service `elementor_available/_document/_save/
     _build` → REST `/sdk/v1/elementor/*` → MCP `contentfte_elementor_*`
     (complex inputs as JSON strings). Builds store `article.meta.wp_post_id`
     and reuse it — repeat builds are idempotent.
   - Caveats: REST meta writes bypass Elementor's `Document::save()`
     invalidation of `_elementor_css` (Elementor 4.2) → responses carry
     `cache_note` (re-save in-editor if styles lag); writes need an
     **Administrator** app password (kses strips `<script>` from post content
     but not from meta → JSON-LD survives inside the html widget).
   - Interactive drag-drop editing sessions still belong to an MCP editor;
     the automated layout write above is native. `lib/wordpress.py` keeps the
     spec §5.13 split: connector owns *publish*, layouts are separate.
   - Reverted: the `mcp.emcp-tools` opencode wiring (adopted, then removed —
     native REST made it redundant). See `skills/elementor-publish` for the
     workflow.
- Rule of thumb: **blog posts → WP block editor (default) or
  `WP_RENDER_TARGET=elementor`; landing pages → Elementor (manual/MCP).**

### Custom sites (Astro/Next) — `custom_site.py` payload
Same HTML **without** block comments (`blocks=False`) + `.md` alternate +
JSON-LD, delivered via SDK pull (`GET /sdk/v1/articles/{id}/content`, the
unified payload) or webhook; the site's renderer owns styling.

Two consumption paths, both from the `content-fte` npm package:
- **React/Next** — `<ContentFTEArticle content={payload}>` renders everything
  (title is the H1 since the pipeline never emits one in the body; body opens
  with the TL;DR blockquote → H2s), plus `content-fte/contentfte-prose.css`.
- **Astro/plain HTML** — render `payload.html` inside
  `<article class="cfte-prose">`, inject `payload.schema` as JSON-LD
  (`<` → `\u003c`), no React required.
