/** ContentFTE JS/TS SDK client (§5.12) — copy-paste quickstart.
 *
 * ```ts
 * import { ContentFTEClient } from "./contentfte";
 * const client = new ContentFTEClient("https://engine.example.com", "site-key");
 * const art = await client.submitArticle("mysite", "best crm for agencies");
 * await client.generateContent(art.id); // briefed -> drafted (runs the LLM)
 * await client.approveArticle(art.id, true);
 * const content = await client.getContent(art.id);
 * ```
 *
 * Transient failures (network errors, 429/5xx) retry with exponential
 * backoff: up to 3 attempts at 0.5s / 1s / 2s. Pair POSTs with an
 * idempotencyKey so retries never duplicate an article server-side.
 */

const RETRY_STATUSES = new Set([429, 500, 502, 503, 504]);
/** Methods that are safe to repeat; a POST only is when it carries an Idempotency-Key. */
const IDEMPOTENT_METHODS = new Set(["GET", "HEAD", "PUT", "DELETE", "OPTIONS"]);

/** A non-2xx answer from the engine. `status` and the server's `detail` are kept so callers can react. */
export class ContentFTEError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
    message: string,
    /** Machine-readable reason: not_found, invalid_state, gate_failed, budget_exceeded, ... ("" if the server sent none). */
    public readonly code: string = "",
    /** What to do about it, when the server says. */
    public readonly next: string = "",
  ) {
    super(message);
    this.name = "ContentFTEError";
  }
}

/** One row from `listArticles`. */
export interface ArticleSummary {
  id: number;
  site_id: number;
  site_slug: string;
  title: string;
  slug: string;
  status: string;
  created_at: string | null;
  published_at: string | null;
  cost_usd: number;
}

/** Result of `listArticles` (newest-first, paginated). */
export interface ArticleListResult {
  articles: ArticleSummary[];
  count: number;
  total: number;
  limit: number;
  offset: number;
}

/** Result of `llmsTxt`. NOTE: `llms_txt` is the text to serve at /llms.txt. */
export interface LlmsTxtResult {
  site: string;
  count: number;
  llms_txt: string;
}

/** Result of `sitemapXml`. NOTE: `sitemap_xml` is the XML to serve at /sitemap.xml. */
export interface SitemapResult {
  site: string;
  count: number;
  sitemap_xml: string;
}

/** Result of `wpPost` (raw WordPress content + registered SEO meta). */
export interface WpPostResult {
  id: number;
  slug: string;
  status: string;
  title: string;
  content_raw: string;
  excerpt: string;
  url: string;
  modified: string;
  featured_media: number;
  categories: number[];
  tags: number[];
  meta: Record<string, unknown>;
}

/** SEO + AEO fields, first-class so sites don't have to parse them out of
 * the markdown (mirrors the Sanity post schema's seoTitle/seoDescription/
 * focusKeyword/tldr fields and the Yoast/Rank Math meta on WordPress). */
export interface SeoFields {
  /** SEO title for search/social (<=60 chars). Falls back to `title`. */
  title: string;
  /** Distinct <title> text (payload v2); falls back to `title`. */
  meta_title?: string;
  /** Meta description (<=160 chars). Same value as `excerpt`. */
  description: string;
  /** Canonical URL of the article (payload v2). */
  canonical?: string;
  /** The primary keyword this post targets (empty when unknown). */
  focus_keyword: string;
  /** The 40-60 word TL;DR answer, or "" when the post has none. */
  tldr: string;
}

/** The unified delivery payload returned by `getContent`. */
export interface DeliveryPayload {
  id: number;
  title: string;
  slug: string;
  url: string;
  excerpt: string;
  html: string;
  markdown: string;
  markdown_alternate: string;
  faq_html: string;
  schema: {
    article?: Record<string, unknown>;
    faq?: Record<string, unknown> | null;
  };
  seo?: SeoFields;
  /** Featured image (payload v2), when one with a public URL exists. */
  image?: { url: string; alt: string; width?: number; height?: number } | null;
  /** Ready-made Open Graph values (payload v2). */
  og?: {
    type: string;
    title: string;
    description: string;
    url: string;
    image: string;
    image_alt: string;
    published_time: string;
    modified_time: string;
  };
  payload_version?: number;
  status?: string;
  scores?: Record<string, number>;
  cost_usd?: number;
  meta?: Record<string, unknown>;
}

