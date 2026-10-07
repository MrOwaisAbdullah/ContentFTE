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

## 6. WordPress acceptance (Phase 1B line 75)
With `WP_*` set, build a prepared post and publish as a draft:
```python
from lib.wordpress import WPConfig, WordPressConnector, build_prepared_post
cfg = WPConfig.from_env(); conn = WordPressConnector(cfg)
post = build_prepared_post(title="Test", markdown="# H\n\nBody",
                           faqs=[{"question":"Q","answer":"A"}],
                           categories=["SEO"], featured_image_path="hero.jpg",
                           inpost_images=[{"path":"in.jpg","alt":"x","after_h2":1}])
print(conn.publish(post, mode="draft"))
```
✅ In WP admin the draft has: rendered headings/lists/table/FAQ/CTA, a
featured image + thumbnail set, in-post image at the H2, Yoast/Rank Math/
AIOSEO title+description, and an Article + FAQPage JSON-LD block in the body.

✅ **Block editability:** open the draft in the block editor — it must appear
as real Heading/Paragraph/List/Table/Image/Code blocks with **no "Attempt
Block Recovery"/invalid-block prompts**. If any block reports invalid, note
which one (that is the block-serialization validation gate) and we adjust its
markup in `lib/wp_render.py`. Also confirm `SITE`-published frontend output
is unchanged (block comments never render on the front end).

## Rollback
- Reads: unset `STORE_READ_SOURCE` (back to Sheets) — dual-write keeps both in sync.
- Postgres: the mirror is best-effort/idempotent; re-running step 1 converges.
