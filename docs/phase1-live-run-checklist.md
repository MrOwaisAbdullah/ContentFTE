# Phase 1 live-run checklist

Operator steps that need real credentials / stores (everything else is code
+ tests). Run in order; each step says how to know it worked.

## 0. Prereqs (env)
Set in the run environment (GitHub Actions secrets / Dokploy / local `.env`):

| Var | Used by |
|---|---|
| `DATABASE_URL` | Postgres (Neon) store — **required for all cutover steps** |
| `GOOGLE_CREDENTIALS`, sheet name | Sheets reads (until cutover flip) |
| `SANITY_*`, `PEXELS_API_KEY`, `CLOUDFLARE_*` | publish + image pipeline |
| `WP_BASE_URL` / `WP_USERNAME` / `WP_APP_PASSWORD` | WordPress acceptance |
| `SDK_MASTER_KEY`, `SITE_PUBLISH_WEBHOOK` | SDK/MCP dogfood + custom-site push |
| `TAVILY_API_KEY`, `TAVILY_MONTHLY_BUDGET` | research + metering |
| `STORE_READ_SOURCE` | leave unset (=`sheets`) until step 3 |

## 1. Backfill Postgres from Sheets
```bash
python scripts/backfill_postgres.py --site <slug> --dry-run   # counts first
python scripts/backfill_postgres.py --site <slug>             # then write
```
✅ Expect `[backfill] ... counts={'keyword': N, 'brief': M, 'article': K}`
matching the sheets' row counts.

## 2. Verify zero drift (the gate)
```bash
python scripts/verify_cutover.py --site <slug>
```
✅ `"in_sync": true` and empty `missing_in_postgres` / `missing_in_sheets`
on both `keywords` and `articles`. Non-zero exit (2) = drift — reconcile
(missing rows usually mean a sheet row predates dual-write; re-run step 1).

## 3. Flip reads to Postgres
Only after a clean step 2:
```bash
export STORE_READ_SOURCE=postgres
```
⚠️ Until `run_stage`/agents are rewired to the `lib/store` read API, the live
pipeline still reads Sheets regardless of this flag — flipping the flag is
safe but not yet load-bearing. Rewiring is the remaining operational task.

## 4. Decay job smoke test
```bash
python scripts/decay_job.py --dry-run   # scans, writes nothing
python scripts/decay_job.py             # writes refresh briefs + ledger 'lost'
```
✅ Prints `scanned=N refresh_briefs=M`. Runs monthly via `pipeline.yml`
(`0 4 1 * *`). No-ops until step 1 populates articles.

## 5. SDK / MCP dogfood (Phase 1C acceptance, lines 84/86)
Start the app, then drive the full loop:
```bash
uvicorn main:app --port 8000
# REST
curl -H "X-Site-Key: $SDK_MASTER_KEY" localhost:8000/sdk/v1/sites
curl -H "X-Site-Key: $SDK_MASTER_KEY" localhost:8000/sdk/v1/sites/<slug>/brief
curl -H "X-Site-Key: $SDK_MASTER_KEY" -X POST localhost:8000/sdk/v1/articles \
     -d '{"site_slug":"<slug>","keyword":"best crm for agencies"}'
# -> approve -> publish (publish 409s until approved)
```
✅ article flows `briefed → approved → published`; `verify_cutover` still clean.
MCP: point Claude Code at `/mcp` (or `python -m mcp_server.server`) and run
`contentfte_list_sites → get_brief → generate_article → get_article_status →
publish_article`.

## 6. WordPress acceptance (TASKS line 80)
Fastest path — one command runs the full gated chain (submit → generate →
image → approve → publish) and verifies the result over WP REST, printing a
PASS/FAIL checklist (start the LocalWP site and export `WP_*` first):
```bash
python scripts/acceptance_wp.py
```

> **Status (2026-10-07):** PASSED on LocalWP `speedline` (WP 7.1 + Yoast 28.6) —
> 14/14 checks, post 97 (20 blocks, Article + FAQPage JSON-LD, 5 `<details>`
> FAQ items, featured 1280×720, in-post image, category SEO,
> `_yoast_wpseo_metadesc`). Manual Gutenberg check: opens with **no "Attempt
> Block Recovery"**, 5 `core/details` parsed. Full log: `docs/dev-log.md`.
Manual equivalent: with `WP_*` set, build a prepared post and publish as a draft:
```python
from lib.wordpress import WPConfig, WordPressConnector, build_prepared_post
cfg = WPConfig.from_env(); conn = WordPressConnector(cfg)
post = build_prepared_post(title="Test", markdown="# H\n\nBody",
                           faqs=[{"question":"Q","answer":"A"}],
                           categories=["SEO"], featured_image_path="hero.jpg",
                           inpost_images=[{"path":"in.jpg","alt":"x","after_h2":1}])
print(conn.publish(post, mode="draft"))
```
✅ In WP admin the draft has: rendered headings/lists/table/FAQ accordion/CTA, a
featured image + thumbnail set, in-post image at the H2, Yoast/Rank Math/
AIOSEO title+description, and an Article + FAQPage JSON-LD block in the body.
FAQs are a native `core/details` accordion (5 `<details>` items share
`name="contentfte-faq"`).

✅ **Block editability:** open the draft in the block editor — it must appear
as real Heading/Paragraph/List/Table/Image/Code blocks with **no "Attempt
Block Recovery"/invalid-block prompts**. If any block reports invalid, note
which one (that is the block-serialization validation gate) and we adjust its
markup in `lib/wp_render.py`. Also confirm `SITE`-published frontend output
is unchanged (block comments never render on the front end).

## 7. Elementor blog design (native REST, Elementor >= 3.27)
For sites that design blog pages in Elementor — **no MCP plugin required**
(Elementor 3.27+ registers document meta with `show_in_rest`; feature-map §4):
```bash
# 1. WP app password from an Administrator (meta writes; JSON-LD in meta is
#    not kses-filtered — a lower role can fail the meta update)
export WP_BASE_URL=https://your-site.com
export WP_USERNAME=admin
export WP_APP_PASSWORD="xxxx xxxx xxxx xxxx xxxx xxxx"
# 2. preflight probe (service: elementor_available / MCP:
#    contentfte_elementor_available / GET /sdk/v1/elementor/available)
# 3. build an article as an Elementor document:
#    POST /sdk/v1/elementor/articles/{id}/build {"mode":"draft"}
#    (equivalent: WP_RENDER_TARGET=elementor on the publish path)
```
✅ Probe returns `{"available": true, "meta_keys": ["_elementor_data", …]}`;
the draft opens in Elementor as container > heading (H1) + html widget + a
native **Accordion widget** for the FAQs (WP title hidden via page settings),
body plain HTML — no block comments — with Article/FAQ JSON-LD intact. Re-run
the build → same `wp_post_id`
(stored in `article.meta`) — **no duplicate posts**; an Elementor write
failure reports `elementor.ok=false` while the post remains valid
(fail-open).

⚠️ Cache caveat: REST meta writes bypass `Document::save()` invalidation of
`_elementor_css` (Elementor 4.2) — if styles look stale, re-save once inside
Elementor (the API response carries `cache_note`).

Note: the earlier EMCP/opencode wiring (`mcp.emcp-tools` in `opencode.json`)
was adopted, then **reverted** — native REST covers the automated path.

## Rollback
- Reads: unset `STORE_READ_SOURCE` (back to Sheets) — dual-write keeps both in sync.
- Postgres: the mirror is best-effort/idempotent; re-running step 1 converges.
