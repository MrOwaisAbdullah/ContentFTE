---
name: contentfte
description: |
  Integrate the ContentFTE content engine into a website or app. Covers
  installing the `@owais-abdullah/contentfte` SDK (or calling the REST/MCP API),
  configuring credentials, pulling the unified `/content` payload, and rendering
  SEO/AEO/GEO-ready articles correctly for the user's stack — Next.js/React,
  Astro, Vue/Nuxt, Svelte/SvelteKit, plain HTML/Node, WordPress, or an AI agent
  driving the engine over MCP. This skill should be used when users ask to add
  ContentFTE to a project, install the contentfte SDK, render ContentFTE
  articles, wire up ContentFTE publishing, or connect an AI agent to ContentFTE.
---

# ContentFTE integration

ContentFTE is a content engine: it researches, writes, gates, and publishes
SEO/AEO/GEO articles. Consumers (your website or app) don't call an LLM — they
**pull a rendered payload** and display it, or drive the engine over the API/MCP.

The engine owns the *content*; your site owns the *layout*.

## What the SDK gives you

The npm package `@owais-abdullah/contentfte` has three entry points:

| Import | What it is |
| :--- | :--- |
| `@owais-abdullah/contentfte` | `ContentFTEClient` — typed client (fetch, retry/backoff, idempotency keys) |
| `@owais-abdullah/contentfte/renderer` | `<ContentFTEArticle>` React component + `ContentFTEPayload` type |
| `@owais-abdullah/contentfte/contentfte-prose.css` | Framework-agnostic typography (wrapper class `cfte-prose`) |

The engine returns a **unified payload** at `GET /sdk/v1/articles/{id}/content`:
`title, slug, url, excerpt, html, markdown, markdown_alternate, schema{article, faq}, meta`.
`html` is pre-rendered by the engine; `markdown` is the source; `markdown_alternate`
is the agent-ready `.md`; `schema` is Article + FAQPage JSON-LD.

> Full endpoint + MCP tool list: `references/api.md`.
> Per-stack code: `references/stacks.md`.

## Before Implementation

Gather context before writing code — do not guess the stack:

