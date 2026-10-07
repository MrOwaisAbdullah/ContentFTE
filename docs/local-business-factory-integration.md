# Integrating ContentFTE with the Octively Local Business Factory (LBF)

The **Local Business Factory** (`local-business-factory` — "Octively") is a
multi-tenant platform that generates ultra-fast, **zero-JS Astro** local
business sites from DB configs + templates. This note records how those sites
map onto ContentFTE and how articles would flow between the two.

## What was inspected

| Path | What it is |
| :--- | :--- |
| `apps/site-renderer` | **Astro 7.3.1**, `output: 'server'` + `@astrojs/node` (SSR, standalone). Multi-tenant by subdomain. Catch-all `src/pages/[...slug].astro`, `llms.txt.ts`, `sitemap.xml.ts`, `api/leads.ts`. |
| `apps/api`, `apps/factory` | Platform API + factory app (Node). |
| `packages/site-schema` | Zod schemas incl. **`BlogPostSchema` / `BlogBlockSchema` / `BlogConfigSchema`**. |
| `packages/templates` | 14 generative templates + custom themes; `renderTemplate()`. |
| `packages/db` | Drizzle ORM over **PostgreSQL** (`tenants`, `sites`, `siteVersions`, `siteConfigs`, `siteLeads`, …). |
| `docs/custom-astro-website-integration-guide.md` | Binding a standalone Astro project to a tenant (env + `/api/tenants/{slug}/content` + deploy webhook). |

Key facts: **Astro `output: 'server'`**, and the deps are only `@astrojs/node`,
`astro`, `drizzle-orm` — **no `@astrojs/react` / vue / svelte / mdx**. So there is
no React island and no build-time content collection in play.

## 1. Which ContentFTE `site_type`?

**`custom` — all of it.** ContentFTE has only `wordpress` | `custom`; every
Astro site (the built-in template renderer *and* any standalone custom Astro
project) is `custom`. ContentFTE `publish` will **not** push to them; delivery
is pull / webhook.

Register each **tenant** as its own site:

```bash
curl -X POST $ENGINE/sdk/v1/sites -H "X-Site-Key: $SDK_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"slug":"lone-star-roofing","name":"Lone Star Roofing",
       "site_type":"custom","base_url":"https://lone-star-roofing.octively.com"}'
```

`base_url` = the tenant's public URL (makes the payload `url`/canonical
absolute). Nothing in LBF needs to change to satisfy the type.

## 2. Delivery — two shapes (pick one)

Both already match patterns LBF uses today (tenant API pull + deploy webhook):

**A. Pull (fits the SSR renderer).** An LBF API route / job enumerates and
pulls, then writes into Postgres so the page renders from the DB:

```
GET /sdk/v1/articles?site_slug=lone-star-roofing&status=published   → ids
GET /sdk/v1/articles/{id}/content                                    → payload
```

**B. Webhook push (fits LBF's "Publish → rebuild" hook).**
`lib/custom_site.deliver(payload, SITE_PUBLISH_WEBHOOK)` POSTs the payload to an
LBF API route. ⚠️ `deliver` is implemented + unit-tested but **not yet wired to
a service op / route / MCP tool** — call it from a job/script, or the pull path
above (which is wired).

Trigger revalidation the same way LBF already does for its own editor
(`Publish → deploy webhook`); for a Node SSR app that's usually a cache/key
bump rather than a rebuild.

## 3. Mapping ContentFTE → LBF `BlogPostSchema`

ContentFTE's `/content` payload maps almost 1:1 onto LBF's own AEO/GEO blog
model — no lossy conversion required for the SEO fields:

| ContentFTE payload | LBF `BlogPost` field | Notes |
| :--- | :--- | :--- |
| `slug` | `slug` | |
| `title` | `title` | |
| `excerpt` | `metaDescription` + `excerpt` | SEO `<title>` → `metaTitle` (≤60); desc ≤160 |
| `markdown` TL;DR blockquote | `answerFirst` | The 40–60 word direct answer |
| `meta.faqs` / `schema.faq` | `faqs[]` | `{question, answer}` → `FaqItem` |
| `markdown` body | `content: BlogBlock[]` | map H2/H3/H4→`heading`, para→`paragraph`, list→`list`; optionally pull a citable fact→`callout` (≤280) and HowTo steps→`step` |
| brief keyword | `targetQuery` + `keywords[]` | exact local query |
| `## Sources` box | `sources[{label,url}]` | GEO attribution |
| featured image URL | `image` | |
| — | `generatedBy: "ai"` | provenance |
| `schema.article` / `schema.faq` | (your JSON-LD emitter) | either use ContentFTE's or rebuild from `answerFirst`/`faqs` |

LBF block types (from `packages/site-schema/src/index.ts`):
`heading{text,level 2–4}`, `paragraph{text}`, `list{items[]}`,
`callout{text ≤280}`, `step{name,text}`.

**Shortcut vs native:** either store ContentFTE's pre-rendered **`html`** as a
single rich block (fastest), or **map `markdown` → `BlogBlock[]`** so posts stay
native/editable in LBF's schema (recommended for the journal UI).

`markdown_alternate` (frontmatter + body) lines up with LBF's existing
`llms.txt.ts` — serve it as `/blog/{slug}.md` for AI answer engines.

## 4. Rendering — ours to change

`apps/site-renderer` + `packages/templates` are **in this repo**, so the render
side is adaptable to how we want ContentFTE content to appear. Options:

- Add a **first-class blog template** that renders a `BlogPost` (heading/FAQ/
  sources/schema) instead of the single-page business layout.
- Extend `BlogBlockSchema` with an `html` (or `markdown`) block so ContentFTE's
  engine-rendered body drops in **byte-identical** with no markdown parser —
  and all three render targets (WordPress, Astro, custom) stay consistent.
- Since the renderer is **SSR + zero-JS**, prefer the engine's `html` or
  `marked`; there is no reason to add React just to render an article.

## 5. Environment (both sides)

| Side | Var | Purpose |
| :--- | :--- | :--- |
| LBF (renderer/api) | `CONTENTFTE_URL`, `CONTENTFTE_SITE_KEY` | pull `/sdk/v1/articles*` |
| LBF | `OCTIVELY_FACTORY_URL`, `TENANT_SLUG`, `TENANT_API_KEY` | existing tenant content fetch (unchanged) |
| ContentFTE | `SDK_MASTER_KEY` | matches `X-Site-Key` |
| ContentFTE | `SITE_PUBLISH_WEBHOOK` | webhook push target (LBF API route) |

## 6. TL;DR

- LBF Astro sites → **`site_type="custom"`**, one ContentFTE site per tenant.
- Delivery = **pull** `GET /sdk/v1/articles?site_slug=…&status=published` →
  `/articles/{id}/content` (wired), or webhook via `lib/custom_site.deliver`
  (not yet wired to a route).
- `BlogPostSchema` already has AEO/GEO fields, so ContentFTE's TL;DR → `answerFirst`,
  FAQs → `faqs`, sources → `sources`, keyword → `targetQuery`; body maps to
  `BlogBlock[]` (or a single `html` block).
- The Astro render side is ours to reshape — we can add a native blog template
  and/or an `html` block so rendering matches ContentFTE exactly.

See also: `docs/site-onboarding-flow.md` (§2 custom-site flow),
`docs/phase1-feature-map.md` (surface map).
