# contentfte

[![npm version](https://img.shields.io/npm/v/content-fte.svg?logo=npm)](https://www.npmjs.com/package/content-fte)
[![License: CC BY-NC 4.0](https://img.shields.io/badge/License-CC%20BY--NC%204.0-orange.svg)](./LICENSE)

Published on npm as **`content-fte`** — https://www.npmjs.com/package/content-fte

One `npm install` gives you the ContentFTE engine SDK: a typed HTTP client
plus a React renderer that turns the unified `/content` delivery payload into
a fully SEO'd article page (title H1, GFM, FAQ section, Article + FAQPage
JSON-LD).

```bash
npm install content-fte
```

> Requires the ContentFTE engine (self-hosted, `uvicorn main:app`) or a
> hosted engine URL, plus a site key. Node 18+ (CJS `require` of the renderer
> needs Node 22+ or a bundler; ESM works everywhere).

## Three entry points

| Import | What you get |
|---|---|
| `content-fte` | `ContentFTEClient` — dependency-free `fetch`, built-in retry/backoff, idempotency keys |
| `content-fte/renderer` | `<ContentFTEArticle>` React component + `ContentFTEPayload` type |
| `content-fte/contentfte-prose.css` | Framework-agnostic typography for the payload |

### Client

```ts
import { ContentFTEClient } from "content-fte";

const client = new ContentFTEClient("https://engine.example.com", "site-key");

const art = await client.submitArticle("mysite", "best crm for agencies");
await client.approveArticle(art.id, true);
await client.publishArticle(art.id);
const payload = await client.getContent(art.id); // unified delivery payload
```

### Renderer (React / Next.js)

```tsx
import { ContentFTEClient } from "content-fte";
import { ContentFTEArticle, type ContentFTEPayload } from "content-fte/renderer";
import "content-fte/contentfte-prose.css";

const client = new ContentFTEClient(process.env.CONTENTFTE_URL!, process.env.CONTENTFTE_SITE_KEY!);

export default async function Page({ params }: { params: { id: string } }) {
  const payload: ContentFTEPayload = await client.getContent(Number(params.id));
  return <ContentFTEArticle content={payload} siteOrigin="https://mysite.com" />;
}
```

The component handles: `payload.title` as the `<h1>` (the pipeline never
emits an H1 in the body), GFM tables/strikethrough, `==highlight==` →
`<mark>`, external links in a new tab, heading ids for TOC anchors, a FAQ
section from `payload.schema.faq`, and escaped Article/FAQPage JSON-LD.
Sanitized with rehype-sanitize (LLM-authored content is untrusted HTML).
Server Components friendly — no hooks, no `"use client"`.

### No React? Use `payload.html`

```html
<link rel="stylesheet" href="/path/to/contentfte-prose.css" />
<article class="cfte-prose">
  <h1>{title}</h1>
  <div>{/* payload.html */}</div>
  <script type="application/ld+json">{/* payload.schema as JSON, `<` → \u003c */}</script>
</article>
```

Theming: override the `--cfte-*` custom properties (`--cfte-accent`,
`--cfte-font-body`, ...). Opt-in dark mode: add
`data-cfte-theme="auto"` to the wrapper.

## Payload shape

`client.getContent(id)` returns `{ title, slug, url, excerpt, html,
markdown, markdown_alternate, schema: { article, faq } }` — one contract for
React, Astro, plain HTML, and static generators (`markdown_alternate`
includes `---` front-matter).

Full walkthrough (Next.js server routes, key-location guidance, Astro
endpoint + render, status flow, MCP): see [`quickstart.md`](./quickstart.md)
shipped in this package.

## License

CC BY-NC 4.0 — non-commercial use. See [LICENSE](./LICENSE).
