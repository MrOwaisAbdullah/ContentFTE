# Site onboarding & publishing flow — WordPress · custom React/Astro

How a brand-new site goes from "not known to the engine" to "article live on
the site", for the two delivery targets this repo supports:

- **WordPress** — the engine pushes the finished post straight into WP over the
  REST API (`site_type="wordpress"`).
- **Custom site (React / Next / Astro / plain HTML)** — the engine owns the
  content, your site owns the layout; you **pull** the rendered payload
  (`site_type="custom"`), optionally with a webhook push.

Both targets share the same engine, the same article lifecycle, and the same
**gated** publish rule (an article must be approved before it can go live).
The code lives in `sdk/service.py` (canonical ops) → `sdk/server.py`
(REST `/sdk/v1`) → `mcp_server/server.py` (MCP `contentfte_*`).

---

## 0. Concepts you need first

| Thing | What it means |
| :--- | :--- |
| **Site** | A row keyed by `slug` with `site_type` = `custom` \| `wordpress`, an optional `base_url`, and `publish_mode`. Create it once. |
| **Article lifecycle** | `briefed` → `drafted` → `approved` → `published`; a rejected review sets `needs_review`. `publish_article` only accepts `approved` (or `published`). |
| **Interfaces** | Everything below is available three ways, same behavior: **REST** (`/sdk/v1/*`), **MCP** (`contentfte_*` tools), and the **clients** (`sdk/python_client.py`, npm `content-fte`). |
| **Auth** | REST/MCP: `X-Site-Key` header == `SDK_MASTER_KEY` (dev-open when unset). |
| **Audit + cost** | Every mutating op writes an `AuditLog` row; publish finalizes the per-article cost into `Article.cost_usd`. |
| **Fail-open** | A WordPress/Elementor/webhook failure never loses the article or rolls back status — the outcome rides in the response (`wp.ok=false`, …) and a re-run retries. |

**One rule:** nothing publishes unless it is `approved`. Approve is your gate —
review `scores` first (house policy: overall ≥ 90 and every sub-score ≥ 80).

### Where the site type lives (wordpress vs custom)

There is **no `astro` / `nextjs` / `react` value** — the engine only knows two
targets, set on the `Site` row at creation:

| Value | Meaning |
| :--- | :--- |
| `wordpress` | `publish` pushes the post into WordPress (§1) |
| `custom` | the engine owns the content; your site pulls the payload (§2). **Astro, Next, React, plain HTML — all `custom`.** |

Where to set it:

| Where | How |
| :--- | :--- |
| **REST** | `POST /sdk/v1/sites` → `{"slug","name","site_type":"wordpress"\|"custom","base_url":"…"}` (`sdk/server.py` `SiteUpsert`) |
| **Python** | `service.upsert_site("acme", site_type="wordpress", base_url="https://…")` (`sdk/service.py:87`) |
| **Factory / brand provisioning** | taken from the business profile — `site_type or "wordpress"` (`lib/factory.py:108`) |
| **DB column** | `Site.site_type` (default `"custom"`), `Site.base_url`, `Site.publish_mode` (`lib/db.py:49-57`) |
| **MCP** | none — there is no `upsert_site` tool; use REST / Python |

⚠️ Two gotchas:
- `submit_article` **auto-creates** an unknown site with the default
  `site_type="custom"` — create the WordPress site **first**, or publish
  silently skips the WP push.
- `upsert_site` sets `site_type` only on **create**; it will **not** change an
  existing site's type (edit the row to switch).

WordPress sub-option (not `site_type`): `WP_RENDER_TARGET=blocks|elementor`.
The framework choice for a `custom` site is made on your side (§2.4).

---

## 1. WordPress flow (push target)

### 1.1 Prerequisites (once per site)

1. In the WP admin: **Users → Profile → Application Passwords** → mint one for
   an Administrator. (Elementor meta writes and JSON-LD need an admin token.)
2. Export env for the engine process:
   ```bash
   WP_BASE_URL=https://your-site.com     # no trailing slash
   WP_USERNAME=admin
   WP_APP_PASSWORD="xxxx xxxx xxxx xxxx xxxx xxxx"
   ```
3. Recommended: install **Yoast SEO** (or Rank Math / AIOSEO) so the meta
   title/description actually persist (WP drops unregistered meta keys). The
   connector sends all three plugins' keys unconditionally.
