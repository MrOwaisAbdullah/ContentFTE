# ContentFTE SDK — frontend quickstart (React / Next.js / Astro / plain HTML)

One install gives you everything:

```bash
npm install contentfte
```

| Import | What it is |
|---|---|
| `contentfte` | Typed HTTP client — dependency-free `fetch`, works in browsers, Node 18+, Next.js, Astro, Vite |
| `contentfte/renderer` | `<ContentFTEArticle>` — React component that renders the delivery payload (title `<h1>`, markdown body, FAQ section, Article + FAQPage JSON-LD) |
| `contentfte/contentfte-prose.css` | Framework-agnostic typography for the payload (also usable without React) |

## 1. Get connected

```bash
# engine (from this repo)
uvicorn main:app --port 8000
```

- Base URL: `http://localhost:8000` (prod: your engine domain)
- Site key: `X-Site-Key` header. Dev-open when `SDK_MASTER_KEY` is unset;
  set it in production. Create sites via `POST /sdk/v1/sites` or MCP
  `contentfte_list_sites`.
- CORS is pre-configured for browsers (open by default; restrict with
  `SDK_CORS_ORIGINS=https://yoursite.com,http://localhost:3000`).

## 2. Where to keep the key

| Pattern | Key location | Use when |
|---|---|---|
| **Server route (recommended)** | Your backend (Route Handler / server util) | Production — key never ships to the browser |
| Direct from browser | `X-Site-Key` in the bundle | Local dogfooding / public read-only sites |

### Next.js — server route (app router)

```ts
// app/api/contentfte/route.ts
import { ContentFTEClient } from "contentfte";

const client = new ContentFTEClient(
  process.env.CONTENTFTE_URL!,    // e.g. https://engine.example.com
  process.env.CONTENTFTE_SITE_KEY!,
);

export async function POST(req: Request) {
  const { keyword } = await req.json();
  const art = await client.submitArticle("mysite", keyword, {},
                  req.headers.get("Idempotency-Key") ?? "");
  return Response.json(art);
}
```

```tsx
// client component
const res = await fetch("/api/contentfte", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ keyword: "best crm for agencies" }),
});
const { id } = await res.json();
```

### Direct from a client component / Vite

```tsx
import { ContentFTEClient } from "contentfte";

const client = new ContentFTEClient(
  import.meta.env.VITE_CONTENTFTE_URL,
  import.meta.env.VITE_CONTENTFTE_SITE_KEY,  // exposed — see table above
);

const art = await client.submitArticle("mysite", "best crm for agencies", {}, crypto.randomUUID());
```

### Astro — server endpoint

```ts
// src/pages/api/contentfte.ts (or .ts route handler)
import type { APIRoute } from "astro";
import { ContentFTEClient } from "contentfte";

const client = new ContentFTEClient(
  import.meta.env.PUBLIC_CONTENTFTE_URL,
  import.meta.env.CONTENTFTE_SITE_KEY,
);

export const POST: APIRoute = async ({ request }) => {
  const { keyword } = await request.json();
  return Response.json(await client.submitArticle("mysite", keyword));
};
```

## 3. The calls

```ts
// one-time setup (or auto-created on first submit)
await client.upsertSite("mysite", "My Site", "custom", "https://mysite.com");

const art   = await client.submitArticle("mysite", keyword);  // -> article.ready
const gen   = await client.generateContent(art.id);           // briefed -> drafted (LLM, 30-120s, idempotent)
const got   = await client.getArticle(art.id);                // status, scores, cost
const ok    = await client.approveArticle(art.id, true);      // gate passed?
await client.publishArticle(art.id);                          // approved only; 409 otherwise
const payload = await client.getContent(art.id);              // unified delivery payload
```

`getContent` returns the unified payload: `title`, `slug`, `url`, `excerpt`,
`html` (server-rendered body), `markdown`, `markdown_alternate` (front-matter
variant for static generators), and `schema` (`article` + `faq` JSON-LD).

