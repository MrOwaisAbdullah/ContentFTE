# Per-stack integration snippets

All snippets assume env `CONTENTFTE_URL` and `CONTENTFTE_SITE_KEY` (server-side).

## Next.js / React (full SDK path)

`app/blog/[slug]/page.tsx` (App Router, server component):
```tsx
import { ContentFTEClient } from "@owais-abdullah/contentfte";
import { ContentFTEArticle, type ContentFTEPayload } from "@owais-abdullah/contentfte/renderer";
import "@owais-abdullah/contentfte/contentfte-prose.css";

const client = new ContentFTEClient(process.env.CONTENTFTE_URL!, process.env.CONTENTFTE_SITE_KEY!);

export default async function Post({ params }: { params: { slug: string } }) {
  // resolve the article id however you store it (DB, route param, listArticles)
  const id = Number(params.slug);
  const payload = await client.getContent(id) as ContentFTEPayload;
  return <ContentFTEArticle content={payload} siteOrigin={process.env.SITE_ORIGIN} />;
}
```
The renderer emits the `<h1>`, GFM body, FAQ section, and the Article + FAQPage
JSON-LD (sanitized). Keep the client in server code (route handler / RSC).

## Astro (no React — pull + render)

Server-rendered page `src/pages/blog/[slug].astro`:
```astro
---
const res = await fetch(`${import.meta.env.CONTENTFTE_URL}/sdk/v1/articles/${id}/content`,
  { headers: { "X-Site-Key": import.meta.env.CONTENTFTE_SITE_KEY } });
const p = await res.json();
import { marked } from "marked";             // or use p.html directly
const body = marked.parse(p.markdown);
---
<html><body>
  <article class="prose">
    <h1>{p.title}</h1>
    <p class="dek">{p.excerpt}</p>
    <div set:html={body} />
  </article>
  <script type="application/ld+json" set:html={JSON.stringify(p.schema.article)} />
  {p.schema.faq && <script type="application/ld+json" set:html={JSON.stringify(p.schema.faq)} />}
</body></html>
```
Astro options: `p.html` (engine-rendered, zero deps) · `p.markdown` via `marked`
· a **content loader** with `renderMarkdown()` for Astro's own remark/rehype
pipeline (build-time; needs the article ids). No framework island needed.

## Vue 3 / Nuxt

```vue
<script setup lang="ts">
import { marked } from "marked";
const p = await $fetch(`${import.meta.env.CONTENTFTE_URL}/sdk/v1/articles/${id}/content`,
  { headers: { "X-Site-Key": import.meta.env.CONTENTFTE_SITE_KEY } });
const body = marked.parse(p.markdown);        // or p.html
useHead({ script: [{ type: "application/ld+json", innerHTML: JSON.stringify(p.schema.article) }] });
</script>
<template>
  <article class="cfte-prose"><h1>{{ p.title }}</h1><div v-html="body" /></article>
</template>
```

## Svelte / SvelteKit

```svelte
<script lang="ts">
  import Markdown from "svelte-exmarkdown";
  export let data;                            // supplied by +page.server.ts load()
</script>
<article class="cfte-prose">
  <h1>{data.p.title}</h1>
  <Markdown md={data.p.markdown} />
</article>
<svelte:head><script type="application/ld+json">{@html JSON.stringify(data.p.schema.article)}</script></svelte:head>
```
`+page.server.ts`: `const p = await client.getContent(id)` (fetch server-side).

## Plain HTML / Node

```js
const p = await (await fetch(`${process.env.CONTENTFTE_URL}/sdk/v1/articles/${id}/content`,
  { headers: { "X-Site-Key": process.env.CONTENTFTE_SITE_KEY } })).json();
// server-render: <article class="cfte-prose"><h1>${p.title}</h1>${p.html}</article>
// + <link rel="stylesheet" href="/path/to/contentfte-prose.css">
// + <script type="application/ld+json">${JSON.stringify(p.schema.article)}</script>
```

## WordPress (push — nothing to install)

Register the site with `site_type="wordpress"` (+ `WP_BASE_URL/WP_USERNAME/
WP_APP_PASSWORD` on the engine). On publish the engine pushes the post (Gutenberg
body, FAQ accordion, Yoast/RankMath/AIOSEO meta, JSON-LD, categories, images).
Read it back with `GET /sdk/v1/wp/posts/{id}`; update in place with
`POST /sdk/v1/articles/{id}/refresh`. No site-side SDK.

## AI agent (MCP)

Point the agent's MCP client at the engine's `/mcp` endpoint (Streamable HTTP,
`X-Site-Key`). Tools: `contentfte_list_sites`, `contentfte_get_brief`,
`contentfte_generate_article`, `contentfte_get_article_status`,
`contentfte_list_articles`, `contentfte_publish_article`,
`contentfte_refresh_article`, `contentfte_wp_post`, `contentfte_llms_txt`,
`contentfte_site_health`, `contentfte_elementor_*`.

Typical agent flow: `list_sites → get_brief → generate_article →
get_article_status → (approve) → publish_article`.