4. Optional: **Elementor ≥ 3.27** if you want native Elementor layouts (§1.7).

### 1.2 Register the site

```bash
curl -X POST localhost:8000/sdk/v1/sites \
  -H "X-Site-Key: $SDK_MASTER_KEY" -H "Content-Type: application/json" \
  -d '{"slug":"acme","name":"Acme","site_type":"wordpress","base_url":"https://your-site.com"}'
```
> MCP note: there is no `contentfte_upsert_site` tool — create/update sites via
> REST (or `service.upsert_site`). Agents then use `contentfte_list_sites`.

### 1.3 Submit the article (brief + keyword)

```bash
curl -X POST localhost:8000/sdk/v1/articles \
  -H "X-Site-Key: $SDK_MASTER_KEY" -H "Content-Type: application/json" \
  -d '{
        "site_slug": "acme",
        "keyword": "best crm for agencies",
        "brief": {
          "title": "Best CRM for Agencies",
          "description": "Meta description…",
          "categories": ["SEO"],
          "tags": ["crm"],
          "faqs": [{"question":"…","answer":"…"}],
          "cta": {"label":"Read the docs","url":"https://…"}
        }
      }'
```
→ `{"id": 12, "status": "briefed", "event": "article.ready"}`.
Idempotent per `(site, keyword)` — a repeat submit returns the existing row
(`deduplicated: true`). The keyword is bound to a ledger row (§5.16 lineage).

### 1.4 Generate

```bash
curl -X POST localhost:8000/sdk/v1/articles/12/generate \
  -H "X-Site-Key: $SDK_MASTER_KEY" -H "Content-Type: application/json" \
  -d '{"regenerate": false}'
```
→ `article.drafted`; the article now carries `content_md`, `title`, `summary`,
`faqs`, and `scores`. This runs the real content-generator agent (LLM).
`regenerate: true` rewrites an already-drafted/published article.

### 1.5 Stage images (optional, recommended)

The WP push reads `meta.images` — a list of slots:
```json
"images": [
  {"slot": "featured", "path": "/abs/hero.jpg", "alt": "…"},
  {"slot": "inpost",   "path": "/abs/in.jpg",  "alt": "…", "after_h2": 1}
]
```
(`path` for a local file; a remote `url`/`image_url` also works for the
featured slot — it is downloaded to a temp file, uploaded, then cleaned up.)

### 1.6 Approve → Publish (WP push happens *inside* publish)

```bash
curl -X POST localhost:8000/sdk/v1/articles/12/approve \
  -H "X-Site-Key: $SDK_MASTER_KEY" -H "Content-Type: application/json" \
  -d '{"approved": true}'

curl -X POST localhost:8000/sdk/v1/articles/12/publish \
  -H "X-Site-Key: $SDK_MASTER_KEY" -H "Content-Type: application/json" \
  -d '{"mode": "draft"}'          # "publish" to go live immediately
```
Response:
```json
{"id":12,"status":"published","mode":"draft","cost_usd":0.07,
 "wp":{"ok":true,"post_id":97,"url":"https://your-site.com/?p=97",
       "status":"draft","slug":"best-crm-for-agencies",
       "categories":["SEO"],"render_target":"blocks","featured_media":95}}
```
**What lands in WordPress, in that one call:**
- the body as **Gutenberg blocks** (headings, lists, tables, code, blockquote,
  paragraph) — opens as real editable blocks, no "Convert to Blocks";
- **FAQ as a native accordion** (`core/details` blocks, shared
  `name="contentfte-faq"`);
