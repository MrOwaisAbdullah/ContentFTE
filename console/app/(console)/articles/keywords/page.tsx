import Link from "next/link";
import { engine, type QueueView, type SiteList } from "@/lib/engine";
import { createArticleAction, deleteKeywordAction, prioritizeKeywordAction } from "@/actions/articles";
import { Alert, fmtDate, fmtScore } from "@/lib/ui";
import { PendingButton } from "@/lib/interactive";
import { SiteFilterSelect } from "@/components/site-filter";
import { Glyph } from "@/components/glyph";

export const dynamic = "force-dynamic";

export default async function KeywordsPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string; site?: string; err?: string; deleted?: string; created?: string }>;
}) {
  const { status = "", site = "", err = "", deleted = "", created = "" } = await searchParams;
  let slug = site;
  let error = "";
  let sites: SiteList = { sites: [], count: 0 };
  let queue: QueueView | null = null;

  try {
    sites = await engine<SiteList>("/sites");
    if (!slug && sites.sites.length === 1) slug = sites.sites[0].slug;
    if (slug) {
      const qs = new URLSearchParams({ limit: "200" });
      if (status) qs.set("status", status);
      queue = await engine<QueueView>(`/sites/${encodeURIComponent(slug)}/queue?${qs}`);
    }
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  const rows = queue?.queue ?? [];
  const totalKeywords = queue?.count ?? rows.length;
  const statuses = queue ? Object.keys(queue.counts) : [];

  // Summary statistics
  const totalVolume = rows.reduce((acc, r) => acc + (r.volume || 0), 0);
  const avgKd = rows.length > 0 ? Math.round(rows.reduce((acc, r) => acc + (r.difficulty || 0), 0) / rows.length) : null;
  const convertedCount = rows.filter((r) => r.status === "briefed" || r.status === "generated" || r.status === "published").length;
  const conversionRate = rows.length > 0 ? ((convertedCount / rows.length) * 100).toFixed(1) : "—";

  return (
    <div className="space-y-8 w-full max-w-full min-w-0">
      {/* Feedback Alerts */}
      {created && <Alert tone="success">Keyword added to autonomous backlog queue.</Alert>}
      {deleted && <Alert tone="info">Keyword entry #{deleted} removed from ledger.</Alert>}
      {err && <Alert tone="error">{err}</Alert>}
      {error && <Alert tone="error">Engine unreachable: {error}</Alert>}

      {!slug && sites.sites.length > 1 ? (
        <div className="rounded-xl border border-dashed border-line bg-card/40 p-8 space-y-4">
          <h2 className="text-[15px] font-headline font-semibold text-ink">Choose a site to view its keyword ledger</h2>
          <p className="text-[12px] text-secondary">
            The keyword ledger is per-site. Pick a site to continue.
          </p>
          <div className="flex flex-wrap gap-2">
            {sites.sites.map((s) => (
              <Link key={s.slug} href={`/articles/keywords?site=${encodeURIComponent(s.slug)}`} className="px-3 py-1.5 rounded-lg border border-line bg-surface-container text-ink text-[12px] font-mono hover:border-primary-container hover:text-primary-container transition-colors">
                {s.name || s.slug}
              </Link>
            ))}
          </div>
        </div>
      ) : null}

      {/* HEADER / TITLE SECTION */}
      <section className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-outline-variant/20">
        <div>
          <div className="flex items-center gap-2 mb-1.5">
            <span className="text-[11px] font-mono uppercase tracking-wider text-primary-container font-semibold">
              ENGINE TELEMETRY / INGESTION
            </span>
            <span className="text-secondary text-xs">•</span>
            <span className="text-[11px] font-mono text-tertiary flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-tertiary animate-pulse" />
              Live Sync: Active
            </span>
          </div>
          <h1 className="text-[28px] lg:text-[32px] font-headline font-bold text-ink tracking-tight">
            Keyword Ledger &amp; Intent Matrix
          </h1>
          <p className="text-[13px] text-secondary mt-1 max-w-3xl leading-relaxed">
            Target keyword ingestion, search intent scoring, difficulty benchmarks, and autonomous pipeline status across tenant properties.
          </p>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-3 self-start md:self-auto shrink-0">
          <a
            href={`data:text/json;charset=utf-8,${encodeURIComponent(JSON.stringify(rows, null, 2))}`}
            download={`keywords-ledger-${slug || "fleet"}-${Date.now()}.json`}
            className="bg-surface-lowest hover:bg-surface-container text-ink border border-outline-variant/40 text-[12px] font-mono font-medium px-4 py-2 rounded-lg transition-all flex items-center gap-2 active:scale-[0.98]"
          >
            <Glyph name="file_download" className="text-[16px] text-secondary" />
            <span>Export Sheet</span>
          </a>
          <a
            href="#ingest-form"
            className="bg-primary-container hover:brightness-110 text-white font-mono text-[12px] font-semibold px-4 py-2 rounded-lg transition-all flex items-center gap-2 active:scale-[0.98] shadow-xs"
          >
            <Glyph name="add_circle" className="text-[16px] font-bold" />
            <span>Ingest Keywords</span>
          </a>
        </div>
      </section>

      {slug ? (
        <div className="flex items-center gap-2 text-[12px] font-mono text-secondary">
          <span className="px-2 py-0.5 rounded bg-primary-container/10 text-primary-container border border-primary-container/20">Scope: {slug}</span>
          <span>·</span>
          <Link href="/articles/keywords" className="text-accent hover:underline">change site</Link>
        </div>
      ) : null}

      {/* KPI METRIC SUMMARY ROW (Strictly 4 cards in single row) */}
      <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        {/* Metric 1: Tracked Keywords */}
        <div className="bg-surface-lowest border border-outline-variant/30 rounded-xl p-6 relative overflow-hidden transition-all hover:border-outline-variant/60 group shadow-xs">
          <div className="flex items-start justify-between">
            <span className="text-[11px] font-mono text-secondary tracking-wider uppercase">TRACKED KEYWORDS</span>
            <span className="p-1.5 rounded-lg bg-surface-container text-secondary group-hover:text-primary-container transition-colors">
              <Glyph name="key" className="text-[18px]" />
            </span>
          </div>
          <div className="mt-4 flex items-baseline gap-2">
            <span className="text-[32px] font-headline font-bold text-ink tracking-tight font-mono">
              {totalKeywords}
            </span>

          </div>
          <p className="text-[12px] text-secondary mt-2">Across {sites.sites.length} tenant site{sites.sites.length === 1 ? "" : "s"}</p>
          <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-outline-variant/20 group-hover:bg-primary-container transition-colors" />
        </div>

        {/* Metric 2: Avg Difficulty (KD) */}
        <div className="bg-surface-lowest border border-outline-variant/30 rounded-xl p-6 relative overflow-hidden transition-all hover:border-outline-variant/60 group shadow-xs">
          <div className="flex items-start justify-between">
            <span className="text-[11px] font-mono text-secondary tracking-wider uppercase">AVG DIFFICULTY (KD)</span>
            <span className="p-1.5 rounded-lg bg-surface-container text-secondary group-hover:text-primary-container transition-colors">
              <Glyph name="speed" className="text-[18px]" />
            </span>
          </div>
          <div className="mt-4 flex items-baseline gap-2">
            <span className="text-[32px] font-headline font-bold text-ink tracking-tight font-mono">
              {avgKd != null ? avgKd : "—"}{avgKd != null ? <span className="text-secondary text-[16px] font-normal"> / 100</span> : ""}
            </span>
          </div>
          <p className="text-[12px] text-secondary mt-2">Low-to-Medium SERP competition target</p>
          <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-outline-variant/20 group-hover:bg-tertiary transition-colors" />
        </div>

        {/* Metric 3: Total Search Volume */}
        <div className="bg-surface-lowest border border-outline-variant/30 rounded-xl p-6 relative overflow-hidden transition-all hover:border-outline-variant/60 group shadow-xs">
          <div className="flex items-start justify-between">
            <span className="text-[11px] font-mono text-secondary tracking-wider uppercase">TOTAL SEARCH VOLUME</span>
            <span className="p-1.5 rounded-lg bg-surface-container text-secondary group-hover:text-primary-container transition-colors">
              <Glyph name="bar_chart" className="text-[18px]" />
            </span>
          </div>
          <div className="mt-4 flex items-baseline gap-2">
            <span className="text-[32px] font-headline font-bold text-ink tracking-tight font-mono">
              {totalVolume > 0 ? `${Math.round(totalVolume / 1000)}k` : "—"}
            </span>
            <span className="text-[11px] font-mono text-secondary bg-surface-container px-1.5 py-0.5 rounded">
              Mo. Target
            </span>
          </div>
          <p className="text-[12px] text-secondary mt-2">Est. monthly addressable queries</p>
          <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-outline-variant/20 group-hover:bg-primary-container transition-colors" />
        </div>

        {/* Metric 4: In-Pipeline Conversion */}
        <div className="bg-surface-lowest border border-outline-variant/30 rounded-xl p-6 relative overflow-hidden transition-all hover:border-outline-variant/60 group shadow-xs">
          <div className="flex items-start justify-between">
            <span className="text-[11px] font-mono text-secondary tracking-wider uppercase">IN-PIPELINE CONVERSION</span>
            <span className="p-1.5 rounded-lg bg-surface-container text-secondary group-hover:text-primary-container transition-colors">
              <Glyph name="cached" className="text-[18px]" />
            </span>
          </div>
          <div className="mt-4 flex items-baseline gap-2">
            <span className="text-[32px] font-headline font-bold text-ink tracking-tight font-mono">
              {convertedCount}
            </span>
            <span className="text-[11px] font-mono text-primary-container bg-primary-container/10 px-1.5 py-0.5 rounded font-bold">
              {conversionRate === "—" ? "—" : `${conversionRate}% rate`}
            </span>
          </div>
          <p className="text-[12px] text-secondary mt-2">Converted to active Briefs &amp; Articles</p>
          <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-outline-variant/20 group-hover:bg-primary-container transition-colors" />
        </div>
      </section>

      {/* QUICK-ADD KEYWORD CARD */}
      <section className="bg-surface-lowest border border-outline-variant/30 rounded-xl p-6 space-y-4 shadow-xs">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Glyph name="input" className="text-primary-container text-[20px]" />
            <h2 className="text-[15px] font-headline font-semibold text-ink">
              Quick Ingest to Autonomous Backlog
            </h2>
          </div>
          <span className="text-[11px] font-mono text-secondary">
            Keyword difficulty comes from the research stage (engine-backed).
          </span>
        </div>

        <form id="ingest-form" action={createArticleAction} className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-12 gap-4 items-end">
            {/* Target Keyword Input */}
            <div className="md:col-span-5 space-y-1.5">
              <label className="block text-[11px] font-mono uppercase tracking-wider text-secondary">
                Target Keyword / Canonical Query
              </label>
              <div className="relative">
                <input
                  name="keyword"
                  required
                  type="text"
                  placeholder="e.g. Next.js 15 Partial Prerendering or YouTube Video Title"
                  className="w-full bg-surface-container border border-outline-variant/40 rounded px-3 py-2 text-[13px] font-mono text-ink focus:outline-none focus:border-primary-container focus:ring-1 focus:ring-primary-container transition-all"
                />
              </div>
            </div>

            {/* Target Site Selector Dropdown */}
            <div className="md:col-span-3 space-y-1.5">
              <label className="block text-[11px] font-mono uppercase tracking-wider text-secondary">
                Target Site Tenant
              </label>
              <div className="relative">
                <select
                  name="site"
                  defaultValue={slug}
                  className="w-full bg-surface-container border border-outline-variant/40 rounded px-3 py-2 text-[13px] text-ink focus:outline-none focus:border-primary-container focus:ring-1 focus:ring-primary-container appearance-none pr-8 cursor-pointer"
                >
                  {sites.sites.map((s) => (
                    <option key={s.slug} value={s.slug}>
                      {s.name || s.slug}
                    </option>
                  ))}
                </select>
                <Glyph name="expand_more" className="absolute right-2.5 top-1/2 -translate-y-1/2 text-secondary pointer-events-none text-[18px]" />
              </div>
            </div>

            {/* Working Title / Angle */}
            <div className="md:col-span-2 space-y-1.5">
              <label className="block text-[11px] font-mono uppercase tracking-wider text-secondary">
                Angle / Headline
              </label>
              <input
                name="title"
                type="text"
                placeholder="Optional working title"
                className="w-full bg-surface-container border border-outline-variant/40 rounded px-3 py-2 text-[13px] text-ink focus:outline-none focus:border-primary-container focus:ring-1 focus:ring-primary-container transition-all"
              />
            </div>

            {/* Submit Button */}
            <div className="md:col-span-2">
              <PendingButton
                pendingLabel="Ingesting…"
                className="w-full bg-primary-container hover:brightness-110 text-white font-mono text-[12px] font-bold py-2 px-4 rounded border border-white/10 transition-all flex items-center justify-center gap-1.5 active:scale-[0.98] shadow-xs cursor-pointer"
                leftIcon={<Glyph name="add" className="text-[16px]" />}
              >
                + Ingest
              </PendingButton>
            </div>
          </div>

          {/* Collapsible / Optional Video Transcript Input */}
          <details className="group border border-outline-variant/30 rounded-lg p-3 bg-surface-container/30">
            <summary className="text-[12px] font-mono text-secondary hover:text-ink cursor-pointer flex items-center justify-between select-none">
              <span className="flex items-center gap-2">
                <Glyph name="subtitles" className="text-[16px] text-primary-container" />
                <span>Attach YouTube / Audio Transcript (Optional)</span>
              </span>
              <span className="text-[11px] text-secondary group-open:rotate-180 transition-transform">▼</span>
            </summary>
            <div className="pt-3 space-y-2">
              <p className="text-[11px] text-secondary">
                Paste the full video transcript text below. The brief and drafting agents will use this as direct ground truth.
              </p>
              <textarea
                name="transcript"
                rows={4}
                placeholder="Paste raw video transcript or speech-to-text dump here..."
                className="w-full bg-surface-container border border-outline-variant/40 rounded px-3 py-2 text-[12px] font-mono text-ink focus:outline-none focus:border-primary-container focus:ring-1 focus:ring-primary-container transition-all"
              />
            </div>
          </details>

          {/* Instant Auto-Run Toggle */}
          <div className="flex items-center justify-between pt-1 border-t border-outline-variant/20">
            <label className="flex items-center gap-2.5 cursor-pointer select-none">
              <input
                type="checkbox"
                name="instant"
                value="1"
                defaultChecked={true}
                className="w-4 h-4 rounded border-outline-variant/60 text-primary-container focus:ring-primary-container cursor-pointer accent-primary-container"
              />
              <div className="flex flex-col">
                <span className="text-[12px] font-semibold text-ink flex items-center gap-1.5">
                  <Glyph name="bolt" className="text-amber-400 text-[15px]" />
                  Instant Pipeline Run (Autonomous Auto-Draft)
                </span>
                <span className="text-[11px] text-secondary">
                  Immediately generate brief, write draft, and stage images in background. Ready for 1-click publish approval.
                </span>
              </div>
            </label>
          </div>
        </form>
      </section>

      {/* KEYWORD LEDGER TABLE & STATUS FILTER TABS */}
      <section className="bg-surface-lowest border border-outline-variant/30 rounded-xl overflow-hidden shadow-xs space-y-0">
        {/* Filter Tabs & Site Switcher Header */}
        <div className="p-6 border-b border-outline-variant/20 space-y-4">
          <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
            {/* Filter Tabs */}
            <div className="flex items-center gap-1 overflow-x-auto pb-1 lg:pb-0">
              <Link
                href={`/articles/keywords?site=${encodeURIComponent(slug)}`}
                className={`px-3.5 py-1.5 rounded text-[12px] font-mono transition-colors whitespace-nowrap ${
                  !status
                    ? "bg-surface-container text-ink font-semibold border-b-2 border-primary-container"
                    : "text-secondary hover:text-ink hover:bg-surface-container/60"
                }`}
              >
                All Keywords ({totalKeywords})
              </Link>
              {statuses.map((st) => (
                <Link
                  key={st}
                  href={`/articles/keywords?site=${encodeURIComponent(slug)}&status=${encodeURIComponent(st)}`}
                  className={`px-3.5 py-1.5 rounded text-[12px] font-mono transition-colors whitespace-nowrap ${
                    status === st
                      ? "bg-surface-container text-ink font-semibold border-b-2 border-primary-container"
                      : "text-secondary hover:text-ink hover:bg-surface-container/60"
                  }`}
                >
                  <span className="capitalize">{st}</span> ({queue?.counts[st] ?? 0})
                </Link>
              ))}
            </div>

            {/* Target Site Switcher */}
            {sites.sites.length > 1 && (
              <SiteFilterSelect
                sites={sites.sites}
                current={slug}
                basePath="/articles/keywords"
              />
            )}
          </div>
        </div>

        {/* Table Container */}
        <div className="overflow-x-auto w-full max-w-full">
          <table className="w-full min-w-[700px] text-left border-collapse">
            <thead>
              <tr className="border-b border-outline-variant/30 text-secondary text-[11px] font-mono uppercase tracking-wider">
                <th className="py-3 px-4">KEYWORD / QUERY</th>
                <th className="py-3 px-3">TENANT SITE</th>
                <th className="py-3 px-3 text-right">VOL / MO</th>
                <th className="py-3 px-4">KD</th>
                <th className="py-3 px-3">INTENT</th>
                <th className="py-3 px-3">STATUS</th>
                <th className="py-3 px-3 text-right">SCORE</th>
                <th className="py-3 px-4 text-right">ACTIONS</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant/15 text-[12px]">
              {rows.length > 0 ? (
                rows.map((row) => {
                  const kd = row.difficulty || null;
                  const kdColor = kd == null ? "bg-surface-container" : kd < 35 ? "bg-tertiary" : kd < 60 ? "bg-amber-500" : "bg-danger";

                  return (
                    <tr key={row.id} className="hover:bg-surface-container/50 transition-colors group">
                      {/* Keyword */}
                      <td className="py-3.5 px-4">
                        <div className="flex items-center gap-2">
                          <span className="w-1.5 h-1.5 rounded-full bg-primary-container shrink-0" />
                          <div className="flex flex-col min-w-0">
                            <span className="font-mono text-[12px] font-semibold text-ink group-hover:text-primary-container transition-colors truncate">
                              {row.keyword}
                            </span>
                            {row.subject && (
                              <span className="text-[11px] text-secondary truncate max-w-md">
                                {row.subject}
                              </span>
                            )}
                          </div>
                        </div>
                      </td>

                      {/* Site */}
                      <td className="py-3.5 px-3">
                        <span className="font-mono text-[11px] text-secondary">
                          {slug}
                        </span>
                      </td>

                      {/* Volume */}
                      <td className="py-3.5 px-3 text-right font-mono text-[11px] text-ink font-medium">
                        {row.volume ? row.volume.toLocaleString() : "—"}
                      </td>

                      {/* KD (Difficulty) */}
                      <td className="py-3.5 px-4">
                        <div className="flex items-center gap-2">
                          <div className="w-16 h-1.5 rounded-full bg-surface-container overflow-hidden">
                            <div className={`h-full ${kdColor}`} style={{ width: kd != null ? `${kd}%` : "0%" }} />
                          </div>
                          <span className="font-mono text-[11px] text-secondary">{kd != null ? kd : "—"}</span>
                        </div>
                      </td>

                      {/* Intent */}
                      <td className="py-3.5 px-3">
                        <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-mono bg-surface-container border border-outline-variant/30 text-secondary uppercase">
                          {row.intent || "Informational"}
                        </span>
                      </td>

                      {/* Status */}
                      <td className="py-3.5 px-3">
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-mono bg-primary-container/15 text-primary-container border border-primary-container/30 capitalize">
                          {row.status}
                        </span>
                      </td>

                      {/* Priority Score */}
                      <td className="py-3.5 px-3 text-right font-mono text-[11px] text-tertiary font-bold">
                        {row.priority_score ? row.priority_score.toFixed(1) : "—"}
                      </td>

                      {/* Actions */}
                      <td className="py-3.5 px-4 text-right">
                        <div className="flex items-center justify-end gap-1 opacity-80 group-hover:opacity-100 transition-opacity">
                          <Link
                            href={`/articles/research?site=${encodeURIComponent(slug)}`}
                            className="p-1 text-secondary hover:text-ink rounded hover:bg-surface-container"
                            title="Inspect in Research"
                          >
                            <Glyph name="visibility" className="text-[16px]" />
                          </Link>
                          <form action={prioritizeKeywordAction} className="inline-block">
                            <input type="hidden" name="id" value={String(row.id)} />
                            <input type="hidden" name="site" value={slug} />
                            <PendingButton
                              pendingLabel="…"
                              title={`Prioritize "${row.keyword}" (boost to top of queue)`}
                              aria-label={`Prioritize ${row.keyword}`}
                              className="p-1 text-secondary hover:text-primary-container rounded hover:bg-surface-container"
                              leftIcon={<Glyph name="keyboard_double_arrow_up" className="text-[16px]" />}
                            >
                              <span className="sr-only">Prioritize</span>
                            </PendingButton>
                          </form>
                          <form action={deleteKeywordAction} className="inline-block">
                            <input type="hidden" name="id" value={String(row.id)} />
                            <input type="hidden" name="site" value={slug} />
                            <PendingButton
                              confirmMessage={`Delete keyword "${row.keyword}" from this site's ledger?`}
                              pendingLabel="…"
                              title={`Delete ${row.keyword}`}
                              aria-label={`Delete ${row.keyword}`}
                              className="p-1 text-secondary hover:text-danger rounded hover:bg-surface-container"
                              leftIcon={<Glyph name="delete" className="text-[16px]" />}
                            >
                              <span className="sr-only">Delete</span>
                            </PendingButton>
                          </form>
                        </div>
                      </td>
                    </tr>
                  );
                })
              ) : (
                <tr>
                  <td colSpan={8} className="py-12 text-center text-secondary font-mono text-[12px]">
                    No keywords in this view. Ingest keywords using the form above to populate the ledger.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-outline-variant/20 flex items-center justify-between text-[11px] font-mono text-secondary">
          <span>Showing {rows.length} of {totalKeywords} keywords in ledger</span>
          <span>Target site: {slug}</span>
        </div>
      </section>
    </div>
  );
}