- **Events** returned in every mutating response: `article.ready`,
  `article.drafted`, `article.needs_review`, `article.published` — forward
  them to your CMS/webhook.
- **Idempotency**: pass an `idempotencyKey` on submit; retries (built in:
  3× exponential backoff on network/429/5xx) never duplicate an article.
- **Publish gate**: `approveArticle` only flips status — `publishArticle`
  refuses (HTTP 409) until approved (90/100 overall, every sub-score ≥ 80).

## 4. Render the content

### React / Next.js — `<ContentFTEArticle>`

```tsx
import { ContentFTEClient } from "contentfte";
import { ContentFTEArticle, type ContentFTEPayload } from "contentfte/renderer";
import "contentfte/contentfte-prose.css";

const client = new ContentFTEClient(process.env.CONTENTFTE_URL!, process.env.CONTENTFTE_SITE_KEY!);

export default async function ArticlePage({ params }: { params: { id: string } }) {
  const payload: ContentFTEPayload = await client.getContent(Number(params.id));
  return <ContentFTEArticle content={payload} siteOrigin="https://mysite.com" />;
}
```

What it handles for you:

- `payload.title` renders as the `<h1>` — the pipeline never emits an H1 in the
  body (the title *is* the H1); the body opens with the TL;DR blockquote → H2s
- GFM tables/strikethrough, `==highlight==` → `<mark>`, external links open in
  a new tab (`rel="noopener noreferrer"`), tables get an overflow wrapper
- heading ids for TOC/scrollspy anchors (`#quick-comparison`)
- FAQ section from `payload.schema.faq` (`<section id="faqs">`)
- Article + FAQPage JSON-LD (with `<` escaped so it can never break out)
- `siteOrigin` keeps your own links in-tab; every other absolute link is
  marked external. Omit it to treat all absolute links as external.
- Server Components friendly (no hooks, no `"use client"`)

### Astro / any framework — `payload.html` + prose CSS

No React needed: the payload already ships server-rendered HTML.

```astro
---
import { ContentFTEClient } from "contentfte";
import "contentfte/contentfte-prose.css";

const client = new ContentFTEClient(
  import.meta.env.PUBLIC_CONTENTFTE_URL,
  import.meta.env.CONTENTFTE_SITE_KEY,
);
const payload = await client.getContent(Astro.params.id);
const jsonLd = (o: unknown) => JSON.stringify(o).replace(/</g, "\\u003c");
---
<article class="cfte-prose">
  <h1>{payload.title}</h1>
  <p class="cfte-dek">{payload.excerpt}</p>
  <div set:html={payload.html} />
  {payload.schema?.article && (
    <script type="application/ld+json" set:html={jsonLd(payload.schema.article)} />
  )}
  {payload.schema?.faq && (
    <script type="application/ld+json" set:html={jsonLd(payload.schema.faq)} />
  )}
</article>
```

### Plain HTML

```html
<link rel="stylesheet" href="/path/to/contentfte-prose.css" />
<article class="cfte-prose">
  <h1>Best CRM for Agencies</h1>
  <div><!-- paste payload.html here --></div>
  <script type="application/ld+json">/* payload.schema.article + .faq, `<` → \u003c */</script>
</article>
```

Statically generating? `markdown_alternate` is the body prefixed with
`---` front-matter and `# {title}` — drop it straight into a
Jekyll/Hugo/MDX file.

Theming: override the `--cfte-*` custom properties (`--cfte-accent`,
`--cfte-font-body`, `--cfte-text`, ...). For automatic dark mode add
`data-cfte-theme="auto"` to the wrapper.

## 5. Status flow

```
briefed → generateContent(id) → drafted → approved → publishArticle → published
                                     └→ approve false → needs_review
```

Call `generateContent(id)` after submit — the engine runs its LLM
(briefed → drafted, typically 30–120s; idempotent unless `regenerate=true`)
— then approve (or request review) and publish. AI assistants can drive the
same flow over MCP at `/mcp` (`contentfte_generate_article` submits and
generates in one call, `contentfte_get_article_status`, ...).