- meta title/description for **Yoast / Rank Math / AIOSEO**;
- **Article + FAQPage JSON-LD** in the body;
- categories + tags (from the brief, else the site's default category);
- **featured image** (thumbnail) + **in-post image** placed after the nth H2.

**Idempotency / safety:** the WP post id is stored as `meta.wp_post_id`; a
re-publish returns `{"deduplicated": true}` and does **not** create a second
post. If WP is down, `wp.ok=false` with the reason — the article is still
`published` in the engine and re-running publish retries the push.

> Local/dev sites: an outbound link check runs before push. Set
> `WP_LINK_CHECK=0` to bypass it when AI-written links point at slugs that
> don't exist yet on a fresh local site.

### 1.7 Elementor variant (optional)

If the site designs blog pages in Elementor, write a native document instead of
a Gutenberg body:
```bash
# preflight
curl localhost:8000/sdk/v1/elementor/available -H "X-Site-Key: $SDK_MASTER_KEY"
# compose the article as an Elementor document (creates or reuses the post)
curl -X POST localhost:8000/sdk/v1/elementor/articles/12/build \
  -H "X-Site-Key: $SDK_MASTER_KEY" -H "Content-Type: application/json" \
  -d '{"mode":"draft"}'
```
The document is `container > heading (H1) + html widget + native Accordion
widget` for the FAQs. Equivalently, set `WP_RENDER_TARGET=elementor` and use the
normal publish path. Failure is fail-open (`elementor.ok=false`), and the post
content remains valid standard HTML.

### 1.8 Verify / accept

```bash
python scripts/acceptance_wp.py --mode draft       # full chain + checklist
```
Full criteria: `docs/phase1-live-run-checklist.md` §6 (blocks, JSON-LD, FAQ
accordion, featured/in-post image, category, SEO meta, excerpt) and §7
(Elementor). Latest live result and attempt log: `docs/dev-log.md`.

---

## 2. Custom site flow — React / Next / Astro / plain HTML (pull target)

The engine produces a **site-agnostic delivery payload**; your site renders it
with its own layout. Nothing is pushed into your codebase — you pull.

### 2.1 Register the site

```bash
curl -X POST localhost:8000/sdk/v1/sites \
  -H "X-Site-Key: $SDK_MASTER_KEY" -H "Content-Type: application/json" \
  -d '{"slug":"acme-blog","name":"Acme Blog","site_type":"custom","base_url":"https://blog.acme.com"}'
```
`base_url` is optional but makes the payload's `url`/canonical absolute.

### 2.2 Submit → generate → approve

Identical to the WordPress flow (§1.3–§1.6). For a custom site **`publish`**
just marks the article `published` in the engine (there is no built-in push) —
the site then pulls the content.

### 2.3 Pull the unified `/content` payload

```bash
curl localhost:8000/sdk/v1/articles/12/content -H "X-Site-Key: $SDK_MASTER_KEY"
```
```jsonc
{
  "id": 12, "title": "Best CRM for Agencies", "slug": "best-crm-for-agencies",
  "url": "https://blog.acme.com/best-crm-for-agencies",
  "excerpt": "Meta description…",
  "status": "published", "scores": {…}, "cost_usd": 0.07,

  "html": "<h2>…</h2><p>…</p>…",                 // rendered body (no block comments)
  "markdown": "## …",                              // the source
  "markdown_alternate": "…",                       // llms.txt / alternate Markdown

  "schema": {
    "article": { "@type": "Article", … },          // JSON-LD
    "faq":     { "@type": "FAQPage", … } | null
  },
  "meta": { "brief": {…}, "faqs": [ { "question": "…", "answer": "…" } ] }
}
```

**Site-level indexes:** `GET /sdk/v1/sites/{slug}/llms.txt` composes the site's
`llms.txt` (§5.8 GEO) from its published articles — the companion to the
per-article `markdown_alternate` (`.md`). The site serves both at its own URLs
(`/llms.txt`, `/blog/{slug}.md`).

### 2.4 Render it

**Astro** — render the source `markdown` (or use the pre-rendered `html`; see
the field note below). Astro's content collections work on *local* files, so for
a fetched string compile it with a Markdown library:

```astro
---
import { marked } from "marked";                 // npm i marked
const res = await fetch(`${ENGINE}/sdk/v1/articles/12/content`,
                        { headers: { "X-Site-Key": KEY } });
const p   = await res.json();
const body = marked.parse(p.markdown);           // or: use p.html directly
---
<article>
  <h1>{p.title}</h1>
  <p class="dek">{p.excerpt}</p>
  <div class="prose" set:html={body} />
</article>
<script type="application/ld+json" set:html={JSON.stringify(p.schema.article)} />
{p.schema.faq && <script type="application/ld+json" set:html={JSON.stringify(p.schema.faq)} />}
```

If you'd rather skip the Markdown dependency, swap `body` for `p.html`:

```astro
<div class="prose" set:html={p.html} />
```

#### Astro's native pipeline (best for a content-driven site)

`marked` does **not** use Astro's markdown config. To render with the *same*
remark/rehype pipeline as your `.md` files (GFM, syntax highlighting, your
plugins) — the true Astro equivalent of `react-markdown` — use a **content
loader** and its `renderMarkdown()`:

```ts
// src/content.config.ts
import { defineCollection, z } from "astro:content";

const API = import.meta.env.CONTENTFTE_URL;   // engine base URL
const HDRS = { "X-Site-Key": import.meta.env.CONTENTFTE_SITE_KEY };

const blog = defineCollection({
  loader: {
    name: "contentfte",
    async load({ store, renderMarkdown }) {
      // 1. enumerate the site's published articles (newest first)
      const list = await (await fetch(
        `${API}/sdk/v1/articles?site_slug=acme&status=published&limit=100`,
        { headers: HDRS })).json();
      // 2. pull each article's rendered payload
      for (const { id } of list.articles) {
        const p = await (await fetch(`${API}/sdk/v1/articles/${id}/content`,
                                     { headers: HDRS })).json();
        store.set({
          id: p.slug,
          data: { title: p.title, description: p.excerpt, articleId: p.id, url: p.url },
          rendered: await renderMarkdown(p.markdown),   // Astro's own pipeline
        });
      }
    },
  },
  schema: z.object({ title: z.string(), description: z.string().optional(),
                     articleId: z.number(), url: z.string().optional() }),
});

export const collections = { blog };
```

```astro
---
import { getCollection, render } from "astro:content";
const posts = await getCollection("blog");
---
{posts.map(async (post) => {
  const { Content } = await render(post);
  return <article><h1>{post.data.title}</h1><Content /></article>;
})}
```

> `GET /sdk/v1/articles` enumerates a site's articles (`site_slug`, `status`,
> `limit`, `offset`) → feed the ids into `/articles/{id}/content`. The same is
> available as the MCP tool `contentfte_list_articles` and in both SDK clients
> (`list_articles` / `listArticles`). Collections give you typed data,
> `<Content />`, and Astro's image handling for free.

