# ContentFTE SDK — frontend quickstart (React / Next.js / Astro)

The SDK's primary consumers are browser apps. The TypeScript client
(`sdk/contentfte.ts`) is dependency-free — plain `fetch`, works in browsers,
Node 18+, Next.js, Astro, and Vite.

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

Copy `sdk/contentfte.ts` into your project (e.g. `lib/contentfte.ts`).

## 2. Where to keep the key

| Pattern | Key location | Use when |
|---|---|---|
| **Server route (recommended)** | Your backend (Route Handler / server util) | Production — key never ships to the browser |
| Direct from browser | `X-Site-Key` in the bundle | Local dogfooding / public read-only sites |

### Next.js — server route (app router)

```ts
// app/api/contentfte/route.ts
import { ContentFTEClient } from "@/lib/contentfte";

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
import { ContentFTEClient } from "./lib/contentfte";

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
import { ContentFTEClient } from "../../lib/contentfte";

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
const got   = await client.getArticle(art.id);                // status polling
const ok    = await client.approveArticle(art.id, true);      // gate passed?
await client.publishArticle(art.id);                          // approved only; 409 otherwise
const html  = await client.getContent(art.id);                // HTML + meta + images
```

- **Events** returned in every mutating response: `article.ready`,
  `article.needs_review`, `article.published` — forward them to your CMS/webhook.
- **Idempotency**: pass an `idempotencyKey` on submit; retries (built in:
  3× exponential backoff on network/429/5xx) never duplicate an article.
- **Publish gate**: `approveArticle` only flips status — `publishArticle`
  refuses (HTTP 409) until approved (90/100 overall, every sub-score ≥ 80).

## 4. Status flow

```
briefed → (engine generates) → needs_review | approved → published
                                ↑ approve false     ↑ publishArticle
```

Poll `getArticle(id)` until `status !== "briefed"`, then approve (or request
review) and publish. AI assistants can drive the same flow over MCP at `/mcp`
(`contentfte_generate_article`, `contentfte_get_article_status`, ...).
