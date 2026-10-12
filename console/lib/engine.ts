import "server-only";
import { currentInstance } from "./instances";

export class EngineError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** Engine call against the currently selected instance (cookie-switched). */
export async function engine<T = unknown>(
  path: string,
  init?: RequestInit & { json?: unknown },
): Promise<T> {
  const { json, headers, ...rest } = init ?? {};
  const inst = await currentInstance();
  const res = await fetch(`${inst.baseUrl}/sdk/v1${path}`, {
    ...rest,
    cache: "no-store",
    headers: {
      ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(inst.apiKey ? { "X-Site-Key": inst.apiKey } : {}),
      ...(headers as Record<string, string> | undefined),
    },
    body: json !== undefined ? JSON.stringify(json) : (rest.body as BodyInit | undefined),
  });
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
}

export interface SiteList {
  sites: SiteInfo[];
  count: number;
}

/** GET /sites/{slug}/health — ledger + WP config + live probes (spec §5.6). */
export interface SiteHealth {
  site: string;
  ok: boolean;
  ledger: { briefable: number; published: number };
  wp_configured: boolean;
  base_url: string;
  checks: string[];
  critical: string[];
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
  summary?: string;
}

export interface ArticleList {
  articles: ArticleListItem[];
  count: number;
  total: number;
  limit: number;
  offset: number;
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
}