#### Other frameworks inside Astro

An Astro site can host React/Vue/Svelte islands (or be built from one framework
via an integration). If the site **already** ships a framework, use that
framework's markdown component; otherwise prefer Astro's own pipeline above
(zero client JS):

| Integration | Markdown renderer |
| :--- | :--- |
| `@astrojs/react` | `react-markdown` — the same renderer a React site uses (or the published `<ContentFTEArticle>`) |
| `@astrojs/vue` | `marked` / `markdown-it` + `v-html`, or `@nuxtjs/markdownit` |
| `@astrojs/svelte` | `svelte-exmarkdown` (`<Markdown>` component) |
| `@astrojs/mdx` | `.mdx` **files** (compile-time) — not runtime strings |

You don't need to add a framework island *just* to render markdown — `marked`
or a content loader covers it with zero JS shipped.

#### `html` vs `markdown` vs `markdown_alternate`

The payload deliberately ships all three:

| Field | What it is | Use it when |
| :--- | :--- | :--- |
| `html` | the body compiled **once by the engine** (`lib/wp_render`) — identical for every consumer | you want zero markdown dependency, or byte-identical output across platforms |
| `markdown` | the source the engine generated | you want **your own** markdown pipeline / components (Astro `marked`, Next `react-markdown`, MDX) |
| `markdown_alternate` | frontmatter + `# title` + body — the agent-ready `.md` | you serve a `/slug.md` alternate for LLMs (GEO §5.8) — **not** the visible page |

So Astro is **not** forced to HTML: use `p.markdown` to render it yourself, or
`p.html` for the engine's exact rendering. The React renderer in
`content-fte` is the markdown path — it compiles `payload.markdown`
via `react-markdown` (and falls back to `payload.html` when markdown is empty),
which is why React/Next below looks "markdown-first".

**React / Next** — install the published renderer once:
```bash
npm install content-fte
```
```tsx
import { ContentFTEClient } from "content-fte";
import { ContentFTEArticle } from "content-fte/renderer";
import "content-fte/contentfte-prose.css";

const client = new ContentFTEClient(process.env.CONTENTFTE_URL!, process.env.CONTENTFTE_SITE_KEY!);
const payload = await client.getContent(12);

export default function Post() {
  return <ContentFTEArticle content={payload} siteOrigin="https://blog.acme.com" />;
}
```
`<ContentFTEArticle>` renders the title as `<h1>`, GFM (incl. `==highlight==` →
`<mark>`), heading anchors for a TOC, external links `target="_blank"`, a FAQ
section, and emits the Article + FAQPage JSON-LD — sanitized via
`rehype-sanitize`. See `sdk/quickstart.md` for Next route-handler and Astro
patterns.

