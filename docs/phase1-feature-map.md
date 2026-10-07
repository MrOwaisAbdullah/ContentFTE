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
- **`sdk/`** — REST service (`service.py` → `server.py`), Python + TypeScript clients, quickstart. Customer sites pull articles without touching Python.
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

`lib/wp_render.py` emits **plain semantic HTML** into `post_content` via the WP REST API:

| Markdown | Emitted HTML |
|---|---|
| `# H2` … | `<h1>`–`<h6>` |
| paragraphs | `<p>` |
| `- / 1.` nested lists | `<ul>` / `<ol>` + nested lists |
| `>` | `<blockquote>` |
| GFM table | `<table><thead><tbody>` |
| ` ```lang ` fence | `<pre><code class="language-lang">` (escaped) |
| `**b** *i* `code` ~~s~~ ==mark==` | `<strong> <em> <code> <del> <mark>` |
| `![alt](src)` / `[t](u)` | `<img>` / `<a>` (prose brackets escaped `&#91;` vs shortcodes) |
| FAQ / CTA | `<section class="faq-block">…`, `<aside class="cta-block">…` |
| in-post images | `<figure class="wp-block-image">` injected after the nth `</h2>` |
| schema | `<script type="application/ld+json">` (Article + FAQPage) |

No CSS/JS is shipped — front-end styling comes from the theme (unstyled-but-valid
if the theme adds none).

## 4. Is it editable? (WordPress vs Elementor vs raw HTML)

**Answer: it is NOT code-only editing.**

### WordPress block editor (Gutenberg) — yes, visual editing
- On first open, content **without block delimiters loads as one Classic block**
  (official Gutenberg behavior: classic posts sit inside a `core/freeform` block).
- One click on **"Convert to Blocks"** runs Gutenberg's `rawHandler`, which splits
  our HTML into real blocks: `<h2>`→Heading, `<p>`→Paragraph, `<table>`→Table,
  `<figure>`→Image, `<pre>`→Code, `<blockquote>`→Quote. From then on the post is
  edited visually with block toolbars; markup is re-serialized with `<!-- wp:… -->`
  delimiters on save.
- Even without converting, the Classic block's rich-text toolbar edits text,
  images, links and tables directly. HTML editing is optional, not required.
- Docs: `wordpress/gutenberg` — *freeform README*, *rawHandler*, *Block Edit and
  Save > Validation*, *Serialization and parsing*.

### Elementor — renders, but not Elementor-editable
- Elementor stores its own JSON (`_elementor_data`); our HTML in `post_content`
  is foreign content. It **displays** (via the theme's `the_content()` or an
  Elementor **Post Content** widget in a Theme Builder single-post template), but
  Elementor's canvas can't visually edit it — edits go through the HTML/Text
  widget or the WP editor. Elementor's own docs: *Edit HTML in Elementor* (HTML
  widget), *Post Content widget*.
- Practical rule: **blog posts = WP block editor; landing pages = Elementor.**

### Custom sites (Astro/Next) — our `custom_site.py` payload
Same HTML (+ `.md` alternate + JSON-LD) delivered via SDK pull or webhook; the
site's own renderer owns styling.

### Optional future enhancement
Emitting `<!-- wp:paragraph -->`-style delimiters in `wp_render.py` would skip the
"Convert to Blocks" click entirely (post opens directly as blocks). Not needed for
correctness — one click today.
