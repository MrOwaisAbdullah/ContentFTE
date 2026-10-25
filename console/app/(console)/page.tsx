import Link from "next/link";
import {
  ArticleList,
  ArticleStats,
  BriefPeek,
  engine,
  LogsView,
  QueueView,
  SearchConsoleView,
  SiteHealth,
  SiteList,
  SpendSummary,
} from "@/lib/engine";
import { runStageAction } from "@/actions/stages";
import { approveArticleAction } from "@/actions/articles";
import { PendingButton } from "@/lib/interactive";
import { Alert, checkTier, fmtCost, fmtDate } from "@/lib/ui";
import { InteractiveKpiCards, InteractiveStreamStages } from "@/components/interactive-overview-cards";
import { Freshness } from "@/components/freshness";
import { Glyph } from "@/components/glyph";
import { rangeDays, isWithinDays } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: Promise<{ site?: string; range?: string; err?: string }>;
}) {
  const { site = "", range = "30d", err = "" } = await searchParams;
  const days = rangeDays(range);

  let sites: SiteList = { sites: [], count: 0 };
  let queue: QueueView | null = null;
  let brief: BriefPeek | null = null;
  let articles: ArticleList | null = null;
  let spend: SpendSummary | null = null;
  let health: (SiteHealth | null)[] = [];
  let gsc: SearchConsoleView | null = null;
  let stats: ArticleStats | null = null;
  let error = "";

  try {
    sites = await engine<SiteList>("/sites");

    const effectiveSlug = site || (sites.sites.length > 0 ? sites.sites[0].slug : "");
    const siteParam = site ? `?site_slug=${encodeURIComponent(site)}&limit=500` : "?limit=500";
    const spendParam = site ? `?site_slug=${encodeURIComponent(site)}` : "";
    const statsParam = site
      ? `?site_slug=${encodeURIComponent(site)}&since_days=${days}`
      : `?since_days=${days}`;

    [queue, brief, articles, spend, gsc, stats] = await Promise.all([
      effectiveSlug
        ? engine<QueueView>(`/sites/${encodeURIComponent(effectiveSlug)}/queue?limit=10`).catch(() => null)
        : null,
      effectiveSlug
        ? engine<BriefPeek>(`/sites/${encodeURIComponent(effectiveSlug)}/brief`).catch(() => null)
        : null,
      engine<ArticleList>(`/articles${siteParam}`).catch(() => null),
      engine<SpendSummary>(`/spend/summary${spendParam}`).catch(() => null),
      engine<SearchConsoleView>("/search-console").catch(() => null),
      engine<ArticleStats>(`/articles/stats${statsParam}`).catch(() => null),
    ]);

    const healthTargets = site ? sites.sites.filter((s) => s.slug === site) : sites.sites;
    health = await Promise.all(
      healthTargets.map((s) =>
        engine<SiteHealth>(`/sites/${encodeURIComponent(s.slug)}/health`).catch(() => null),
      ),
    );
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  const rawArticles = articles?.articles ?? [];
  const allArticles = site ? rawArticles.filter((a) => a.site_slug === site) : rawArticles;
  const inRangeArticles = allArticles.filter((a) => isWithinDays(a.created_at, days));
  const awaiting = allArticles.filter((a) => a.status === "generated" || a.status === "needs_review");
  const approvedQueue = allArticles.filter((a) => a.status === "approved");
  const publishedArticles = allArticles.filter((a) => a.status === "published");
  const publishedCount = publishedArticles.length;

  const totalSites = sites.sites.length;
  const wpSites = sites.sites.filter((s) => s.site_type === "wordpress").length;
  const customSites = totalSites - wpSites;
  const healthySites = health.filter(
    (h) => h && h.critical.length === 0 && !h.checks.some((c) => checkTier(c) === "warn"),
  ).length;

  const briefableTotal = health.reduce((n, h) => n + (h?.ledger.briefable ?? 0), 0);
  const wtdFmt = spend?.wtd_formatted ?? "—";

  const scoredArticles = allArticles.filter((a) => a.quality != null);
  const avgQuality =
    scoredArticles.length > 0
      ? Math.round(
          scoredArticles.reduce((sum, a) => sum + (a.quality || 0), 0) / scoredArticles.length,
        )
      : null;
  const passRate =
    scoredArticles.length > 0
      ? Math.round(
          (scoredArticles.filter((a) => (a.quality || 0) >= 90).length / scoredArticles.length) * 100,
        )
      : null;

  const generatingCount = allArticles.filter((a) => a.status === "generating").length;
  const mediaCount = allArticles.filter((a) => (a.images && a.images > 0) || a.status === "published").length;
  const realQueueCount = queue?.count ?? briefableTotal;
  const realBriefCount = brief?.keyword ? 1 : 0;

  const connectedGsc = (gsc?.sites ?? []).filter((s) => !site || s.slug === site);
  const gscImpressionsTotal = connectedGsc.reduce((acc, s) => acc + (s.metrics_28d?.impressions ?? 0), 0);
  const gscClicksTotal = connectedGsc.reduce((acc, s) => acc + (s.metrics_28d?.clicks ?? 0), 0);
  const gscConnectedSitesCount = connectedGsc.filter((s) => s.connected === true).length;

  const recentArticles = allArticles.slice(0, 6);
  const autoPublishSites = sites.sites.filter((s) => s.publish_mode === "auto").length;

  const withRange = (r: string) => {
    const qs = new URLSearchParams();
    if (site) qs.set("site", site);
    qs.set("range", r);
    return `/?${qs.toString()}`;
  };

  return (
    <div className="space-y-10">
      <div className="flex flex-col xl:flex-row xl:items-start justify-between gap-6 pb-4 border-b border-outline-variant/20">
        <div className="space-y-2 min-w-0">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <h1 className="text-[28px] lg:text-[34px] font-headline font-bold tracking-tight text-ink">
              {site ? `${site} Overview` : "Fleet Overview"}
            </h1>
            <span className="px-2.5 py-1 rounded-full text-[11px] font-mono bg-surface-container border border-outline-variant/40 text-secondary">
              {sites.sites.length ? `${totalSites} site${totalSites === 1 ? "" : "s"} · ${stats?.total ?? allArticles.length} articles` : "engine offline"}
            </span>
          </div>
          <p className="text-[13px] text-secondary max-w-2xl leading-relaxed">
            {site ? (
              <>
                Operational health and publishing throughput for{" "}
                <strong className="text-ink">{site}</strong>.{" "}
                <Link href="/" className="text-primary-container hover:underline ml-1">View all sites</Link>
              </>
            ) : (
              <>High-level operational health and publishing throughput across{" "}
                <strong className="text-ink">{totalSites} connected tenant site{totalSites === 1 ? "" : "s"}</strong>.
              </>
            )}
          </p>
          {error ? <Alert tone="error">Fleet engine unreachable: {error}</Alert> : null}
          <Freshness at={new Date().toISOString()} ok={sites.sites.length > 0} />
        </div>

        <div className="flex flex-wrap items-center gap-3 xl:justify-end">
          <div className="inline-flex p-1 rounded-lg bg-surface-lowest border border-outline-variant/30 text-[12px] font-mono">
            <Link href={withRange("24h")} className={`px-3 py-1 rounded transition-colors ${range === "24h" ? "bg-surface-container text-ink font-medium shadow-xs" : "text-secondary hover:text-ink"}`}>24h</Link>
            <Link href={withRange("7d")} className={`px-3 py-1 rounded transition-colors ${range === "7d" ? "bg-surface-container text-ink font-medium shadow-xs" : "text-secondary hover:text-ink"}`}>7d</Link>
            <Link href={withRange("30d")} className={`px-3 py-1 rounded transition-colors ${range === "30d" || !range ? "bg-surface-container text-ink font-medium shadow-xs" : "text-secondary hover:text-ink"}`}>30d</Link>
          </div>
          <div className="flex items-center gap-2 px-3.5 py-1.5 rounded-lg bg-surface-container border border-outline-variant/30 text-[12px] font-mono text-ink">
            <span className={`w-2 h-2 rounded-full ${autoPublishSites > 0 ? "bg-tertiary animate-pulse" : "bg-secondary"}`} />
            <span className="font-medium">Auto-publish: {autoPublishSites > 0 ? `${autoPublishSites} of ${totalSites} sites` : "off"}</span>
          </div>
        </div>
      </div>

      <InteractiveKpiCards
        totalSites={totalSites}
        healthySites={healthySites}
        wpSites={wpSites}
        customSites={customSites}
        site={site}
        totalArticles={stats?.total ?? allArticles.length}
        publishedCount={stats?.by_status?.published ?? publishedCount}
        awaitingCount={awaiting.length}
        generatingCount={generatingCount}
        queueCount={realQueueCount}
        briefCount={realBriefCount}
        avgQuality={stats?.avg_quality ?? avgQuality}
        passRate={stats?.quality_pass_rate ?? passRate}
        wtdFmt={wtdFmt}
        gscImpressions={gscImpressionsTotal}
        gscClicks={gscClicksTotal}
        gscConnectedSites={gscConnectedSitesCount}
      />

      <div className="space-y-4">
        <div className="flex items-center justify-between px-1">
          <div className="flex items-center gap-2.5">
            <Glyph name="conversion_path" className="text-primary-container text-[18px]" />
            <h2 className="text-[12px] font-mono uppercase tracking-wider text-secondary font-semibold">
              Autonomous Execution Stream
            </h2>
          </div>
          <span className="text-[12px] font-mono text-secondary">
            {realQueueCount} queued · {realBriefCount} briefable
          </span>
        </div>
        <InteractiveStreamStages
          queueCount={realQueueCount}
          briefCount={realBriefCount}
          awaitingCount={awaiting.length}
          publishedCount={stats?.by_status?.published ?? publishedCount}
          generatingCount={generatingCount}
          mediaCount={mediaCount}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
        <div className="lg:col-span-8 space-y-4">
          <div className="flex items-center justify-between px-1">
            <div className="flex items-center gap-2">
              <Glyph name="history" className="text-primary-container text-[18px]" />
              <h2 className="text-[15px] font-headline font-semibold text-ink">Recent Autonomous Dispatches</h2>
            </div>
            <Link className="text-[12px] font-mono text-primary-container hover:underline flex items-center gap-1" href="/articles">
              <span>View All Pipeline Runs</span>
              <Glyph name="arrow_forward" className="text-[14px]" />
            </Link>
          </div>

          <div className="rounded-xl bg-surface-lowest border border-outline-variant/30 divide-y divide-outline-variant/15 overflow-hidden shadow-xs">
            {recentArticles.length > 0 ? (
              recentArticles.map((art) => {
                const isPublished = art.status === "published";
                const isGenerating = art.status === "generating";
                return (
                  <div key={art.id} className="p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4 hover:bg-surface-container/40 transition-colors">
                    <div className="space-y-1.5 max-w-xl min-w-0">
                      <div className="flex items-center gap-2.5 text-[11px] font-mono">
                        {isPublished ? (
                          <span className="text-tertiary font-medium flex items-center gap-1">
                            <span className="w-1.5 h-1.5 rounded-full bg-tertiary" />
                            Dispatched to CMS
                          </span>
                        ) : isGenerating ? (
                          <span className="text-primary-container font-medium flex items-center gap-1">
                            <span className="w-1.5 h-1.5 rounded-full bg-primary-container animate-pulse" />
                            Synthesizing Draft
                          </span>
                        ) : (
                          <span className="text-secondary font-medium flex items-center gap-1">
                            <span className="w-1.5 h-1.5 rounded-full bg-secondary" />
                            {art.status}
                          </span>
                        )}
                        <span className="text-secondary/40">•</span>
                        <span className="text-secondary truncate">{art.site_slug}</span>
                        <span className="text-secondary/40">•</span>
                        <span className="text-secondary/70">
                          {art.published_at ? fmtDate(art.published_at) : fmtDate(art.created_at)}
                        </span>
                      </div>
                      <Link
                        href={`/articles/${art.id}`}
                        className="text-[14px] font-semibold text-ink hover:text-primary-container transition-colors block truncate"
                      >
                        {art.title || art.slug || `Article #${art.id}`}
                      </Link>
                    </div>

                    <div className="flex items-center gap-5 text-[12px] font-mono text-secondary shrink-0">
                      <div className="text-right">
                        <div className="text-ink font-medium">
                          {art.word_count ? `${art.word_count.toLocaleString()} words` : "—"}
                        </div>
                        <div className="text-secondary/70 text-[11px]">
                          Quality: {art.quality != null ? `${Math.round(art.quality)}/100` : "Not scored"}
                        </div>
                      </div>
                      <Link
                        href={`/articles/${art.id}`}
                        className="p-2 rounded-lg text-secondary hover:text-ink hover:bg-surface-container transition-colors"
                        title="Inspect Run"
                      >
                        <Glyph name="open_in_new" className="text-[18px]" />
                      </Link>
                    </div>
                  </div>
                );
              })
            ) : (
              <div className="p-8 text-center text-secondary font-mono text-[12px]">
                No recent pipeline runs recorded. Trigger a dispatch to begin autonomous flow.
              </div>
            )}
          </div>
        </div>

        <div className="lg:col-span-4 space-y-4">
          <div className="flex items-center justify-between px-1">
            <div className="flex items-center gap-2">
              <Glyph name="shield" className="text-primary-container text-[18px]" />
              <h2 className="text-[15px] font-headline font-semibold text-ink">Attention Needed</h2>
            </div>
            <span className="px-2.5 py-0.5 rounded-full text-[11px] font-mono bg-primary-container/15 text-primary-container border border-primary-container/30">
              {awaiting.length} Items
            </span>
          </div>
          <p className="text-[11px] font-mono text-secondary -mt-2 px-1">
            Articles waiting for an editorial decision before publishing.
          </p>

          {awaiting.length > 0 ? (
            <div className="p-6 rounded-xl bg-surface-lowest border border-outline-variant/30 space-y-4 shadow-xs">
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-mono text-secondary truncate max-w-[140px]">
                    {awaiting[0].site_slug}
                  </span>
                  <span className="text-[11px] font-mono text-primary-container font-medium bg-primary-container/10 px-2 py-0.5 rounded border border-primary-container/20">
                    Quality: {awaiting[0].quality != null ? `${Math.round(awaiting[0].quality)}/100` : "Not scored"}
                  </span>
                </div>
                <h3 className="text-[14px] font-semibold text-ink leading-snug">
                  {awaiting[0].title || awaiting[0].slug}
                </h3>
                <p className="text-[12px] text-secondary leading-relaxed">
                  Requires editorial confirmation before publishing.
                </p>
              </div>

              <div className="pt-2 flex items-center gap-3">
                <form action={approveArticleAction} className="flex-1">
                  <input type="hidden" name="id" value={String(awaiting[0].id)} />
                  <input type="hidden" name="approved" value="1" />
                  <input type="hidden" name="from" value="/" />
                  <PendingButton
                    confirmTitle="Approve Article"
                    confirmMessage={`Approve "${awaiting[0].title || `#${awaiting[0].id}`}"? It will move to the publish queue.`}
                    confirmButtonLabel="Approve"
                    pendingLabel="Approving…"
                    className="w-full h-9 rounded-lg bg-primary-container hover:brightness-110 text-white text-[12px] font-semibold flex items-center justify-center gap-1.5 shadow-xs transition-all"
                    leftIcon={<Glyph name="check_circle" className="text-[15px]" />}
                  >
                    Approve
                  </PendingButton>
                </form>
                <Link
                  href={`/articles/${awaiting[0].id}`}
                  className="px-3.5 h-9 rounded-lg bg-surface-container hover:bg-surface-high text-secondary hover:text-ink border border-outline-variant/30 text-[12px] font-mono flex items-center justify-center transition-colors"
                >
                  Review
                </Link>
              </div>
            </div>
          ) : (
            <div className="p-6 rounded-xl bg-surface-lowest border border-outline-variant/30 space-y-3">
              <div className="flex items-center gap-2 text-tertiary font-mono text-[12px]">
                <Glyph name="verified" className="text-[18px]" />
                <span>Work Queue Clear</span>
              </div>
              <p className="text-[12px] text-secondary leading-relaxed">
                All generated content has passed automated checks with 0 manual escalations pending.
              </p>
            </div>
          )}

          <div className="p-5 rounded-xl bg-surface-lowest border border-outline-variant/30 space-y-3">
            <span className="text-[11px] font-mono uppercase tracking-wider text-secondary block">
              Direct Stage Trigger
            </span>
            <div className="grid grid-cols-2 gap-2">
              <form action={runStageAction}>
                <input type="hidden" name="stage" value="research" />
                <input type="hidden" name="site" value={site} />
                <PendingButton
                  confirmTitle="Run Research Stage"
                  confirmMessage="Run the research stage now? It spends model credits."
                  confirmButtonLabel="Run"
                  confirmVariant="primary"
                  pendingLabel="…"
                  className="w-full py-1.5 px-2 rounded bg-surface-container border border-outline-variant/30 hover:bg-surface-high text-ink text-[11px] font-mono flex items-center justify-center gap-1"
                >
                  <Glyph name="search" className="text-[13px] text-primary-container" />
                  <span>Research</span>
                </PendingButton>
              </form>
              <form action={runStageAction}>
                <input type="hidden" name="stage" value="content" />
                <input type="hidden" name="site" value={site} />
                <PendingButton
                  confirmTitle="Run Content Stage"
                  confirmMessage="Generate content now? It spends LLM/image credits."
                  confirmButtonLabel="Run"
                  confirmVariant="primary"
                  pendingLabel="…"
                  className="w-full py-1.5 px-2 rounded bg-surface-container border border-outline-variant/30 hover:bg-surface-high text-ink text-[11px] font-mono flex items-center justify-center gap-1"
                >
                  <Glyph name="edit_note" className="text-[13px] text-tertiary" />
                  <span>Drafts</span>
                </PendingButton>
              </form>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}