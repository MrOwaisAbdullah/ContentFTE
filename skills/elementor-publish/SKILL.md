---
name: elementor-publish
description: Publish and edit WordPress blog posts as native Elementor documents through ContentFTE's own REST/MCP ops (Elementor >= 3.27 show_in_rest meta — no third-party MCP or plugin). Use when a site designs blog pages in Elementor, when the task mentions Elementor, page builders, WP layout writes, or when WP_RENDER_TARGET=elementor / contentfte_elementor_* tools are involved.
---

# Elementor publish via ContentFTE (native REST)

Writes Elementor documents with the **same WP application-password
connection** the connector already uses — Elementor >= 3.27 registers its
document meta with `show_in_rest`, so no MCP server, proxy, or plugin of
ours is required. Everything here rides the standard layering:
`sdk/service.py` → REST `/sdk/v1/elementor/*` → MCP `contentfte_elementor_*`.

## Prerequisites (one-time, operator)

1. WordPress with **Elementor >= 3.27** (older versions don't expose meta).
2. Env: `WP_BASE_URL`, `WP_USERNAME`, `WP_APP_PASSWORD` — the app password
   must belong to an **Administrator**: kses strips `<script>` from post
   *content* but not from *meta*, so JSON-LD in the html widget only
   survives with full caps (a lower role can fail the meta update).
3. Preflight: `GET /sdk/v1/elementor/available` (or MCP
   `contentfte_elementor_available`). Expected:
   `{"available": true, "meta_keys": ["_elementor_data", …]}`.
   `available: false` ⇒ Elementor too old/not active — fall back to the
   Gutenberg path (this is the default, `WP_RENDER_TARGET=blocks`).

## Render target

- `WP_RENDER_TARGET=blocks` (default): Gutenberg block markup, opens as
  real editable blocks.
- `WP_RENDER_TARGET=elementor`: `build_prepared_post` renders the body as
  **plain HTML** (no `<!-- wp: -->` comments; FAQ/CTA unwrapped) so it fits
  Elementor's `html` widget; `publish()` then writes the document.
- Unknown values fall back to `blocks` — a typo never yields an
  unrenderable body.

## The document write (create-then-write, fail-open)

1. The WP post is created **first** with plain-HTML content (valid standard
   post on its own).
2. Only then is the Elementor document written:
   container > `heading` widget (carries the H1) + `html` widget (body +
   Article/FAQ JSON-LD), page settings `{"hide_title": "yes"}`.
3. Any failure in step 2 is **caught** → `result["elementor"] =
   {"ok": false, "error": …, "fallback": …}` — the post still exists and
   is never re-created (no duplicate posts).

## Ops (same behavior on every surface)

| Layer | Call |
|---|---|
| service | `elementor_available()` / `elementor_document(post_id, post_type)` / `elementor_save(post_id, elements, page_settings=…)` / `elementor_build(article_id, post_id=None, mode="draft")` |
| REST | `GET /sdk/v1/elementor/available` · `GET/POST /sdk/v1/elementor/posts/{id}` · `POST /sdk/v1/elementor/articles/{id}/build` |
| MCP | `contentfte_elementor_available` / `_document` / `_save` / `_build` (complex args as JSON **strings**, parsed at the tool edge) |

- `elementor_build` composes from the article's `content_md`, stores
  `article.meta.wp_post_id`, and **reuses it** on later builds → repeat
  builds are idempotent. With `post_id` (explicit or stored) it saves onto
  the existing post instead of creating another.
- Every save/build is audit-logged (`elementor.save`,
  `article.elementor_build`).
- `post_type` is whitelisted (`posts`|`pages`) — it goes into a URL path.

## Element shape (what you pass to `elementor_save`)

```json
[{"id": "a1b2c3d", "elType": "container", "isInner": false,
  "settings": {"content_width": "full"},
  "elements": [{"id": "b2c3d4e", "elType": "widget", "widgetType": "heading",
                "settings": {"title": "…", "header_size": "h1"}, "elements": []},
               {"id": "c3d4e5f", "elType": "widget", "widgetType": "html",
                "settings": {"html": "<p>…</p>"}, "elements": []}]}]
```

- `id`: 7-char hex, unique per element (the editor's format).
- `_elementor_data` is a **string** containing a plain JSON **array** of
  root elements — NOT the legacy `{"version": "0.4", "content": […]}`
  wrapper (accepted on read only).
- Widgets you'll use: `heading` (`title`, `header_size`, `align`),
  `html` (`html`), `text-editor` (`editor`).
- Read-modify-write: fetch `contentfte_elementor_document`, edit the
  array, post it back to `contentfte_elementor_save`. Omit
  `page_settings` to keep the settings the editor owns.

## Verify + caveats

- After a build: the post opens in Elementor with the two widgets; the
  public front end shows the body; JSON-LD `<script>` is intact in the
  html widget.
- **CSS cache:** REST meta writes bypass Elementor's `Document::save()`
  invalidation of `_elementor_css`/`_elementor_element_cache` (4.2), so
  styles can lag — responses carry `cache_note`; re-save once in the
  editor if the page looks stale.
- Reads never mutate; saves replace the whole root array (take a
  `contentfte_elementor_document` snapshot first if you need an undo).
- Interactive drag-drop sessions / widget-schema discovery still belong to
  a page-builder MCP editor — this skill covers the *automated publish*
  path only (spec §5.13 split: connector owns publish, layouts stay a
  separate concern).

## References

- `lib/elementor.py` (client + builder), `lib/wordpress.py`
  (`_resolve_render_target`, `_write_elementor`), `sdk/service.py`
  (elementor ops), feature-map §4, live-run checklist §7.
- Elementor REST meta: `register_meta(…, show_in_rest)` in Elementor ≥ 3.27
  (`_elementor_data` schema type: string).
