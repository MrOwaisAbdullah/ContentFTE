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

export class ContentFTEClient {
  constructor(
    private baseUrl: string,
    private siteKey: string,
    private maxRetries = 3,
    private backoffMs = 500,
  ) {}

  private headers(extra: Record<string, string> = {}) {
    return { "Content-Type": "application/json", "X-Site-Key": this.siteKey, ...extra };
  }

  private sleep(ms: number) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  private async request(method: string, path: string, body?: unknown, extra: Record<string, string> = {}) {
    let delay = this.backoffMs;
    let lastErr: unknown;
    for (let attempt = 1; attempt <= this.maxRetries; attempt++) {
      try {
        const res = await fetch(`${this.baseUrl}${path}`, {
          method,
          headers: this.headers(extra),
          body: body === undefined ? undefined : JSON.stringify(body),
        });
        if (RETRY_STATUSES.has(res.status) && attempt < this.maxRetries) {
          await this.sleep(delay);
          delay *= 2;
          continue;
        }
        if (!res.ok) throw new Error(`${method} ${path} failed: ${res.status}`);
        return res.json();
      } catch (err) {
        lastErr = err;
        if (attempt >= this.maxRetries) break;
        await this.sleep(delay);
        delay *= 2;
      }
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

  async getArticle(id: number) {
    return this.request("GET", `/sdk/v1/articles/${id}`);
  }

  async generateContent(id: number, regenerate = false) {
    return this.request("POST", `/sdk/v1/articles/${id}/generate`, { regenerate });
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
  async wpPost(postId: number) {
    return this.request("GET", `/sdk/v1/wp/posts/${postId}`);
  }

  async getContent(id: number) {
    return this.request("GET", `/sdk/v1/articles/${id}/content`);
  }

  async listSites() {
    return this.request("GET", "/sdk/v1/sites");
  }

  /** List articles newest-first (filter by site and/or status).
   *  Content-loader usage: list published ids, then getContent(id) each. */
  async listArticles(siteSlug = "", status = "", limit = 100, offset = 0) {
    const qs = new URLSearchParams({
      site_slug: siteSlug, status, limit: String(limit), offset: String(offset),
    });
    return this.request("GET", `/sdk/v1/articles?${qs}`);
  }

  async upsertSite(slug: string, name = "", siteType = "custom", baseUrl = "") {
    return this.request("POST", "/sdk/v1/sites", { slug, name, site_type: siteType, base_url: baseUrl });
  }
}
