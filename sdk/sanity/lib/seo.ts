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
 *
 * Length: an explicit `seoTitle` / `seoDescription` is returned exactly as the
 * editor wrote it. Only the *fallback* is shortened — a raw summary can be
 * several hundred characters (a live legacy post shipped a 381-character meta
 * description) and a long title gets cut off in results, so the fallback is
 * trimmed to a sensible snippet length at a word boundary.
 */

export interface SeoSource {
  title?: string;
  summary?: string;
  seoTitle?: string;
  seoDescription?: string;
}

/** Fallback title budget. Leaves room for a ` | Brand` suffix a site may append. */
export const SEO_TITLE_FALLBACK_MAX = 60;
/** Fallback description budget (what search results reliably display). */
export const SEO_DESCRIPTION_FALLBACK_MAX = 155;

/** Cut `text` to at most `max` characters at a word boundary, adding an ellipsis when shortened. */
export function truncateAtWord(text: string, max: number): string {
  const t = text.replace(/\s+/g, " ").trim();
  if (t.length <= max) return t;
  const room = Math.max(1, max - 1); // reserve one character for "…"
  const slice = t.slice(0, room + 1);
  const lastSpace = slice.lastIndexOf(" ");
  // Only back up to a space when it doesn't throw away most of the budget.
  const cut = lastSpace >= room * 0.6 ? slice.slice(0, lastSpace) : t.slice(0, room);
  return `${cut.replace(/[\s,;:.\-–—]+$/, "")}…`;
}

export function resolveSeoTitle(post: SeoSource): string {
  const explicit = (post.seoTitle || "").trim();
  if (explicit) return explicit;
  return truncateAtWord(post.title || "", SEO_TITLE_FALLBACK_MAX);
}

export function resolveSeoDescription(post: SeoSource): string {
  const explicit = (post.seoDescription || "").trim();
  if (explicit) return explicit;
  return truncateAtWord(post.summary || "", SEO_DESCRIPTION_FALLBACK_MAX);
}
