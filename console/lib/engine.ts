import "server-only";
import { currentInstance } from "./instances";
import { redactSiteList } from "./site-secrets";
import { verifySession } from "./session";

export class EngineError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** Reads should fail fast so one hung engine can't freeze every page (CON-06). */
const READ_TIMEOUT_MS = 15_000;
/** Mutations (generate / publish / run stage) legitimately take much longer. */
const WRITE_TIMEOUT_MS = 180_000;

type EngineInit = RequestInit & { json?: unknown; timeoutMs?: number };

/**
 * Engine call against the currently selected instance (cookie-switched).
 *
 * Site responses are returned with secrets stripped (see lib/site-secrets.ts):
 * the engine's GET /sites includes the raw settings JSON, and these results are
 * routinely passed to client components. Use `engineUnredacted` only inside a
 * server action that must merge with the stored values.
 */
export async function engine<T = unknown>(path: string, init?: EngineInit): Promise<T> {
  return redactSiteList(await engineUnredacted<T>(path, init));
}

/** Like `engine()` but WITHOUT secret redaction. Server actions only — never pass the result to the client. */
export async function engineUnredacted<T = unknown>(path: string, init?: EngineInit): Promise<T> {
  const { json, headers, timeoutMs, ...rest } = init ?? {};
  // Data-access-layer check: layouts don't re-run on client navigation and
  // server actions are public POST endpoints, so never rely on the page/middleware
  // alone before talking to an engine with the operator's key.
  if (!(await verifySession())) throw new EngineError(401, "401 not signed in");
  const inst = await currentInstance();
  const method = (rest.method || "GET").toUpperCase();
  const limit = timeoutMs ?? (method === "GET" ? READ_TIMEOUT_MS : WRITE_TIMEOUT_MS);
  let res: Response;
  try {
    res = await fetch(`${inst.baseUrl}/sdk/v1${path}`, {
      ...rest,
      cache: "no-store",
      signal: rest.signal ?? AbortSignal.timeout(limit),
      headers: {
        ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(inst.apiKey ? { "X-Site-Key": inst.apiKey } : {}),
        ...(headers as Record<string, string> | undefined),
      },
      body: json !== undefined ? JSON.stringify(json) : (rest.body as BodyInit | undefined),
    });
  } catch (e) {
    if (e instanceof Error && (e.name === "TimeoutError" || e.name === "AbortError")) {
      throw new EngineError(504, `504 engine '${inst.name}' did not answer within ${Math.round(limit / 1000)}s`);
    }
    throw new EngineError(503, `503 engine '${inst.name}' unreachable at ${inst.baseUrl}`);
  }
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { raw: text };
  }
  if (!res.ok) {
    const detail =
      (data as { detail?: string } | null)?.detail ||
      (data as { error?: string } | null)?.error ||
      text.slice(0, 300);
    throw new EngineError(res.status, `${res.status} ${detail}`);
  }
  return data as T;
}

export interface SiteInfo {
  id: number;
  slug: string;
  name: string;
  site_type: string;
  base_url: string;
  publish_mode?: string;
  /** Secrets are stripped by `engine()`; see `secrets_set` for which exist. */
  settings?: Record<string, unknown>;
  /** Which known secrets are stored (e.g. `wp_app_password`) — values never leave the server. */
  secrets_set?: Record<string, boolean>;
  has_key?: boolean;
  created_at?: string | null;
}

export interface SiteList {
  sites: SiteInfo[];
  count: number;
}

/** GET /articles/{id}/gate — the engine's deterministic quality gate (plan SEO-01). */
export interface ArticleGate {
  id: number;
  /** false → approval is refused unless forced (when `enforced`). */
  pass: boolean;
  enforced: boolean;
  /** Provable failures: unsupported claims, failed draft checks, eval floor, broken links. */
  blocking: string[];
  /** Advisory: AEO lint, missing research / sub-scores. */
  warnings: string[];
  assessed_at: string;
}

/** GET /stages — one finished `stage.run` audit row (console Wave 5). */
export interface StageRun {
  id: number;
  stage: string;
  ok: boolean;
  detail: string;
  duration_ms: number;
  started_at: string;
  finished_at: string | null;
}

/** GET /stages — history + last-run rollup + live running set. */
export interface StagesView {
  running: string[];
  last: Record<string, StageRun>;
  history: StageRun[];
  count: number;
}

/** GET /sites/{slug}/health — ledger + WP config + live probes (spec §5.6). */
export interface SiteCadenceStatus {
  frequency: "manual" | "daily" | "every_2_days" | "twice_a_week" | "weekly" | "biweekly" | "monthly" | string;
  max_posts_per_cadence: number;
  require_approval: boolean;
  auto_publish: boolean;
  publish_mode: "draft" | "publish" | string;
  last_published_at: string | null;
  last_published_id: number | null;
  last_published_title: string | null;
  next_allowed_at: string | null;
  can_publish_now: boolean;
  seconds_remaining: number;
  can_auto_publish: boolean;
  /** posts that went out inside the current cadence window (counts toward max_posts_per_cadence) */
  posts_in_window?: number;
  /** the site refuses publishes over the cap (settings.enforce_cadence) */
  enforced?: boolean;
}

