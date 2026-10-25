// Pure (no React) site-scope resolution for the per-site pages
// (keywords / research / briefs / stages). UX-05: never silently fall back
// to the first site when no ?site= is provided — force an explicit choice
// so a page never shows site-A data under an "All Sites (Fleet)" heading.

export interface SiteOption {
  slug: string;
  name?: string;
}

export interface ScopeResolution {
  slug: string;
  explicit: boolean;
  sites: SiteOption[];
  singleSite: boolean;
}

export function resolveScope(sites: SiteOption[], requested: string): ScopeResolution {
  const list = sites ?? [];
  const slugs = new Set(list.map((s) => s.slug));
  const requestedTrim = (requested || "").trim();
  if (requestedTrim && slugs.has(requestedTrim)) {
    return { slug: requestedTrim, explicit: true, sites: list, singleSite: list.length === 1 };
  }
  if (list.length === 1) {
    return { slug: list[0].slug, explicit: false, sites: list, singleSite: true };
  }
  return { slug: "", explicit: false, sites: list, singleSite: false };
}