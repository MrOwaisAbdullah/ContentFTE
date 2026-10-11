/**
 * The single fallback rule for SEO fields.
 *
 * `seoTitle` and `seoDescription` are optional fields a post may never fill
 * in (older posts, or a publish that didn't derive them). The page must not
 * render an empty <title> or meta description because of that:
 *
 *   seoDescription ?? summary
 *   seoTitle       ?? title
 *
 * Exactly one definition of this rule exists so the studio, the engine
 * (which derives seoTitle from the title and seoDescription from the
 * summary) and every consuming site agree. See
 * skills/contentfte/references/sanity.md.
 */

export interface SeoSource {
  title?: string;
  summary?: string;
  seoTitle?: string;
  seoDescription?: string;
}

export function resolveSeoTitle(post: SeoSource): string {
  return (post.seoTitle || "").trim() || (post.title || "").trim();
}

export function resolveSeoDescription(post: SeoSource): string {
  return (post.seoDescription || "").trim() || (post.summary || "").trim();
}