/** GET /sites/{slug}/health — ledger + WP config + live probes + cadence (spec §5.6). */
export interface SiteHealth {
  site: string;
  ok: boolean;
  ledger: { briefable: number; published: number };
  wp_configured: boolean;
  base_url: string;
  checks: string[];
  critical: string[];
  cadence?: SiteCadenceStatus;
}

/** GET /search-console — per-site GSC connectivity (one sites.list call). */
export interface SearchConsoleSiteStatus {
  slug: string;
  base_url: string;
  property: string;
  /** tri-state: true = property visible to the SA, false = not shared,
      null = the check itself couldn't run (reason explains). */
  connected: boolean | null;
  permission_level?: string;
  reason?: string;
  metrics_28d?: {
    clicks: number;
    impressions: number;
    ctr: number;
    position: number;
  };
}

export interface SpendSummary {
  site_slug: string;
  wtd_usd: number;
  mtd_usd: number;
  total_usd: number;
  wtd_formatted: string;
  mtd_formatted: string;
  total_formatted: string;
}

export interface SearchConsoleView {
  sites: SearchConsoleSiteStatus[];
  service_account_email: string;
  credentials: boolean;
  properties_visible: number | null;
  visible: { site_url: string; permission_level: string }[];
}

export interface QueueRow {
  id: number;
  keyword: string;
  status: string;
  intent: string;
  volume: number;
  difficulty: number;
  priority_score: number;
  cluster_id: string;
  target_url: string;
  subject: string;
  added_at: string | null;
}

export interface QueueView {
  site: string;
  counts: Record<string, number>;
  queue: QueueRow[];
  count: number;
}

export interface BriefPeek {
  keyword?: string;
  intent?: string;
  status?: string;
  priority_score?: number;
  research_snapshot?: Record<string, unknown>;
  hint?: string;
  error?: string;
}

export interface ArticleListItem {
  id: number;
  site_id: number;
  site_slug: string;
  title: string;
  slug: string;
  status: string;
  created_at: string | null;
  published_at: string | null;
  cost_usd: number | null;
  quality?: number | null;
  word_count?: number | null;
  summary?: string;
  /** staged image count (meta.images) — the Media page detail-fetches only
      articles with art; 0/undefined mean none. */
  images?: number;
}

export interface ArticleList {
  articles: ArticleListItem[];
  count: number;
  total: number;
  limit: number;
  offset: number;
}

export interface ArticleStats {
  site_slug: string;
  range_days: number;
  total: number;
  by_status: Record<string, number>;
  scored: number;
  avg_quality: number | null;
  quality_pass_rate: number | null;
  words_total: number;
  in_range: { created: number; published: number };
  cost: { total_usd: number; per_kind: Record<string, number>; per_1k_words_usd: number | null };
  published_per_day: { date: string; created: number }[];
  sites: { slug: string; articles: number; published: number; approved: number; quality_avg: number | null; words: number }[];
}

/** research_data worksheet row (GET /sites/{slug}/research). */
export interface ResearchItem {
  id: number;
  keyword: string;
  status: string;
  intent: string;
  volume: number;
  difficulty: number;
  subject: string;
  summary: string;
  primary_keyword: string;
  secondary_keywords: string;
  generated: boolean;
  added_at: string | null;
}

export interface ResearchView {
  site: string;
  research: ResearchItem[];
  count: number;
}

/** content_briefs worksheet row (GET /sites/{slug}/briefs). */
export interface BriefItem {
  id: number;
  keyword: string;
  status: string;
  intent: string;
  brief: string;
  faqs: string;
  sources: string;
  summary: string;
  secondary_keywords: string;
}

export interface BriefsView {
  site: string;
  briefs: BriefItem[];
  count: number;
}

/** audit_log row (GET /logs). */
export interface LogEntry {
  id: number;
  action: string;
  article_id: number | null;
  payload: Record<string, unknown>;
  created_at: string | null;
}

export interface CostEntry {
  id: number;
  article_id: number;
  kind: string;
  amount_usd: number;
  detail: Record<string, unknown>;
  created_at: string | null;
}

export interface LogsView {
  audit: LogEntry[];
  costs: CostEntry[];
  kind: string;
  count: number;
}

export interface ArticleDetail {
  id: number;
  site_id: number;
  title: string;
  slug: string;
  status: string;
  scores: Record<string, unknown>;
  cost_usd: number | null;
  keyword_id: number | null;
  markdown?: string;
  html?: string;
  meta?: Record<string, unknown>;
  /* Delivery-payload fields (custom_site.build_delivery_payload) that ride
     along on GET /articles/{id}/content — the SEO & meta tab's data. */
  url?: string;
  excerpt?: string;
  date_published?: string | null;
  date_modified?: string | null;
  seo?: {
    title?: string;
    description?: string;
    focus_keyword?: string;
    tldr?: string;
  };
  schema?: {
    article?: Record<string, unknown> | null;
    faq?: Record<string, unknown> | null;
  };
}

/** GET /wp/posts/{id} — live post readback (WordPress context=edit raw
    content). Used by the article detail "live post vs local" pane. */
export interface WpPostReadback {
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