| Source | Gather |
| :--- | :--- |
| **Codebase** | Framework + router (Next App/Pages, Astro, Nuxt, SvelteKit…), styling system, how pages/routes are defined, existing data-fetching patterns, whether React is present |
| **Conversation** | Production vs local engine URL, whether it's a **WordPress** site or a **custom** site, draft vs published content, which assets they want (renderer? CSS? `.md`? `llms.txt`?) |
| **references/** | `stacks.md` (snippets), `api.md` (surface) |
| **Docs in repo** | `sdk/quickstart.md`, `docs/site-onboarding-flow.md` (full flows), `docs/local-business-factory-integration.md` (LBF example) |

Only ask the user for THEIR specifics (engine URL, site key, stack). The domain
knowledge is in this skill.

## The integration in 6 steps

### 0. Detect the target
- **WordPress site?** → the engine **pushes** on publish; nothing to install.
  Verify with `GET /sdk/v1/wp/posts/{id}`. (See `references/stacks.md#wordpress`.)
- **Custom site (Astro/Next/Vue/Svelte/HTML)?** → your site **pulls** the payload.
  Continue below.
- **AI agent (Claude Code, etc.)?** → connect over MCP instead of writing a
  client. (See `references/stacks.md#ai-agent-mcp`.)

### 1. Install
```bash
npm install @owais-abdullah/contentfte        # React/Next/Bundlers
```
No npm? Call REST directly (`GET /sdk/v1/articles/{id}/content`) — see `references/api.md`.

### 2. Configure (server-side)
```bash
CONTENTFTE_URL=https://engine.example.com     # engine base, no trailing slash
CONTENTFTE_SITE_KEY=<SDK_MASTER_KEY>          # sent as the X-Site-Key header
```
Keep the site key **server-side** (Next route handler / Astro endpoint / SSR),
never in client bundles.

### 3. Fetch content
```ts
import { ContentFTEClient } from "@owais-abdullah/contentfte";
const client = new ContentFTEClient(process.env.CONTENTFTE_URL!, process.env.CONTENTFTE_SITE_KEY!);
const payload = await client.getContent(12);          // one article
const list = await client.listArticles("my-site", "published"); // enumerate
```

### 4. Render — pick by stack (details in `references/stacks.md`)
| Stack | Render with |
| :--- | :--- |
| **Next.js / React** | `<ContentFTEArticle content={payload} siteOrigin="https://…" />` + `contentfte-prose.css` |
| **Astro** | `payload.html` (engine-rendered) or `payload.markdown` via Astro's own pipeline / `marked` — **no React needed** |
| **Vue / Nuxt** | `marked`/`markdown-it` + `v-html` (or `payload.html`) |
| **Svelte / SvelteKit** | `svelte-exmarkdown` or `payload.html` |
| **Plain HTML / Node** | `payload.html` |

The React renderer handles GFM, `==highlight==`, heading anchors, external-link
`target`, a FAQ **accordion** (`<details>`, from `schema.faq`), and emits the
JSON-LD — sanitized. Other stacks use the engine's `html` + `faq_html`, or run
`markdown` through their own renderer.

### 5. Ship the SEO/AEO/GEO assets
- **JSON-LD:** inject `payload.schema.article` and `payload.schema.faq` as
  `<script type="application/ld+json">` (the React renderer does it for you).
- **`.md` alternate (per article):** serve `payload.markdown_alternate` at
  `/blog/{slug}.md`.
- **`FAQ`:** the renderer (`<ContentFTEFaq>` / `<ContentFTEArticle>`) emits a
  native `<details>` **accordion**; non-React sites render `payload.faq_html`
  (same `<details>` markup as the WordPress/Elementor output).
- **`llms.txt` (site-level):** `GET /sdk/v1/sites/{slug}/llms.txt` returns
  `{site, count, llms_txt}` — serve the **`llms_txt` string** at `/llms.txt`
  (do **not** serve the raw JSON). In the client: `const { llms_txt } = await client.llmsTxt(slug)`, then `return new Response(llms_txt, { headers: { "content-type": "text/plain" } })`.
- **Styles:** import `@owais-abdullah/contentfte/contentfte-prose.css` (wrap the
  article in `cfte-prose`).

### 6. Verify
- [ ] The page renders the title as an `<h1>` and the body with correct headings.
- [ ] Article + FAQPage JSON-LD present (view source / Rich Results test).
- [ ] `/blog/{slug}.md` returns the markdown alternate; `/llms.txt` lists posts.
- [ ] No site key in client-side bundles.
- [ ] Publish flow works end-to-end (see `references/api.md#lifecycle`).

## Common pitfalls

- **Using the React renderer in a non-React site** — it pulls React in. Astro/Vue/
  Svelte should use `payload.html` (+ `payload.faq_html`) or their own markdown
  renderer + the CSS.
- **Serving `llmsTxt()` raw** — it returns `{site, count, llms_txt}` JSON; serve
  the `llms_txt` string.
- **`slug` → id** — `getContent()` needs the numeric article id. Map a URL slug to
  an id with `listArticles(site, "published")` (returns `slug` per row), or store
  the id at publish time.
- **Next 15/16 `params` are Promises** — `await params` in pages and `await
  context.params` in route handlers; the old sync form fails.
- **`/blog/[slug].md` route** — App Router can't nest a literal `.md` folder; add
  a `rewrite` (or a `/blog/[slug]/md` route) — see `references/stacks.md`.
- **Tailwind scaffold preflight** — a fresh `create-next-app` ships Tailwind; its
  preflight can fight `contentfte-prose.css`. Scope prose styles to `cfte-prose`
  or drop the scaffold CSS.
- **Astro content collections for remote content** — collections are build-time;
  a server-rendered site should fetch the payload at request time (or via a
  content **loader** with `renderMarkdown()`). See `references/stacks.md#astro`.
- **Client-side site key** — exposes your engine. Fetch server-side.
- **Assuming push for custom sites** — only `site_type="wordpress"` pushes; custom
  sites pull. Register the site with the correct `site_type`.
- **Ignoring the payload `markdown_alternate`** — it's free GEO/LLM value; serve it.
- **`content.rendered` vs raw** — for Gutenberg block checks read `content.raw`.

## Scope

**Does:** install/configure the SDK, choose the right rendering path per stack,
wire JSON-LD / `.md` / `llms.txt` / CSS, connect an agent over MCP, verify.

**Does not:** build the ContentFTE engine (it's a separate service), write
generation prompts, or manage the engine's database.

## Reference files
| File | When to read |
| :--- | :--- |
| `references/stacks.md` | Full code per stack (Next, Astro, Vue, Svelte, HTML, WordPress, MCP) |
| `references/api.md` | REST routes, MCP tools, payload shape, lifecycle, auth |
