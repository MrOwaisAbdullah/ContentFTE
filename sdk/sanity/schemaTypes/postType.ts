/**
 * Post schema — mirrors the live studio (Owais-Abdullah/sanity/schemaTypes/postType.ts).
 *
 * THE RULE THAT MATTERS: `mainImage` is required AND its `alt` is required.
 * On 2026-10-08 the engine's featured-image path failed (Gemini 503), the
 * post was still created, and Studio then showed it as a Draft that could
 * not be published: both fields empty, both red. Discord and the sheet both
 * said "Published". Keeping this schema in the SDK makes that contract
 * explicit and version-controlled instead of a hand-edited Studio field.
 *
 * SEO FIELDS: `seoTitle`/`seoDescription`/`focusKeyword`/`tldr` are separate
 * from `title`/`summary` so search, social and answer engines can read them
 * without re-deriving. They are OPTIONAL with fallbacks, never required:
 *   seoTitle       ?? title     (see lib/seo.ts resolveSeoTitle)
 *   seoDescription ?? summary   (see lib/seo.ts resolveSeoDescription)
 *
 * NOTE: `Rule.required()` on the image alone is NOT enough — it passes when
 * the image object exists but `alt` is empty. The alt rule lives on the
 * nested field so Studio reports it as its own actionable error.
 */
import { DocumentTextIcon } from "@sanity/icons/DocumentText";
import { defineArrayMember, defineField, defineType } from "sanity";

export const postType = defineType({
  name: "post",
  title: "Post",
  type: "document",
  icon: DocumentTextIcon,
  fields: [
    defineField({
      name: "title",
      type: "string",
      validation: (Rule) => Rule.required(),
    }),
    defineField({
      name: "slug",
      type: "slug",
      options: {
        source: "title",
      },
      validation: (Rule) => Rule.required(),
    }),
    // Engine writes a single author reference (SANITY_DEFAULT_AUTHOR_ID).
    // Optional, matching the live schema: a post can live without one.
    defineField({
      name: "author",
      type: "reference",
      to: { type: "author" },
    }),
    /**
     * Featured image + alternative text — BOTH REQUIRED.
     *
     * This pair is the publish blocker. Alt text is not decoration here: it
     * is what image search and answer engines read to decide what the post
     * is about (spec §5.8 GEO) and its absence is a WCAG 1.1.1 failure.
     */
    defineField({
      name: "mainImage",
      type: "image",
      options: {
        hotspot: true,
      },
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
    // Required with min(1): the engine resolves categories to references and
    // auto-creates missing category documents, so a post always carries one.
    defineField({
      name: "categories",
      type: "array",
      of: [defineArrayMember({ type: "reference", to: { type: "category" } })],
      validation: (Rule) => Rule.required().min(1),
    }),
    // Engine writes the 50-160 char SEO meta description. max(300) with a
    // warning mirrors the live schema -- the warning keeps longer summaries
    // publishable without blocking the pipeline.
    defineField({
      name: "summary",
      type: "text",
      validation: (Rule) =>
        Rule.required().max(300).warning("Short summaries are usually better"),
    }),
    /**
     * SEO + AEO fields. A Sanity post previously had none of these, so a
     * Sanity site could not store a focus keyword, a search/social title, or
     * a meta description distinct from the page title -- exactly what Yoast
     * and Rank Math have always provided on the WordPress path
     * (`_yoast_wpseo_focuskw`, `_yoast_wpseo_title`, `rank_math_*`), where
     * the engine already writes them (see lib/wordpress.py `_meta_payload`).
     *
     * The limits are the Yoast/Rank Math "green" thresholds: SEO title 60,
     * meta description 160. They are warnings, not errors -- a longer value
     * must never become a second publish blocker the way the missing
     * featured image was.
     */
    defineField({
      name: "seoTitle",
      title: "SEO Title",
      type: "string",
      description:
        "Search/social title. 60 characters or fewer. Falls back to the post title when empty.",
      validation: (Rule) =>
        Rule.max(60).warning("Keep SEO titles at 60 characters or fewer"),
    }),
    defineField({
      name: "seoDescription",
      title: "SEO Description",
      type: "text",
      rows: 3,
      description:
        "Meta description for search results. 160 characters or fewer. Falls back to Summary when empty.",
      validation: (Rule) =>
        Rule.max(160).warning(
          "Meta descriptions are truncated at roughly 160 characters"
        ),
    }),
    defineField({
      name: "focusKeyword",
      title: "Focus Keyword",
      type: "string",
      description:
        "The primary keyword this post targets (the Yoast/Rank Math focus-keyphrase equivalent).",
    }),
    /**
     * Secondary keywords -- the operator's supporting targets, 2-3 of them.
     * The engine's keyword gate (lib/seo_keywords.py) requires each one to
     * appear in its own H2/H3 heading plus 2-3 body sentences, so a published
     * post normally has at least two of these. Optional with no validation
     * rule on purpose: older posts predate the field, and blocking a publish
     * over a missing *optional* field is exactly the failure mode the
     * mainImage rule exists for.
     */
    defineField({
      name: "secondaryKeywords",
      title: "Secondary Keywords",
      type: "array",
      of: [{type: "string"}],
      description:
        "2-3 supporting keywords, each used verbatim in its own H2/H3 heading and 2-3 body sentences.",
    }),
    /**
     * TL;DR (spec §5.7 AEO) as a first-class field.
     *
     * The engine has always emitted a mandatory 40-60 word TL;DR as the
     * opening blockquote -- but only inside `content`. That forced every
     * consumer (site meta tags, answer-engine extractors, the delivery
     * payload) to parse a blockquote out of Portable Text just to read the
     * single most quotable sentence in the post. Stored separately, it is
     * one field read.
     */
    defineField({
      name: "tldr",
      title: "TL;DR",
      type: "text",
      rows: 4,
      description:
        "40-60 word direct answer to the primary keyword question. Also mirrored at the top of the content as the TL;DR blockquote.",
      validation: (Rule) =>
        Rule.max(600).warning("A TL;DR is 40-60 words (~300 characters)"),
    }),
    // `blockContent` (not an inline array) is what the engine writes into:
    // blocks, images, code objects and GFM tables. See blockContentType.ts.
    defineField({
      name: "content",
      type: "blockContent",
      validation: (Rule) => Rule.required(),
    }),
    defineField({
      name: "faqs",
      title: "FAQs",
      type: "array",
      of: [
        defineArrayMember({
          type: "object",
          fields: [
            {
              name: "question",
              type: "string",
              title: "Question",
            },
            {
              name: "answer",
              type: "text",
              title: "Answer",
            },
          ],
        }),
      ],
    }),
  ],
  preview: {
    select: {
      title: "title",
      author: "author.name",
      media: "mainImage",
    },
    prepare(selection) {
      const { author } = selection;
      return { ...selection, subtitle: author && `by ${author}` };
    },
  },
});
