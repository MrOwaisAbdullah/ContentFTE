# Tool parity — Sanity & Google Sheets → WordPress / custom sites

Inventory of what the original pipeline does against **Sanity CMS** (the
publishing target) and **Google Sheets** (the pipeline's state/queue store), and
where each operation lives in ContentFTE — so the same operations are possible
against **WordPress** (`site_type="wordpress"`) and **any custom site**
(Astro / Next / React, `site_type="custom"`).

Legend: ✅ have it · ⚠️ partial / needs a decision · ❌ missing · ➖ n/a by design

---

## A. Sanity operations → ContentFTE capabilities

| # | Sanity operation (today) | ContentFTE equivalent | Surface | WP | Custom |
| :-- | :--- | :--- | :--- | :-- | :-- |
| A1 | Assemble + publish a post (Portable Text): `SanityAdapter.create_document` / `post_blog`, `tools/tools.py::post_to_sanity_tool` | `service.publish_article` → `_wp_push` builds the body (Gutenberg blocks), meta (Yoast/RankMath/AIOSEO), Article+FAQ JSON-LD, categories/tags, featured + in-post images | `publish_article` · `POST /sdk/v1/articles/{id}/publish` · `contentfte_publish_article` | ✅ | ✅ (status flip; content via `/content` pull) |
| A2 | Upload an image/asset: `upload_image` | `WordPressConnector.upload_media` + `_wp_images` (featured/in-post slots from `meta.images`) | internal to publish | ✅ | ⚠️ payload carries image **URLs** (`meta.images`); no upload/hosting endpoint |
| A3 | Resolve author/category refs: `ensure_document_exists`, `resolve_categories_to_refs`, `list_categories`, `tools/tools.py::get_existing_categories_tool` | `_ensure_term("categories"/"tags", name)` + `default_category()`; author = the WP app-password user | internal | ✅ | ➖ templates own their taxonomy |
| A4 | Internal link discovery: `fetch_internal_links`, `tools/tools.py::fetch_internal_links_tool`, orphan rescue in `tools/linkguard_tool.py` | `WordPressConnector.fetch_internal_links(query)` | internal (used during generation) | ✅ | ❌ no source — needs the site's own sitemap/API (decision) |
| A5 | List/search existing posts (dedupe): `list_posts`, `find_post_by_title` | `list_posts()`, `existing_slugs()`, `meta.wp_post_id` dedupe; enumerate via `list_articles` | `contentfte_list_articles` · `GET /sdk/v1/articles` · clients | ✅ | ✅ |
| A6 | Read a post's content back: `get_post_content_markdown` | `WordPressConnector.get_post(post_id)` (`?context=edit` → raw content + registered meta) | `wp_post` · `GET /sdk/v1/wp/posts/{id}` · `contentfte_wp_post` | ✅ | ✅ (`get_article`, `/content`) |
| A7 | Update/refresh a live post (decay workstream): `update_post_content` | `service.refresh_article` → `WordPressConnector.update_post` (content + SEO meta + taxonomy; never creates/un-publishes) | `refresh_article` · `POST /sdk/v1/articles/{id}/refresh` · `contentfte_refresh_article` | ✅ | ✅ (re-pull payload) |
| A8 | Markdown → Portable Text blocks: `_markdown_to_processed_blocks` | `wp_render.markdown_to_wp_html(md, blocks=True)` | internal | ✅ | ✅ (blocks=False) |
| A9 | Site-level agent index (GEO §5.8) `llms.txt` | `service.llms_txt` composes it from the site's published articles (`lib.geo.generate_llms_txt`) | `llms_txt` · `GET /sdk/v1/sites/{slug}/llms.txt` · `contentfte_llms_txt` | ✅ (site serves it) | ✅ (site serves it) |

## B. Google Sheets operations → ContentFTE (Postgres + service)

Sheets was the pipeline's database; ContentFTE replaced it with Postgres tables
+ the service layer, so these are **target-independent** (identical for WP and
custom sites).

| # | Sheets operation (today) | ContentFTE replacement | Surface |
| :-- | :--- | :--- | :--- |
| B1 | Claim next keyword: `get_keyword_tool` (ContentSpark_Keywords queue) | `get_brief(site_slug)` over the `keyword_ledger` (§5.16: approved/queued, priority-sorted) | `contentfte_get_brief` · `GET /sdk/v1/sites/{slug}/brief` |
| B2 | Queue state writes: `manage_sheet_data`, `release_keyword_claim`, `clear_keyword_claim` | `keyword_ledger.status` (`set_status`), `article.status` | internal |
| B3 | `research_data`, `content_briefs` rows | `Article.meta.brief` + ledger `research_snapshot` | internal |
| B4 | `generated_posts` (content, summary, score) | `Article.content_md`, `summary`, `faqs`, `scores` | `get_article` |
| B5 | `published_posts` | `Article.status="published"` + `publish_article` | `publish_article` |
| B6 | `claims_audit`, `review_feedback_log` | `AuditLog` rows | internal |
| B7 | `freshness sweep`, `performance` (decay) | `lib/decay.py::classify_refresh` | ⚠️ produces refresh intent — needs A7 to apply it |
| B8 | `model_usage_log`, `image_logs` | still Sheets in the fallback runner (pipeline **telemetry**, not a site op) | ➖ not a publishing tool |

---

## Gaps & decisions

| Gap | Detail | Proposal |
| :--- | :--- | :--- |
| **G1 — refresh/update a live post** (A7) | ✅ **DONE** — `refresh_article` (service + `POST /sdk/v1/articles/{id}/refresh` + `contentfte_refresh_article` + clients). WP: updates the existing post in place (content + SEO meta + taxonomy, status untouched); custom: returns a pull/re-deliver instruction. |
| **G2 — read a WP post back** (A6) | ✅ **DONE** — `WordPressConnector.get_post(post_id, context="edit")` + `service.wp_post` + `GET /sdk/v1/wp/posts/{id}` + `contentfte_wp_post` + clients (raw content + registered SEO meta). |
| **G3 — internal links for custom sites** (A4) | Custom sites have no post store to query. | Decision: feed the site's sitemap/URL list into the engine, or generate links against the engine's own article list (`list_articles`). |
| **G4 — image hosting for custom sites** (A2) | Payload carries image URLs; the engine doesn't host/upload for custom sites. | Decision: point `meta.images` at the customer's CDN/bucket, or add an upload endpoint to their side. |
| **G5 — scheduling / delete** | Neither Sanity nor the engine had these (Sanity adapter is create/update only). | Not a parity gap. Flag only if the factory's `BlogConfig.scheduledFor` needs it. |

**Conclusion:** every operation the Sanity + Sheets pipeline performs is
available for **WordPress** and **custom** sites. The only remaining items are
the two custom-only inputs — internal-link source (G3) and image hosting (G4) —
which need a product decision, not a tool. Sheets has no target dependency — it
was replaced by Postgres + the service layer, so it is complete for both targets.

### Recommendations from research

- **G2 read-back** (done): WP returns raw content + registered `meta` only with
  `context=edit`; custom meta must be `register_meta(..., 'show_in_rest' => true)`
  on the WP side (Yoast/Rank Math do this for their keys already).
- **G3 internal links (custom sites):** build the link index from the site's own
  **sitemap** (`sitemap.xml`) or, symmetrically, from the engine's own article
  list (`GET /sdk/v1/articles?site_slug=…&status=published`) — mirroring how the
  DatoCMS/Astro pattern derives `buildSitemapUrls()` from a posts query. Keep
  contextual, descriptive anchors (3–8 in-body links per post).
- **G4 image hosting (custom sites):** the payload already carries image **URLs**.
  Recommendation: presigned **PUT** to object storage (Cloudflare **R2** / S3) or
  a public bucket + CDN — the standard S3 behavior R2 supports. Avoid routing
  uploads through the engine; let the customer's bucket/CDN own hosting.
- **Site indexes (done + remaining):** site-level **`llms.txt`** is now exposed
  (`GET /sdk/v1/sites/{slug}/llms.txt`), composed from published articles — the
  companion to the per-article `markdown_alternate` (`.md`). A **sitemap** stays
  site-owned (every framework emits its own; e.g. LBF's `sitemap.xml.ts`).

See also: `docs/site-onboarding-flow.md`, `docs/local-business-factory-integration.md`,
`docs/phase1-feature-map.md`.