### 2.5 Optional webhook push (build hook)

Instead of polling, the engine can POST the same payload to your site's build
hook / API route:
```python
from lib import custom_site
custom_site.deliver(payload, webhook_url=os.environ["SITE_PUBLISH_WEBHOOK"])
# -> {"status":"ok","status_code":200}  |  {"status":"error","message":…}
```
> Status: `lib/custom_site.deliver` is implemented and unit-tested
> (`tests/test_custom_site.py`) but is **not yet wired to a service op / REST
> route / MCP tool** — call it from your own job/script. Set
> `SITE_PUBLISH_WEBHOOK` in env. The **pull** path above is the wired one.

### 2.6 Revalidation notes

- **Astro (SSG/ISR):** point `SITE_PUBLISH_WEBHOOK` at your deploy/build hook.
- **Next (ISR):** in your webhook route call `res.revalidate('/blog/[slug]')`
  after storing the payload.

---

## 3. Interface cheat-sheet

| Step | REST (`/sdk/v1`) | MCP tool | Service op |
| :--- | :--- | :--- | :--- |
| Create/update site | `POST /sites` | — | `upsert_site` |
| List sites | `GET /sites` | `contentfte_list_sites` | `list_sites` |
| Next brief from ledger | — | `contentfte_get_brief` | `get_brief` |
| Submit article | `POST /articles` | `contentfte_generate_article`¹ | `submit_article` |
| Generate content | `POST /articles/{id}/generate` | `contentfte_generate_article`¹ | `generate_content` |
| Status / scores | `GET /articles/{id}` | `contentfte_get_article_status` | `get_article` |
| Images | — | `contentfte_get_image` | `get_images` |
| Approve | `POST /articles/{id}/approve` | — (call REST) | `approve_article` |
| Publish (WP push inside) | `POST /articles/{id}/publish` | `contentfte_publish_article` | `publish_article` |
| Delivery payload | `GET /articles/{id}/content` | — (client pulls) | `get_article(include_content=True)` |
| Site health | `GET /sites/{slug}/health` | `contentfte_site_health` | `site_health` |
| Elementor probe/read/save/build | `GET /elementor/…` | `contentfte_elementor_*` | `elementor_*` |

¹ MCP `contentfte_generate_article` does **submit + generate** in one tool call.

---

## 4. Environment variables that matter here

| Var | Used by |
| :--- | :--- |
| `WP_BASE_URL`, `WP_USERNAME`, `WP_APP_PASSWORD` | WordPress + Elementor pushes |
| `WP_RENDER_TARGET` | `blocks` (default) \| `elementor` |
| `WP_LINK_CHECK` | `0`/`off` bypasses the outbound-link guard (local sites) |
| `SDK_MASTER_KEY` | `X-Site-Key` auth for REST/MCP (unset = dev-open) |
| `SITE_PUBLISH_WEBHOOK` | custom-site webhook push (`lib.custom_site.deliver`) |
| `DATABASE_URL` | engine store (SQLite default; Postgres for cutover) |
| `GEMINI_API_KEY` / `OPENROUTER_API_KEY` / `OPENAI_API_KEY` | generation |

---

## 5. Minimal end-to-end (either target)

```
POST /sdk/v1/sites            → site exists (site_type = wordpress | custom)
POST /sdk/v1/articles         → briefed            (idempotent per site+keyword)
POST /sdk/v1/articles/{id}/generate → drafted      (content_md, scores, faqs)
   … review scores (policy: overall ≥ 90, subs ≥ 80) …
POST /sdk/v1/articles/{id}/approve  → approved
POST /sdk/v1/articles/{id}/publish  → published
        ├─ wordpress → wp:{ok, post_id, url, …}   (post is live/draft in WP)
        └─ custom    → GET /articles/{id}/content → render in your site
```

**See also:** `docs/phase1-feature-map.md` (full surface map),
`sdk/quickstart.md` (frontend patterns), `docs/phase1-live-run-checklist.md`
(acceptance criteria), `docs/dev-log.md` (latest live runs).
