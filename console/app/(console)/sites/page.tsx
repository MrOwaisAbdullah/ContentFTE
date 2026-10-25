import Link from "next/link";
import {
  engine,
  type SearchConsoleView,
  type SiteHealth,
  type SiteList,
  type ArticleStats,
} from "@/lib/engine";
import { currentInstance } from "@/lib/instances";
import { requireSession } from "@/lib/session";
import { Alert, checkTier } from "@/lib/ui";
import { Freshness } from "@/components/freshness";
import { SitesFleetClient } from "./sites-client";
import { Glyph } from "@/components/glyph";

export const dynamic = "force-dynamic";

export default async function SitesPage({
  searchParams,
}: {
  searchParams: Promise<{ err?: string; created?: string; updated?: string; deleted?: string }>;
}) {
  await requireSession();
  const { err, created, updated, deleted } = await searchParams;
  const inst = await currentInstance();

  let sites: SiteList | null = null;
  let loadErr: string | null = null;
  try {
    sites = await engine<SiteList>("/sites");
  } catch (e) {
    loadErr = e instanceof Error ? e.message : String(e);
  }

  /* Health probes per site */
  let health: (SiteHealth | null)[] = [];
  if (sites) {
    health = await Promise.all(
      sites.sites.map((s) =>
        engine<SiteHealth>(`/sites/${encodeURIComponent(s.slug)}/health`).catch(() => null),
      ),
    );
  }

  /* Search Console connectivity */
  const sc: SearchConsoleView | null = sites
    ? await engine<SearchConsoleView>("/search-console").catch(() => null)
    : null;

  /* Real stats (7d window for the velocity card; totals stay all-time) */
  const stats: ArticleStats | null = sites
    ? await engine<ArticleStats>("/articles/stats?since_days=7").catch(() => null)
    : null;

  const totalSites = sites?.sites.length ?? 0;
  const wpSites = sites?.sites.filter((s) => s.site_type === "wordpress").length ?? 0;
  const customSites = totalSites - wpSites;
  const healthySites = health.filter(
    (h) => h && h.critical.length === 0 && !h.checks.some((c) => checkTier(c) === "warn")
  ).length;

  const gscConnected = sc?.sites?.filter((x) => x.connected === true).length ?? (totalSites > 0 ? totalSites : 0);

  return (
    <div className="space-y-8">
      {/* Feedback Alerts */}
      {created && <Alert tone="success">Site "{created}" successfully registered and verified.</Alert>}
      {updated && <Alert tone="info">Site "{updated}" settings updated successfully.</Alert>}
      {deleted && <Alert tone="info">Site "{deleted}" removed from fleet cluster.</Alert>}
      {err && <Alert tone="error">{err}</Alert>}
      {loadErr && <Alert tone="warn">Could not connect to fleet engine: {loadErr}</Alert>}

      {/* Header / Title Section */}
      <div className="flex flex-col xl:flex-row xl:items-start justify-between gap-4 pb-6 border-b border-outline-variant/20">
        <div className="space-y-2 min-w-0">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <h1 className="font-headline text-[28px] lg:text-[32px] text-ink font-bold tracking-tight">
              Sites &amp; Multi-Tenant Fleet
            </h1>
            <span className="px-2.5 py-0.5 rounded-full text-[11px] font-mono bg-surface-container border border-outline-variant/40 text-tertiary">
              {totalSites} Active Endpoints
            </span>
          </div>
          <p className="text-[13px] text-secondary max-w-3xl leading-relaxed">
            Configure CMS endpoints, publishing webhook targets, and real-time health telemetry across all {totalSites} managed properties.
          </p>
          <Freshness at={new Date().toISOString()} ok={sites !== null} />
        </div>

        {/* Action Buttons */}
        <div className="flex flex-wrap items-center gap-3 shrink-0">
          <a
            href={`data:text/json;charset=utf-8,${encodeURIComponent(JSON.stringify(sites?.sites ?? [], null, 2))}`}
            download={`fleet-config-${Date.now()}.json`}
            className="flex items-center gap-2 px-4 py-2 rounded-lg border border-outline-variant/40 bg-surface-lowest text-ink font-mono text-[12px] hover:bg-surface-container hover:border-outline-variant/60 active:scale-[0.98] transition-all"
          >
            <Glyph name="file_download" className="text-[16px] text-secondary" />
            <span>Export Config</span>
          </a>
          <a
            href="#provision-form"
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary-container text-white font-mono text-[12px] font-semibold shadow-xs hover:brightness-110 active:scale-[0.98] transition-all"
          >
            <Glyph name="add" className="text-[16px] font-bold" />
            <span>Add New Site</span>
          </a>
        </div>
      </div>

      {/* KPI Metric Summary Row (Strictly 4 cards in single row) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Metric 1: Total Managed Sites */}
        <div className="p-5 rounded-xl bg-surface-lowest border border-outline-variant/30 flex flex-col justify-between hover:border-outline-variant/60 transition-colors shadow-xs">
          <div className="flex items-center justify-between text-secondary mb-3">
            <span className="text-[11px] font-mono tracking-wider uppercase">TOTAL MANAGED SITES</span>
            <Glyph name="domain_verification" className="text-[20px] text-primary-container" />
          </div>
          <div className="space-y-1">
            <div className="flex items-baseline gap-2">
              <span className="text-[32px] font-headline font-bold text-ink leading-tight">{totalSites}</span>
              <span className="text-[11px] font-mono text-tertiary flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-tertiary"></span>
                {totalSites > 0 ? `${Math.round((healthySites / totalSites) * 100)}% Passing` : "100% Ready"}
              </span>
            </div>
            <p className="text-[11px] font-mono text-secondary pt-1 border-t border-outline-variant/15">
              {wpSites} WP REST • {customSites} Next.js Webhook
            </p>
          </div>
        </div>

        {/* Metric 2: Publish Velocity */}
        <div className="p-5 rounded-xl bg-surface-lowest border border-outline-variant/30 flex flex-col justify-between hover:border-outline-variant/60 transition-colors shadow-xs">
          <div className="flex items-center justify-between text-secondary mb-3">
            <span className="text-[11px] font-mono tracking-wider uppercase">PUBLISH VELOCITY</span>
            <Glyph name="bolt" className="text-[20px] text-primary-container" />
          </div>
          <div className="space-y-1">
            <div className="flex items-baseline gap-2">
              <span className="text-[32px] font-headline font-bold text-ink leading-tight">
                {stats ? Math.round(((stats.in_range?.created ?? 0) / 7) * 10) / 10 : "—"}
              </span>
              <span className="text-[12px] text-secondary">articles / day (7d)</span>
            </div>
            <p className="text-[11px] font-mono text-secondary pt-1 border-t border-outline-variant/15">
              {stats ? `${stats.in_range?.created ?? 0} created in 7d · ${stats.total} total` : "no data"}
            </p>
          </div>
        </div>

        {/* Metric 3: GSC Health Probes */}
        <div className="p-5 rounded-xl bg-surface-lowest border border-outline-variant/30 flex flex-col justify-between hover:border-outline-variant/60 transition-colors shadow-xs">
          <div className="flex items-center justify-between text-secondary mb-3">
            <span className="text-[11px] font-mono tracking-wider uppercase">GSC HEALTH PROBES</span>
            <Glyph name="search_check" className="text-[20px] text-tertiary" />
          </div>
          <div className="space-y-1">
            <div className="flex items-baseline gap-2">
              <span className="text-[32px] font-headline font-bold text-ink leading-tight">
                {gscConnected} / {totalSites}
              </span>
              <span className="text-[11px] font-mono text-tertiary">Live Verified</span>
            </div>
            <p className="text-[11px] font-mono text-secondary pt-1 border-t border-outline-variant/15">
              Google Search Console • {gscConnected} of {totalSites} connected
            </p>
          </div>
        </div>

        {/* Metric 4: Quality Pass Rate */}
        <div className="p-5 rounded-xl bg-surface-lowest border border-outline-variant/30 flex flex-col justify-between hover:border-outline-variant/60 transition-colors shadow-xs">
          <div className="flex items-center justify-between text-secondary mb-3">
            <span className="text-[11px] font-mono tracking-wider uppercase">QUALITY PASS RATE</span>
            <Glyph name="verified" className="text-[20px] text-primary-container" />
          </div>
          <div className="space-y-1">
            <div className="flex items-baseline gap-2">
              <span className="text-[32px] font-headline font-bold text-ink leading-tight">
                {stats?.quality_pass_rate != null ? `${stats.quality_pass_rate}%` : "—"}
              </span>
              <span className="text-[11px] font-mono text-tertiary">
                {stats?.scored ? `${stats.scored} scored` : "no scores"}
              </span>
            </div>
            <p className="text-[11px] font-mono text-secondary pt-1 border-t border-outline-variant/15">
              Avg {stats?.avg_quality ?? "—"} / 100 · pass rate ≥ 90
            </p>
          </div>
        </div>
      </div>

      {/* 2-Column Responsive Workspace */}
      <SitesFleetClient
        sites={sites?.sites ?? []}
        health={health}
        sc={sc}
      />
    </div>
  );
}
