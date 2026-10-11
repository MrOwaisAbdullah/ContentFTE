# ContentFTE Sanity package

Everything a site needs to store ContentFTE content in Sanity: schema, client
helpers, studio config, and the publish webhook.

```
sanity/
  sanity.config.ts      Studio config (mount at /studio)
  cli.config.ts         `npx sanity schema deploy`
  structure.ts          Studio navigation
  env.ts                projectId/dataset/apiVersion from env (no hardcoded ids)
  schemaTypes/          post, author, category, blockContent
  lib/client.ts         next-sanity client (CDN)
  lib/image.ts          urlFor() image URL builder
  lib/seo.ts            THE SEO fallback rule (resolveSeoTitle/Description)
  webhooks/
    revalidate.ts       Next.js route -> app/api/revalidate/route.ts
```

## Setup

```bash
# 1. copy the folder into your site
cp -r node_modules/content-fte/sanity ./sanity

# 2. env (.env.local)
NEXT_PUBLIC_SANITY_PROJECT_ID=xxxx
NEXT_PUBLIC_SANITY_DATASET=production
NEXT_PUBLIC_SANITY_API_VERSION=2025-09-18
SANITY_API_TOKEN=sk-...            # engine write token (server-side)
SANITY_REVALIDATE_SECRET=...       # webhook shared secret
NEXT_PUBLIC_SITE_URL=https://your.site
INDEXNOW_KEY=...                   # optional

# 3. deploy the schema
npx sanity schema deploy
```

## The two rules this package encodes

**1. Featured image + alt are REQUIRED.**
`postType.mainImage` is `Rule.required()` and its nested `alt` field is
`Rule.required()`. A post missing either cannot leave Draft in Studio. That
is deliberate: on 2026-10-08 the engine published a post whose featured image
had failed upstream, Studio blocked it from publishing, and the pipeline still
reported "Published". The schema now makes the requirement explicit.

**2. SEO fields fall back, they never block.**
`seoTitle`/`seoDescription` are optional (60 / 160 char limits, warnings only).
Pages resolve them with:

```ts
import { resolveSeoTitle, resolveSeoDescription } from "@/sanity/lib/seo";

const metaTitle = resolveSeoTitle(post);        // seoTitle || title
const metaDescription = resolveSeoDescription(post); // seoDescription || summary
```

`resolveSeo*` lives in `lib/seo.ts` so the studio, the engine (which derives
`seoTitle` from the title and `seoDescription` from the summary) and every
consuming site agree on one rule.

## Webhook

Copy `webhooks/revalidate.ts` to `app/api/revalidate/route.ts`, then add the
webhook in Sanity → API → Webhooks:

- URL `https://your.site/api/revalidate?secret=<SANITY_REVALIDATE_SECRET>`
- Filter `type == "post"`, on publish/unpublish
- Projection `{_type, slug, title}`

Credentials come from env only — there is no hardcoded fallback secret.

## Extending

A site's own types (promo banners, analytics, tool reviews) go in
`schemaTypes/` and get appended to `schema.types` in
`schemaTypes/index.ts`. The four engine-owned types should not be edited:
`post_blog` in the engine writes exactly those fields, and a renamed or
removed field silently drops from every published post.
