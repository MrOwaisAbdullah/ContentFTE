# Sanity store — schema, SEO fields, and the featured-image rule

Read this when the site stores content in Sanity (`site_type="sanity"`), or
when the user asks about the Sanity schema, SEO fields in Studio, TL;DR, or a
post that "won't publish" in Studio.

## The pain: keeping SEO fields separate

A Sanity post stores its search/social metadata as **first-class fields**,
separate from the ones a reader sees. WordPress gets these from Yoast / Rank
Math (`_yoast_wpseo_title`, `_yoast_wpseo_metadesc`, `_yoast_wpseo_focuskw`);
the Sanity equivalent is a small extension to the `post` type:

```ts
// sanity/schemaTypes/postType.ts
defineField({
  name: "seoTitle",
  title: "SEO Title",
  type: "string",
  description: "Search/social title. 60 characters or fewer. Falls back to the post title when empty.",
  validation: (Rule) => Rule.max(60).warning("Keep SEO titles at 60 characters or fewer"),
}),
defineField({
  name: "seoDescription",
  title: "SEO Description",
  type: "text",
  rows: 3,
  description: "Meta description for search results. 160 characters or fewer. Falls back to Summary when empty.",
  validation: (Rule) => Rule.max(160).warning("Meta descriptions are truncated at roughly 160 characters"),
}),
defineField({
  name: "focusKeyword",
  title: "Focus Keyword",
  type: "string",
  description: "The primary keyword this post targets (the Yoast/Rank Math focus-keyphrase equivalent).",
}),
defineField({
  name: "tldr",
  title: "TL;DR",
  type: "text",
  rows: 4,
  description: "40-60 word direct answer to the primary keyword question. Also mirrored at the top of the content as the TL;DR blockquote.",
  validation: (Rule) => Rule.max(600).warning("A TL;DR is 40-60 words (~300 characters)"),
}),
```

The engine **writes** them: `focusKeyword` from the ledger keyword,
`seoTitle` from the post title, `seoDescription` from the summary, and `tldr`
extracted from the content (see `lib/sanity_adapter.py::post_blog` and
`lib/geo.extract_tldr`). They are derived deterministically in
`blog_agent/posting_agent.py` — never by asking a model to copy them.

Limits are the Yoast/Rank Math "green" thresholds and are **warnings only**.
Never make an SEO field `required()` (see the rule below).

## The other rule: SEO fields fall back, they never block

A page must not render an empty `<title>` or meta description because an
older post never filled `seoTitle`/`seoDescription`. Resolve them once:

```ts
import { resolveSeoTitle, resolveSeoDescription } from "@/sanity/lib/seo";

const metaTitle = resolveSeoTitle(post);          // seoTitle || title
const metaDescription = resolveSeoDescription(post); // seoDescription || summary
```

Next.js, in `app/blog/[slug]/page.tsx`:

```ts
export async function generateMetadata({params}): Promise<Metadata> {
  const {slug} = await params;
  const blog = await client.fetch(`*[_type == "post" && slug.current == "${slug}"]{
    title, summary, seoTitle, seoDescription, focusKeyword, mainImage
  }[0]`);

  if (!blog) return {title: "Blog Post Not Found", description: "The requested blog post could not be found."};

  const metaTitle = blog.seoTitle || blog.title;
  const metaDescription = blog.seoDescription || blog.summary;
  return {
    title: metaTitle,
    description: metaDescription,
    keywords: blog.focusKeyword ? [blog.focusKeyword] : undefined,
  };
}
```

Remember to add the new fields to **every** GROQ projection that needs them —
`generateStaticParams`, `generateMetadata`, and the page query each select
their own field list, so a field omitted from a query is `undefined` at
runtime.

## TL;DR already exists — it was just inline

The engine has always emitted a mandatory 40-60 word TL;DR as the opening
blockquote (spec §5.7): required in every brief template, enforced by the
generator prompt, checked by the eval agent and by `_content_checks`' `tldr`
gate. The gap was that it only ever lived inside `content`, so answer engines
and site meta had to parse a blockquote out of Portable Text to read the most
quotable sentence in the post. The `tldr` field fixes that — the blockquote
stays for readers, the field is for machines.

## ⚠️ Featured image: required, and so is its alt

```ts
defineField({
  name: "mainImage",
  type: "image",
  options: {hotspot: true},
  fields: [
    {
      name: "alt",
      type: "string",
      title: "Alternative text",
      validation: (Rule) => Rule.required(),
    },
  ],
  validation: (Rule) => Rule.required(),
}),
```

Two independent `required()` rules matter. `Rule.required()` on the image
catches a missing image; the rule on the nested `alt` catches the quieter
case — an uploaded image with an empty alt field, which the outer rule happily
accepts because the image object exists.

**Live incident (2026-10-08):** the engine's featured-image generator died on
a Gemini 503. The post was still created, Studio showed it as a Draft that
could not be published (mainImage + alt empty, both red), and Discord plus the
sheet both reported "Published". Before assuming a Studio bug when a post
won't publish, check: **mainImage present, alt present, ≥1 category, summary
non-empty**. Those are the only required fields.

When the featured image fails upstream the engine now:
1. retries `generate_image_tool` directly (no LLM in that path, so it cannot
   503 the way the nested Image Selection Agent did),
2. promotes an already-generated AI in-post image into the featured slot,
3. and only then publishes flagged — reporting "needs_image" honestly instead
   of claiming "Published".

## Ready-made package

The full studio ships in the SDK: `sdk/sanity/` (schema + `lib/seo.ts` +
client + `webhooks/revalidate.ts`). Copy it into the site as `sanity/`:

```bash
cp -r node_modules/content-fte/sanity ./sanity
npx sanity schema deploy
```

Copy `webhooks/revalidate.ts` to `app/api/revalidate/route.ts` and point the
Sanity publish webhook at it. That route reads its secret from
`SANITY_REVALIDATE_SECRET` and has **no hardcoded fallback** — never commit a
key or secret into the repo (a real site's route shipped with an inline
IndexNow key and default secret; treat any such file as compromised and rotate).

## GROQ notes

- Reading drafts: the engine pins `perspective=raw` for document lookups and
  `published` for live-site pools (`fetch_internal_links`, `list_posts`, link
  validation). Mirror that or unpublished edits will vanish from the live site.
- `slug.current`, not `slug`, is what you select.
- Fetch `content`, `faqs`, `summary` for a full post; `title, slug, mainImage`
  is enough for listings.
