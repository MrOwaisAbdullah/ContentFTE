---
name: elementor-publish
description: Design and edit WordPress blog pages/posts in Elementor through the EMCP Tools MCP server (msrbuilds/elementor-mcp). Use when building Elementor layouts for blog posts, designing landing pages on a WordPress site, or when EMCP/emcp-tools MCP tools are available and the task mentions Elementor, page builders, or WP visual design.
---

# Elementor blog design via EMCP Tools

Turns a WordPress site into an MCP server (526 tools, 231 free) so an agent can
build **native, hand-editable** Elementor designs — no hand-written
`_elementor_data`. Repo: `msrbuilds/elementor-mcp`.

## Prerequisites (one-time, operator)

1. WordPress 6.9+ / PHP 8.1+; Elementor 3.20+ (4.0+ for atomic elements) if the
   target uses Elementor. Install `emcp-tools-*.zip` from the repo's Releases →
   activate → **EMCP Tools → Page Builders** → pick Elementor.
2. Env vars set **before starting opencode** (the MCP config in `opencode.json`
   interpolates them):
   `WP_BASE_URL`, `WP_USERNAME`, `WP_APP_PASSWORD` (WP Application Password).
3. Restart opencode → `emcp-tools` server connects via
   `npx @msrbuilds/emcp-proxy`. Tools are named `emcp-tools-<ability>`
   (internal `emcp-tools/<ability>`).
4. **Writes ship disabled** (377/526 off). In **EMCP Tools → Tools** enable the
   write tools needed (layout/widgets/page management), Save, then reconnect
   the client so the tool list refreshes.

## Widget workflow — discover → inspect → act

Never guess widget params:

1. **Discover:** `emcp-tools-list-widgets` (filter by tier/category/search).
2. **Inspect:** `emcp-tools-get-widget-schema` (add `full: true` for raw controls).
3. **Act:** `emcp-tools-add-free-widget` (Pro: `add-pro-widget`),
   `emcp-tools-update-widget` to edit an existing one.

## Blog post design workflow

1. **Content first:** pull the finished article from ContentFTE
   (`GET /sdk/v1/articles/{id}/content` — HTML/Markdown/JSON-LD) or create the
   post via the WP REST connector. Post body stays Gutenberg blocks
   (`lib/wp_render.py`); the Elementor *template/page* provides the design.
2. **Structure:** page/layout tools — containers (`elType: "container"`,
   not legacy section/column) → widgets (heading, text-editor, image, button,
   html for FAQ/CTA). Elementor doc shape:
   `content[] → {id, elType, widgetType, settings, elements}`.
3. **Hero/CTA/related-posts** belong in the Elementor single-post template
   (Theme Builder); the article body renders through the **Post Content**
   widget.
4. **Verify:** `page snapshot` (one call) + public front-end HTML inspection
   after every build; check mobile widths.
5. **Undo:** every write lands in the change ledger — use the
   changes/history + rollback tools instead of hand-patching.

## Safety

- Every tool runs a WordPress capability check as the authenticating user.
- Destructive ops need explicit `confirm: true`; admins can't be edited over
  MCP; no delete-user tool.
- Prefer rollback over manual fixes; take a snapshot before bulk edits.

## References

- Tool reference: https://emcptools.com/docs/tools/overview/
- Install/connect: https://emcptools.com/docs/getting-started/installation/
- Blueprint prompts (full-page designs): repo `prompts/`
  (`LOCAL_BUSINESS.md`, `DENTAL_CLINIC.md`, …)
- Alternative: official Elementor MCP (Elementor → Elementor MCP dashboard).