export class ContentFTEClient {
  constructor(
    private baseUrl: string,
    private siteKey: string,
    private maxRetries = 3,
    private backoffMs = 500,
    private timeoutMs = 30_000,
  ) {}

  private headers(extra: Record<string, string> = {}) {
    return { "Content-Type": "application/json", "X-Site-Key": this.siteKey, ...extra };
  }

  private sleep(ms: number) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  private async request(
    method: string,
    path: string,
    body?: unknown,
    extra: Record<string, string> = {},
    timeoutMs = this.timeoutMs,
  ) {
    let delay = this.backoffMs;
    let lastErr: unknown;
    const repeatable = IDEMPOTENT_METHODS.has(method.toUpperCase()) || "Idempotency-Key" in extra;
    for (let attempt = 1; attempt <= this.maxRetries; attempt++) {
      let res: Response;
      try {
        res = await fetch(`${this.baseUrl}${path}`, {
          method,
          headers: this.headers(extra),
          body: body === undefined ? undefined : JSON.stringify(body),
          // A hung engine must not hang the caller (and with it a server-rendered page) forever.
          signal: AbortSignal.timeout(timeoutMs),
        });
      } catch (err) {
        // No response at all (timeout / network): repeat only when repeating cannot duplicate work.
        lastErr = err;
        if (!repeatable || attempt >= this.maxRetries) break;
        await this.sleep(delay);
        delay *= 2;
        continue;
      }
      // 429 = "not processed, slow down" (always safe to repeat); other transient statuses only when repeatable.
      const retryable = res.status === 429 || (RETRY_STATUSES.has(res.status) && repeatable);
      if (retryable && attempt < this.maxRetries) {
        await this.sleep(delay);
        delay *= 2;
        continue;
      }
      if (!res.ok) {
        // 4xx will not change on retry (this used to retry 401/404/409/422 three times). Keep the reason.
        let detail = "";
        let code = "";
        let next = "";
        try {
          const body = (await res.json()) as { detail?: unknown; code?: unknown; next?: unknown };
          detail = String(body?.detail ?? "");
          code = String(body?.code ?? "");
          next = String(body?.next ?? "");
        } catch {
          /* non-JSON error body */
        }
        throw new ContentFTEError(
          res.status,
          detail,
          `${method} ${path} failed: ${res.status}${detail ? ` - ${detail}` : ""}`,
          code,
          next,
        );
      }
      return res.json();
    }
    throw lastErr;
  }

  async submitArticle(site_slug: string, keyword = "", brief: Record<string, unknown> = {}, idempotencyKey = "") {
    return this.request(
      "POST",
      "/sdk/v1/articles",
      { site_slug, keyword, brief },
      idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {},
    );
  }

  async getArticle(id: number): Promise<Record<string, unknown>> {
    return this.request("GET", `/sdk/v1/articles/${id}`);
  }

  async generateContent(id: number, regenerate = false) {
    // LLM generation routinely takes 30-120 s, so it gets a much longer timeout than reads.
    return this.request("POST", `/sdk/v1/articles/${id}/generate`, { regenerate }, {}, 180_000);
  }

  async approveArticle(id: number, approved = true, note = "") {
    return this.request("POST", `/sdk/v1/articles/${id}/approve`, { approved, note });
  }

  async publishArticle(id: number, mode: "draft" | "publish" = "draft") {
    return this.request("POST", `/sdk/v1/articles/${id}/publish`, { mode });
  }

  /** Refresh an already-published article (§5.11 decay path). WordPress:
   *  updates the existing post; custom sites: re-pull getContent(). */
  async refreshArticle(id: number) {
    return this.request("POST", `/sdk/v1/articles/${id}/refresh`);
  }

  /** Read a WordPress post back (raw content + registered SEO meta). */
  async wpPost(postId: number): Promise<WpPostResult> {
    return this.request("GET", `/sdk/v1/wp/posts/${postId}`);
  }

  async getContent(id: number): Promise<DeliveryPayload> {
    return this.request("GET", `/sdk/v1/articles/${id}/content`);
  }

  async listSites() {
    return this.request("GET", "/sdk/v1/sites");
  }

  /** Compose the site's llms.txt (§5.8) from its published articles. */
  async llmsTxt(siteSlug: string): Promise<LlmsTxtResult> {
    return this.request("GET", `/sdk/v1/sites/${siteSlug}/llms.txt`);
  }

