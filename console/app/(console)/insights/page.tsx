import Link from "next/link";
import { engine, ArticleList, LogsView, SiteList, SearchConsoleView, ArticleStats } from "@/lib/engine";
import { Alert, Empty, PageHeader, fmtCost, fmtDate } from "@/lib/ui";
import { InteractiveVelocityChart, VelocityPoint } from "@/components/interactive-velocity-chart";
import { InteractiveQualityMeter } from "@/components/interactive-quality-meter";
import { Freshness } from "@/components/freshness";
import { fmtCompact, isWithinDays, rangeDays } from "@/lib/format";
import { normalizeScores } from "@/lib/scores";
import { Glyph } from "@/components/glyph";
import { ChartNoAxesCombined, Table2 } from "lucide-react";

export const dynamic = "force-dynamic";

const COST_KINDS = ["llm", "image", "data"] as const;
type CostKind = (typeof COST_KINDS)[number];
const KIND_LABEL: Record<CostKind, string> = {
  llm: "LLM Inference",
  image: "Visual Generation",
  data: "Search & Context APIs",
};
const isCostKind = (k: string): k is CostKind => (COST_KINDS as readonly string[]).includes(k);

export default async function InsightsPage({
  searchParams,
}: {
  searchParams: Promise<{ site?: string; range?: string }>;
}) {
  const { site = "", range = "30d" } = await searchParams;
  const days = rangeDays(range);

  const [costsRes, usageRes, artsRes, sitesRes, gscRes, statsRes] = await Promise.allSettled([
    engine<LogsView>("/logs?kind=cost&limit=300"),
    engine<LogsView>("/logs?kind=usage&limit=300"),
    engine<ArticleList>("/articles?limit=500"),
    engine<SiteList>("/sites"),
    engine<SearchConsoleView>("/search-console"),
    engine<ArticleStats>(`/articles/stats?since_days=${days}${site ? `&site_slug=${encodeURIComponent(site)}` : ""}`),
  ]);

  const errors: string[] = [];
  if (costsRes.status === "rejected") errors.push("cost rows");
  if (usageRes.status === "rejected") errors.push("usage rows");
  if (artsRes.status === "rejected") errors.push("article index");
  if (sitesRes.status === "rejected") errors.push("site index");

  const costs = costsRes.status === "fulfilled" ? costsRes.value.costs : [];
  const usage = usageRes.status === "fulfilled" ? usageRes.value.audit : [];
  const articles = artsRes.status === "fulfilled" ? artsRes.value.articles : [];
  const sitesList = sitesRes.status === "fulfilled" ? sitesRes.value.sites : [];
  const gsc = gscRes.status === "fulfilled" ? gscRes.value : null;
  const stats = statsRes.status === "fulfilled" ? statsRes.value : null;

  // Scope costs/usage to the selected site.
  const artById = new Map(articles.map((a) => [a.id, a]));
  const inSite = (articleId: number | null | undefined) =>
    !site || (articleId != null && artById.get(articleId)?.site_slug === site);

  const scopedCosts = costs.filter((c) => inSite(c.article_id));
  const scopedUsage = usage.filter((u) => inSite(u.article_id));

  // Filter by date range (real timestamps on ledger rows).
  const rangeFilteredCosts = scopedCosts.filter((c) => isWithinDays(c.created_at, days));
  const rangeFilteredUsage = scopedUsage.filter((u) => isWithinDays(u.created_at, days));

  const kindSum = new Map<CostKind, { amount: number; rows: number }>();
  let totalSpend = 0;
  for (const c of rangeFilteredCosts) {
    if (!isCostKind(c.kind)) continue;
    const amt = Number(c.amount_usd) || 0;
    const rec = kindSum.get(c.kind) ?? { amount: 0, rows: 0 };
    rec.amount += amt;
    rec.rows += 1;
    kindSum.set(c.kind, rec);
    totalSpend += amt;
  }

  // Per-article rollups (within range).
  type ArtRow = { llm: number; image: number; data: number; total: number };
  const byArticle = new Map<number, ArtRow>();
  for (const c of rangeFilteredCosts) {
    if (!isCostKind(c.kind)) continue;
    const row = byArticle.get(c.article_id) ?? { llm: 0, image: 0, data: 0, total: 0 };
    const amt = Number(c.amount_usd) || 0;
    row[c.kind] += amt;
    row.total += amt;
    byArticle.set(c.article_id, row);
  }

  // Model breakdown from usage rows.
  type ModelRow = { lane: string; calls: number; failed: number };
  const byModel = new Map<string, ModelRow>();
  for (const u of rangeFilteredUsage) {
    const p = u.payload || {};
    const model = String(p.model || p.model_id || "unknown");
    const lane = String(p.lane || (u.action.includes("image") ? "image" : "model"));
    const key = `${lane}:${model}`;
    const rec = byModel.get(key) ?? { lane, calls: 0, failed: 0 };
    rec.calls += 1;
    if (p.status === "failed" || p.ok === false) rec.failed += 1;
    byModel.set(key, rec);
  }
  const modelRows = [...byModel.entries()]
    .map(([key, v]) => ({ model: key.slice(key.indexOf(":") + 1), ...v }))
    .sort((a, b) => b.calls - a.calls);
  const totalCalls = modelRows.reduce((n, r) => n + r.calls, 0);

  // GSC real data.
  const connectedSites = (gsc?.sites ?? []).filter((s) => s.connected === true);
  const scopedGscSites = site
    ? (gsc?.sites ?? []).filter((s) => s.slug === site)
    : connectedSites;
  const gscImpressions = scopedGscSites.reduce((s, x) => s + (x.metrics_28d?.impressions ?? 0), 0);
  const gscClicks = scopedGscSites.reduce((s, x) => s + (x.metrics_28d?.clicks ?? 0), 0);
  const gscPositions = scopedGscSites.filter((x) => x.metrics_28d?.position);
  const gscAvgPos = gscPositions.length
    ? gscPositions.reduce((s, x) => s + (x.metrics_28d?.position ?? 0), 0) / gscPositions.length
    : null;
  const gscAvgCtr = gscPositions.length
    ? gscPositions.reduce((s, x) => s + (x.metrics_28d?.ctr ?? 0), 0) / gscPositions.length
    : null;

  // Top articles (real): by quality desc, then cost.
  const scopedArticles = site ? articles.filter((a) => a.site_slug === site) : articles;
  const topArticles = [...scopedArticles]
    .sort((a, b) => (b.quality ?? -1) - (a.quality ?? -1) || (b.cost_usd ?? 0) - (a.cost_usd ?? 0))
    .slice(0, 10);

  // Per-site rollup (real).
  const perSite = stats?.sites ?? [];
  const displayTopSites = perSite.map((s) => ({
    slug: s.slug,
    name: sitesList.find((x) => x.slug === s.slug)?.name || s.slug,
    articles: s.articles,
    published: s.published,
    quality: s.quality_avg,
    cost: s.words ? null : null,
  }));

  // Quality bands for the meter.
  const qualityBands = (() => {
    const bands: Record<string, number> = { "90–100": 0, "75–89": 0, "<75": 0, "unscored": 0 };
    for (const a of scopedArticles) {
      if (a.quality == null) { bands["unscored"] += 1; continue; }
      if (a.quality >= 90) bands["90–100"] += 1;
      else if (a.quality >= 75) bands["75–89"] += 1;
      else bands["<75"] += 1;
    }
    return Object.entries(bands).map(([label, count]) => ({ label, count }));
  })();

  // Velocity series (real).
  const velocityPoints: VelocityPoint[] = (stats?.published_per_day ?? []).map((p) => ({
    day: p.date.slice(5),
    created: p.created,
  }));

  const fmtNum = (n: number) => {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
    return Math.round(n).toString();
  };

  const withRange = (r: string) => {
    const params = new URLSearchParams();
    params.set("range", r);
    if (site) params.set("site", site);
    return `?${params.toString()}`;
  };

  return (
    <div className="space-y-8">
      {errors.length ? (
        <Alert tone="warn">Telemetry sync partial: {errors.join(", ")}.</Alert>
      ) : null}

      <section className="space-y-4 pb-6 border-b border-line">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-[11px] font-mono text-secondary">
            <span>Fleet Control</span>
            <span className="text-secondary/40">/</span>
            <span className="text-ink font-medium">Telemetry &amp; Search Analytics</span>
          </div>
          <div className="flex flex-wrap items-center gap-2.5 shrink-0">
            <div className="inline-flex p-1 rounded-lg bg-surface-container border border-line text-[11px] font-mono">
              <Link href={withRange("7d")} className={`px-3 py-1 rounded transition-colors ${range === "7d" ? "bg-surface-lowest text-ink font-semibold shadow-xs" : "text-secondary hover:text-ink"}`}>Last 7 Days</Link>
              <Link href={withRange("30d")} className={`px-3 py-1 rounded transition-colors ${range === "30d" || !range ? "bg-surface-lowest text-ink font-semibold shadow-xs border-b-2 border-primary-container" : "text-secondary hover:text-ink"}`}>30 Days</Link>
              <Link href={withRange("90d")} className={`px-3 py-1 rounded transition-colors ${range === "90d" ? "bg-surface-lowest text-ink font-semibold shadow-xs" : "text-secondary hover:text-ink"}`}>90 Days</Link>
              <Link href={withRange("qtd")} className={`px-3 py-1 rounded transition-colors ${range === "qtd" ? "bg-surface-lowest text-ink font-semibold shadow-xs" : "text-secondary hover:text-ink"}`}>Quarter-to-date</Link>
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-[26px] sm:text-[30px] lg:text-[32px] font-headline font-bold text-ink tracking-tight whitespace-nowrap">
            Fleet Insights &amp; Search Telemetry
          </h1>
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 font-mono text-[11px] font-medium whitespace-nowrap">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            GSC: {gsc ? `${connectedSites.length} of ${gsc.sites.length} connected` : "not configured"}
          </span>
        </div>
        <p className="text-[13px] text-secondary max-w-3xl leading-relaxed">
          Cost, quality, and publishing throughput from the engine ledger. Search Console metrics shown for the last 28 days (GSC API window).
        </p>
        <Freshness at={new Date().toISOString()} ok={sitesRes.status === "fulfilled"} />
      </section>

      {/* KPI cards */}
      <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-surface-lowest border border-outline-variant/30 rounded-xl p-5">
          <div className="flex items-center justify-between text-secondary mb-2">
            <span className="text-[11px] font-mono tracking-wider uppercase">Total Organic Impressions</span>
            <Glyph name="visibility" className="text-[18px] text-secondary" />
          </div>
          <div className="text-[32px] font-headline font-bold text-ink font-mono">{connectedSites.length ? fmtNum(gscImpressions) : "—"}</div>
          <div className="text-[11px] font-mono text-secondary mt-1">{connectedSites.length ? "28-day window" : "GSC not connected"}</div>
        </div>
        <div className="bg-surface-lowest border border-outline-variant/30 rounded-xl p-5">
          <div className="flex items-center justify-between text-secondary mb-2">
            <span className="text-[11px] font-mono tracking-wider uppercase">Organic Clicks</span>
            <Glyph name="ads_click" className="text-[18px] text-secondary" />
          </div>
          <div className="text-[32px] font-headline font-bold text-ink font-mono">{connectedSites.length ? fmtNum(gscClicks) : "—"}</div>
          <div className="text-[11px] font-mono text-secondary mt-1">{connectedSites.length ? "28-day window" : "GSC not connected"}</div>
        </div>
        <div className="bg-surface-lowest border border-outline-variant/30 rounded-xl p-5">
          <div className="flex items-center justify-between text-secondary mb-2">
            <span className="text-[11px] font-mono tracking-wider uppercase">Avg Position</span>
            <Glyph name="pin_drop" className="text-[18px] text-secondary" />
          </div>
          <div className="text-[32px] font-headline font-bold text-ink font-mono">
            {gscAvgPos != null ? gscAvgPos.toFixed(1) : "—"}
          </div>
          <div className="text-[11px] font-mono text-secondary mt-1">Avg CTR {gscAvgCtr != null ? `${(gscAvgCtr * 100).toFixed(2)}%` : "—"}</div>
        </div>
        <div className="bg-surface-lowest border border-outline-variant/30 rounded-xl p-5">
          <div className="flex items-center justify-between text-secondary mb-2">
            <span className="text-[11px] font-mono tracking-wider uppercase">Cost per 1k Words</span>
            <Glyph name="payments" className="text-[18px] text-secondary" />
          </div>
          <div className="text-[32px] font-headline font-bold text-primary-container font-mono">
            {stats?.cost?.per_1k_words_usd != null ? `$${stats.cost.per_1k_words_usd.toFixed(4)}` : "—"}
          </div>
          <div className="text-[11px] font-mono text-secondary mt-1">
            {stats?.words_total ? `${fmtNum(stats.words_total)} words · ${fmtCost(stats.cost.total_usd)}` : "no spend recorded"}
          </div>
        </div>
      </section>

      {/* Velocity chart + quality meter */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        <div className="lg:col-span-8">
          <InteractiveVelocityChart points={velocityPoints} connected={connectedSites.length > 0} />
        </div>
        <div className="lg:col-span-4">
          <InteractiveQualityMeter
            scored={stats?.scored ?? 0}
            avgQuality={stats?.avg_quality ?? null}
            passRate={stats?.quality_pass_rate ?? null}
            bands={qualityBands}
          />
        </div>
      </div>

      {/* Top articles table */}
      <div className="bg-surface-lowest border border-outline-variant/30 rounded-xl p-6 shadow-xs">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-[17px] font-headline font-semibold text-ink">Top articles by quality</h3>
            <p className="text-[12px] text-secondary mt-0.5">
              Real article data (title, site, status, quality, cost). GSC per-article metrics are not available from the engine.
            </p>
          </div>
          <span className="text-[11px] font-mono text-secondary px-2.5 py-1 rounded bg-surface-container border border-outline-variant/30">
            Showing {topArticles.length} of {articles.length}
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-outline-variant/30 text-secondary uppercase tracking-wider text-[11px] font-mono">
                <th className="py-2.5 px-3">Title / Slug</th>
                <th className="py-2.5 px-3">Site</th>
                <th className="py-2.5 px-3">Status</th>
                <th className="py-2.5 px-3 text-center">Quality</th>
                <th className="py-2.5 px-3 text-right">Cost</th>
                <th className="py-2.5 px-3 text-right">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant/15 text-[12px]">
              {topArticles.map((row) => (
                <tr key={row.id} className="hover:bg-surface-container/50 transition-colors">
                  <td className="py-3 px-3">
                    <Link href={`/articles/${row.id}`} className="font-medium text-ink hover:text-primary-container transition-colors">
                      {row.title}
                    </Link>
                    <div className="text-[11px] font-mono text-secondary/70 truncate max-w-xs">{row.slug}</div>
                  </td>
                  <td className="py-3 px-3">
                    <span className="px-2 py-0.5 rounded text-[11px] font-mono bg-surface-container border border-outline-variant/30 text-ink">{row.site_slug}</span>
                  </td>
                  <td className="py-3 px-3">{row.status}</td>
                  <td className="py-3 px-3 text-center font-mono">
                    {row.quality != null ? `${Math.round(row.quality)}/100` : "Not scored"}
                  </td>
                  <td className="py-3 px-3 text-right font-mono text-ink">{fmtCost(row.cost_usd)}</td>
                  <td className="py-3 px-3 text-right font-mono text-ink-faint">{fmtDate(row.created_at)}</td>
                </tr>
              ))}
              {topArticles.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-8 text-center text-secondary font-mono text-[12px]">No articles yet.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>

      {/* Tenant sites + spend ledger (stacked beside the tall quality card) */}
      <div id="telemetry-rollups" className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
          <div className="bg-surface-lowest border border-outline-variant/30 rounded-xl p-6 shadow-xs">
            <div className="flex items-start justify-between gap-3 mb-4">
              <div className="min-w-0">
                <h3 className="text-[17px] font-headline font-semibold text-ink">
                  Tenant sites
                </h3>
                <p className="text-[12px] text-secondary mt-0.5">
                  {site ? `Per-site rollup scoped to ${site}` : "Articles, quality, and GSC per site"}
                </p>
              </div>
              <Link href="/sites" className="shrink-0 text-[11px] font-mono text-primary-container hover:underline font-semibold">Inspect all →</Link>
            </div>
            <div className="space-y-2">
              {displayTopSites.map((si) => {
                const gscSite = (gsc?.sites ?? []).find((x) => x.slug === si.slug);
                return (
                  <div key={si.slug} className="p-3 rounded-lg bg-surface-container/40 border border-outline-variant/20">
                    <div className="text-[12px] font-mono text-ink truncate">{si.name}</div>
                    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] font-mono text-secondary">
                      <span>{si.articles} articles · {si.published} published</span>
                      <span>avg quality: {si.quality ?? "—"}</span>
                      <span className={gscSite?.metrics_28d ? "" : "text-secondary/70"}>
                        {gscSite?.metrics_28d
                          ? `${fmtNum(gscSite.metrics_28d.impressions)} impr · ${fmtNum(gscSite.metrics_28d.clicks)} clicks`
                          : "GSC not connected"}
                      </span>
                    </div>
                  </div>
                );
              })}
              {displayTopSites.length === 0 ? (
                <p className="text-[12px] text-secondary">No sites.</p>
              ) : null}
            </div>
          </div>

          {/* Spend ledger */}
          <div className="p-6 rounded-xl bg-surface-lowest border border-outline-variant/30 shadow-xs">
            <div className="flex items-start justify-between gap-3 mb-3">
              <div className="min-w-0">
                <h3 className="text-[15px] font-headline font-semibold text-ink">Engine Spend Ledger</h3>
                <p className="text-[12px] text-secondary mt-0.5">Ledger rows in the selected range</p>
              </div>
              <span className="shrink-0 text-[11px] font-mono text-secondary px-2.5 py-0.5 rounded bg-surface-container border border-outline-variant/30">
                {rangeFilteredCosts.length} rows
              </span>
            </div>
            <div className="grid gap-2">
              {COST_KINDS.map((k) => {
                const rec = kindSum.get(k);
                const amt = rec?.amount ?? 0;
                const pct = totalSpend > 0 ? (amt / totalSpend) * 100 : 0;
                return (
                  <div key={k} className="flex items-center justify-between text-[12px] font-mono">
                    <span className="text-secondary">{KIND_LABEL[k]}</span>
                    <span className="text-ink">{fmtCost(amt)} <span className="text-secondary/60">({pct.toFixed(0)}%)</span></span>
                  </div>
                );
              })}
              <div className="flex items-center justify-between text-[12px] font-mono pt-2 border-t border-line">
                <span className="text-ink font-semibold">Total</span>
                <span className="text-gold font-semibold">{fmtCost(totalSpend)}</span>
              </div>
            </div>
            {modelRows.length > 0 ? (
              <div className="mt-4 overflow-x-auto">
                <table className="w-full text-left border-collapse text-[11px] font-mono">
                  <thead>
                    <tr className="border-b border-outline-variant/30 text-secondary uppercase tracking-wider">
                      <th className="py-2 px-2">Model / Lane</th>
                      <th className="py-2 px-2 text-right">Calls</th>
                      <th className="py-2 px-2 text-right">Failed</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-outline-variant/15">
                    {modelRows.map((r) => (
                      <tr key={`${r.lane}:${r.model}`}>
                        <td className="py-2 px-2 text-ink">{r.model} <span className="text-secondary/60">({r.lane})</span></td>
                        <td className="py-2 px-2 text-right text-ink">{r.calls}</td>
                        <td className={`py-2 px-2 text-right ${r.failed > 0 ? "text-rose-400 font-bold" : "text-secondary"}`}>{r.failed}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="mt-3 text-[11px] text-secondary">No usage rows in this range.</p>
            )}
          </div>
      </div>

      <footer className="mt-8 p-4 rounded-xl bg-surface-lowest border border-outline-variant/30 flex flex-col md:flex-row items-center justify-between gap-3 text-[11px] font-mono text-secondary shadow-xs">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-tertiary" />
          <span>{stats?.total ?? 0} articles · {stats?.scored ?? 0} scored · {stats?.quality_pass_rate ?? "—"}% pass rate</span>
        </div>
        <div className="text-secondary/70">Sync epoch: {new Date().toISOString()}</div>
      </footer>
    </div>
  );
}