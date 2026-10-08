# ContentFTE API surface

Base URL: `${CONTENTFTE_URL}`. All `/sdk/v1/*` routes take header
`X-Site-Key: ${CONTENTFTE_SITE_KEY}` (= engine `SDK_MASTER_KEY`; dev-open when the
engine has none set). Errors are `HTTP 4xx` with `{"detail": ...}`; service
dicts carry `{"error", "next"}` (actionable).

## REST routes (`/sdk/v1`)

| Method | Path | Purpose |
| :--- | :--- | :--- |
| GET | `/sites` | list sites |
| POST | `/sites` | create/update a site (`slug, name, site_type: wordpress\|custom, base_url`) |
| GET | `/sites/{slug}/health` | site health |
| GET | `/sites/{slug}/llms.txt` | site `llms.txt` (§5.8) from published articles — returns `{site, count, llms_txt}` (serve `.llms_txt`) |
| POST | `/articles` | submit a brief/keyword (idempotent per site+keyword) |
| GET | `/articles` | list articles (`site_slug`, `status`, `limit`, `offset`) |
| GET | `/articles/{id}` | status + scores + cost |
| POST | `/articles/{id}/generate` | run generation (briefed → drafted; slow) |
| POST | `/articles/{id}/approve` | approve / needs_review |
| POST | `/articles/{id}/publish` | mark published; **WordPress sites are pushed here** |
| POST | `/articles/{id}/refresh` | update an existing WP post in place (decay) |
| GET | `/articles/{id}/content` | unified delivery payload |
| GET | `/wp/posts/{id}` | read a WP post back (raw content + SEO meta) |
| GET | `/elementor/available` | Elementor REST probe |
| GET | `/elementor/posts/{id}` | current Elementor document |
| POST | `/elementor/posts/{id}` | replace the Elementor document |
| POST | `/elementor/articles/{id}/build` | compose an article as an Elementor doc |

## MCP tools (mounted at `/mcp`)

`contentfte_list_sites`, `contentfte_get_brief`, `contentfte_generate_article`,
`contentfte_get_article_status`, `contentfte_list_articles`,
`contentfte_get_image`, `contentfte_publish_article`,
`contentfte_refresh_article`, `contentfte_wp_post`, `contentfte_llms_txt`,
`contentfte_site_health`, `contentfte_elementor_available`,
`contentfte_elementor_document`, `contentfte_elementor_save`,
`contentfte_elementor_build`.

`contentfte_generate_article` = **submit + generate** in one call.

## Delivery payload (`GET /articles/{id}/content`)

```jsonc
{
  "id": 12, "title": "…", "slug": "…", "url": "https://site/blog/…",
  "excerpt": "Meta description…",
  "html": "<h2>…</h2>…",            // engine-rendered (no block comments)
  "faq_html": "<section class=\"faq-block\">…<details class=\"faq-item\" name=\"contentfte-faq\"><summary>Q</summary><p>A</p></details>…</section>",  // FAQ accordion for non-React sites
  "markdown": "## …",                // source
  "markdown_alternate": "---\n{…}\n---\n\n# Title\n\n…",  // agent-ready .md
  "schema": { "article": { "@type": "Article", … }, "faq": { "@type": "FAQPage", … } | null },
  "status": "published", "scores": { … }, "cost_usd": 0.07,
  "meta": { "brief": { … }, "faqs": [ { "question": "…", "answer": "…" } ] }
}
```

## Lifecycle

`briefed → drafted → approved → published` (`needs_review` on reject).
`publish_article` requires `approved`. Gate policy: overall ≥ 90, every
sub-score ≥ 80.

Publish behaviour by `site_type`:
- **wordpress** → pushes the post in the same call; response carries
  `wp: {ok, post_id, url, status, slug, categories, featured_media}`. Fail-open
  (`wp.ok=false`); `meta.wp_post_id` dedupes re-publishes.
- **custom** → status flip only; the site pulls `/content`.

## Clients

| Entry | Methods |
| :--- | :--- |
| TS `ContentFTEClient` | `submitArticle, getArticle, generateContent, approveArticle, publishArticle, refreshArticle, getContent, listSites, upsertSite, listArticles, llmsTxt, wpPost` |
| Python `ContentFTEClient` | `submit_article, get_article, generate_content, approve_article, publish_article, refresh_article, get_content, list_sites, upsert_site, list_articles, llms_txt, wp_post` |

## Environment

| Var | Side | Purpose |
| :--- | :--- | :--- |
| `SDK_MASTER_KEY` | engine | expected `X-Site-Key` (unset = dev-open) |
| `CONTENTFTE_URL`, `CONTENTFTE_SITE_KEY` | consumer | engine base + site key |
| `WP_BASE_URL`, `WP_USERNAME`, `WP_APP_PASSWORD` | engine | WordPress/Elementor push |
| `WP_RENDER_TARGET` | engine | `blocks` (default) \| `elementor` |
| `SITE_PUBLISH_WEBHOOK` | engine | custom-site webhook push target |