  /** Compose the site's XML sitemap (§5.6) from published articles. */
  async sitemapXml(siteSlug: string): Promise<SitemapResult> {
    return this.request("GET", `/sdk/v1/sites/${siteSlug}/sitemap.xml`);
  }

  /** List articles newest-first (filter by site and/or status).
   *  Content-loader usage: list published ids, then getContent(id) each. */
  async listArticles(siteSlug = "", status = "", limit = 100, offset = 0): Promise<ArticleListResult> {
    const qs = new URLSearchParams({
      site_slug: siteSlug, status, limit: String(limit), offset: String(offset),
    });
    return this.request("GET", `/sdk/v1/articles?${qs}`);
  }

  /** Create a site, or update name/site_type/baseUrl of an existing slug
   *  (empty values leave fields untouched; create defaults to "custom"). */
  async upsertSite(slug: string, name = "", siteType = "", baseUrl = "") {
    return this.request("POST", "/sdk/v1/sites", { slug, name, site_type: siteType, base_url: baseUrl });
  }

  /** Keyword-ledger view: rows + per-status counts (parity B1). */
  async listQueue(siteSlug: string, status = "", limit = 100) {
    const qs = new URLSearchParams({ status, limit: String(limit) });
    return this.request("GET", `/sdk/v1/sites/${siteSlug}/queue?${qs}`);
  }

  /** research_data worksheet view: keyword rows + research snapshot. */
  async listResearch(siteSlug: string, status = "", limit = 100) {
    const qs = new URLSearchParams({ status, limit: String(limit) });
    return this.request("GET", `/sdk/v1/sites/${siteSlug}/research?${qs}`);
  }

  /** content_briefs worksheet view: only rows carrying a brief. */
  async listBriefs(siteSlug: string, limit = 100) {
    return this.request("GET", `/sdk/v1/sites/${siteSlug}/briefs?limit=${limit}`);
  }

  /** Audit + cost-ledger view (kind: "usage" | "cost" | action prefix). */
  async listLogs(kind = "", limit = 200) {
    const qs = new URLSearchParams({ kind, limit: String(limit) });
    return this.request("GET", `/sdk/v1/logs?${qs}`);
  }

  /** Operator edit of contentMd (approved reopens to generated). */
  async updateContent(id: number, contentMd: string, note = "") {
    return this.request("PATCH", `/sdk/v1/articles/${id}/content`, { content_md: contentMd, note });
  }

  /** Trigger a pipeline stage in the background (202; 409 on overlap). */
  async runStage(stage: string) {
    return this.request("POST", `/sdk/v1/run/${stage}`);
  }
}

/** The subset of Next.js `Metadata` that `buildMetadata` returns (kept structural so the SDK needs no `next` dependency). */
export interface BuiltMetadata {
  title: string;
  description: string;
  alternates: { canonical: string };
  openGraph: {
    type: "article";
    title: string;
    description: string;
    url: string;
    publishedTime?: string;
    modifiedTime?: string;
    images?: { url: string; alt?: string; width?: number; height?: number }[];
  };
  twitter: { card: "summary_large_image" | "summary"; title: string; description: string; images?: string[] };
}

/**
 * Map a delivery payload to Next.js `generateMetadata()` output, so a page's head tags (title, description,
 * canonical, Open Graph, Twitter) come from the engine's single source instead of being re-derived by hand:
 *
 *     export async function generateMetadata({ params }) {
 *       return buildMetadata(await cfte.getContent(id));
 *     }
 */
export function buildMetadata(payload: DeliveryPayload): BuiltMetadata {
  const seo = payload.seo;
  const title = (seo?.meta_title || seo?.title || payload.title || "").trim();
  const description = (seo?.description || payload.excerpt || "").trim();
  const canonical = seo?.canonical || payload.url || "";
  const og = payload.og;
  const image = payload.image && payload.image.url ? payload.image : null;
  return {
    title,
    description,
    alternates: { canonical },
    openGraph: {
      type: "article",
      title: og?.title || title,
      description: og?.description || description,
      url: og?.url || canonical,
      ...(og?.published_time ? { publishedTime: og.published_time } : {}),
      ...(og?.modified_time ? { modifiedTime: og.modified_time } : {}),
      ...(image ? { images: [{ url: image.url, alt: image.alt, width: image.width, height: image.height }] } : {}),
    },
    twitter: {
      card: image ? "summary_large_image" : "summary",
      title: og?.title || title,
      description: og?.description || description,
      ...(image ? { images: [image.url] } : {}),
    },
  };
}
