"use client";

import { useState } from "react";
import Link from "next/link";
import { createSiteAction, deleteSiteAction } from "@/actions/instances";
import { PendingButton } from "@/lib/interactive";
import type { SearchConsoleView, SiteHealth, SiteList } from "@/lib/engine";
import { Glyph } from "@/components/glyph";

type SiteItem = SiteList["sites"][number];

export function SitesFleetClient({
  sites,
  health,
  sc,
}: {
  sites: SiteItem[];
  health: (SiteHealth | null)[];
  sc: SearchConsoleView | null;
}) {
  const [filter, setFilter] = useState<"all" | "wp" | "custom" | "auto" | "draft">("all");
  const [testProbeResult, setTestProbeResult] = useState<string | null>(null);

  const wpCount = sites.filter((s) => s.site_type === "wordpress").length;
  const customCount = sites.filter((s) => s.site_type !== "wordpress").length;
  const autoCount = sites.filter((s) => s.publish_mode === "auto").length;
  const draftCount = sites.filter((s) => s.publish_mode !== "auto").length;

  const filteredSites = sites.filter((s) => {
    if (filter === "wp") return s.site_type === "wordpress";
    if (filter === "custom") return s.site_type !== "wordpress";
    if (filter === "auto") return s.publish_mode === "auto";
    if (filter === "draft") return s.publish_mode !== "auto";
    return true;
  });

  const handleExportConfig = () => {
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(sites, null, 2));
    const downloadAnchor = document.createElement("a");
    downloadAnchor.setAttribute("href", dataStr);
    downloadAnchor.setAttribute("download", `contentfte-fleet-config-${Date.now()}.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  };

  return (
    <div className="space-y-8">
      {/* Table & Form 2-Column Responsive Workspace */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
        {/* Left Column: Connected Fleet Endpoints Table */}
        <div className="lg:col-span-7 xl:col-span-8 space-y-4">
          <div className="p-6 rounded-xl bg-surface-lowest border border-outline-variant/30 space-y-5 shadow-xs">
            {/* Table Header & Filter Pills */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-outline-variant/20">
              <div>
                <h2 className="font-headline text-[15px] text-ink font-semibold flex items-center gap-2">
                  <span>Connected Fleet Endpoints</span>
                  <span className="w-2 h-2 rounded-full bg-tertiary shadow-[0_0_8px_#4edea3]"></span>
                </h2>
                <p className="text-[12px] text-secondary">
                  Active edge connections, ingestion schemas, and latency
                </p>
              </div>

              {/* Filter Pills */}
              <div className="flex flex-wrap items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => setFilter("all")}
                  className={`px-2.5 py-1 rounded text-[11px] font-mono transition-all ${
                    filter === "all"
                      ? "bg-primary-container text-white font-semibold shadow-xs"
                      : "bg-surface-container text-secondary hover:text-ink border border-outline-variant/20"
                  }`}
                >
                  All ({sites.length})
                </button>
                <button
                  type="button"
                  onClick={() => setFilter("wp")}
                  className={`px-2.5 py-1 rounded text-[11px] font-mono transition-all ${
                    filter === "wp"
                      ? "bg-primary-container text-white font-semibold shadow-xs"
                      : "bg-surface-container text-secondary hover:text-ink border border-outline-variant/20"
                  }`}
                >
                  WordPress ({wpCount})
                </button>
                <button
                  type="button"
                  onClick={() => setFilter("custom")}
                  className={`px-2.5 py-1 rounded text-[11px] font-mono transition-all ${
                    filter === "custom"
                      ? "bg-primary-container text-white font-semibold shadow-xs"
                      : "bg-surface-container text-secondary hover:text-ink border border-outline-variant/20"
                  }`}
                >
                  Custom ({customCount})
                </button>
                <button
                  type="button"
                  onClick={() => setFilter("auto")}
                  className={`px-2.5 py-1 rounded text-[11px] font-mono transition-all ${
                    filter === "auto"
                      ? "bg-primary-container text-white font-semibold shadow-xs"
                      : "bg-surface-container text-secondary hover:text-ink border border-outline-variant/20"
                  }`}
                >
                  Auto ({autoCount})
                </button>
                <button
                  type="button"
                  onClick={() => setFilter("draft")}
                  className={`px-2.5 py-1 rounded text-[11px] font-mono transition-all ${
                    filter === "draft"
                      ? "bg-primary-container text-white font-semibold shadow-xs"
                      : "bg-surface-container text-secondary hover:text-ink border border-outline-variant/20"
                  }`}
                >
                  Draft ({draftCount})
                </button>
              </div>
            </div>

            {/* Table Container */}
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse min-w-[620px]">
                <thead>
                  <tr className="border-b border-outline-variant/30 text-secondary text-[11px] font-mono uppercase tracking-wider">
                    <th className="py-3 px-3 whitespace-nowrap">SLUG / SITE</th>
                    <th className="py-3 px-3 whitespace-nowrap">ARCHITECTURE</th>
                    <th className="py-3 px-3 whitespace-nowrap">MODE</th>
                    <th className="py-3 px-3 whitespace-nowrap">CADENCE</th>
                    <th className="py-3 px-3 whitespace-nowrap">HEALTH PROBE</th>
                    <th className="py-3 px-3 text-right whitespace-nowrap">GSC STATUS</th>
                    <th className="py-3 px-3 text-right whitespace-nowrap">ACTIONS</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-outline-variant/15 text-[12px]">
                  {filteredSites.length > 0 ? (
                    filteredSites.map((s) => {
                      const idx = sites.findIndex((x) => x.slug === s.slug);
                      const h = health[idx];
                      const gscSite = sc?.sites?.find((x) => x.slug === s.slug);
                      const isAuto = s.publish_mode === "auto";
                      const isWp = s.site_type === "wordpress";

                      const isHealthy = h && h.critical.length === 0;

                      return (
                        <tr key={s.id} className="hover:bg-surface-container transition-colors group">
                          {/* Slug / Site */}
                          <td className="py-3.5 px-3">
                            <div className="flex items-center gap-2">
                              <span
                                className={`w-2 h-2 rounded-full shrink-0 ${
                                  isHealthy ? "bg-tertiary" : "bg-danger"
                                }`}
                              />
                              <div className="flex flex-col min-w-0">
                                <Link
                                  href={`/sites/${encodeURIComponent(s.slug)}`}
                                  className="font-mono text-[12px] font-semibold text-ink group-hover:text-primary-container transition-colors truncate"
                                >
                                  {s.slug}
                                </Link>
                                <span className="text-[11px] text-secondary truncate">
                                  {s.name || s.slug}
                                </span>
                              </div>
                            </div>
                          </td>

                          {/* Architecture */}
                          <td className="py-3.5 px-3">
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-mono bg-surface-container border border-outline-variant/40 text-ink">
                              {isWp ? "WordPress REST" : "Next.js Webhook"}
                            </span>
                          </td>

                          {/* Mode */}
                          <td className="py-3.5 px-3">
                            {isAuto ? (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-mono bg-primary-container/15 text-primary-container border border-primary-container/30">
                                <Glyph name="bolt" className="text-[12px]" />
                                Auto
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-mono bg-surface-container text-secondary border border-outline-variant/30">
                                <Glyph name="edit_note" className="text-[12px]" />
                                Draft
                              </span>
                            )}
                          </td>

                          {/* Cadence */}
                          <td className="py-3.5 px-3">
                            {(() => {
                              const siteSettings = (s.settings || {}) as Record<string, any>;
                              const cadenceFreq = String(siteSettings.posting_frequency || "every_2_days");
                              const freqMap: Record<string, string> = {
                                daily: "Daily",
                                every_2_days: "Every 2 Days",
                                twice_a_week: "2x / Week",
                                weekly: "Weekly",
                                biweekly: "Bi-Weekly",
                                monthly: "Monthly",
                                manual: "Manual Only",
                              };
                              const label = freqMap[cadenceFreq] || cadenceFreq;
                              return (
                                <div className="flex flex-col">
                                  <span className="font-mono text-[11px] font-semibold text-ink">
                                    {label}
                                  </span>
                                  <span className="text-[10px] text-secondary">
                                    {siteSettings.require_approval !== false ? "Approval Req." : "Auto-Pub"}
                                  </span>
                                </div>
                              );
                            })()}
                          </td>

                          {/* Health Probe */}
                          <td className="py-3.5 px-3">
                            <div className="flex items-center gap-1.5 font-mono text-[11px]">
                              <span
                                className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                                  isHealthy ? "bg-tertiary animate-pulse" : "bg-danger"
                                }`}
                              />
                              <span className={isHealthy ? "text-tertiary" : "text-danger"}>
                                {isHealthy ? "Healthy" : "Degraded"}
                              </span>
                              <span className="text-secondary">• {h?.checks?.length ?? 0} checks</span>
                            </div>
                          </td>

                          {/* GSC Status */}
                          <td className="py-3.5 px-3 text-right">
                            {gscSite?.connected === true ? (
                              <div>
                                <span className="font-mono text-[11px] text-tertiary font-semibold">
                                  Live Verified
                                </span>
                                <span className="text-secondary block text-[10px]">
                                  {gscSite.metrics_28d
                                    ? `${gscSite.metrics_28d.impressions.toLocaleString("en-US")} impr · ${gscSite.metrics_28d.clicks.toLocaleString("en-US")} clicks`
                                    : "28d window"}
                                </span>
                              </div>
                            ) : (
                              <div>
                                <span className="font-mono text-[11px] text-secondary">Pending</span>
                                <span className="text-secondary/60 block text-[10px]">GSC Probe</span>
                              </div>
                            )}
                          </td>

                          {/* Action Buttons */}
                          <td className="py-3.5 px-3 text-right">
                            <div className="flex items-center justify-end gap-1 opacity-80 group-hover:opacity-100 transition-opacity">
                              {s.base_url && (
                                <a
                                  href={s.base_url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="p-1 text-secondary hover:text-ink rounded hover:bg-surface-container"
                                  title="Visit Site"
                                >
                                  <Glyph name="open_in_new" className="text-[16px]" />
                                </a>
                              )}
                              <Link
                                href={`/sites/${encodeURIComponent(s.slug)}`}
                                className="p-1 text-secondary hover:text-ink rounded hover:bg-surface-container"
                                title="Configure Endpoint"
                              >
                                <Glyph name="settings" className="text-[16px]" />
                              </Link>
                              <form action={deleteSiteAction} className="inline-block">
                                <input type="hidden" name="slug" value={s.slug} />
                                <PendingButton
                                  confirmTitle="Disconnect Endpoint"
                                  confirmMessage={`Are you sure you want to disconnect site "${s.slug}"? All associated posts and keywords will also be permanently deleted.`}
                                  confirmButtonLabel="Disconnect Site"
                                  confirmVariant="danger"
                                  pendingLabel="…"
                                  title={`Disconnect site ${s.slug}`}
                                  aria-label={`Disconnect site ${s.slug}`}
                                  className="p-1 text-secondary hover:text-danger rounded hover:bg-surface-container"
                                  leftIcon={<Glyph name="delete" className="text-[16px]" />}
                                >
                                  <span className="sr-only">Disconnect</span>
                                </PendingButton>
                              </form>
                            </div>
                          </td>
                        </tr>
                      );
                    })
                  ) : (
                    <tr>
                      <td colSpan={6} className="py-8 text-center text-secondary font-mono text-[12px]">
                        No endpoints match the selected filter.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            {/* Table Pagination / Summary Footer */}
            <div className="flex items-center justify-between pt-3 border-t border-outline-variant/20 text-secondary font-mono text-[11px]">
              <span>Showing {filteredSites.length} of {sites.length} provisioned sites</span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  disabled
                  className="px-2.5 py-1 rounded bg-surface-container border border-outline-variant/30 text-ink disabled:opacity-40"
                >
                  Prev
                </button>
                <button
                  type="button"
                  disabled
                  className="px-2.5 py-1 rounded bg-surface-container border border-outline-variant/30 text-ink disabled:opacity-40"
                >
                  Next
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Right Column: Provision New Site Endpoint Form */}
        <div className="lg:col-span-5 xl:col-span-4 space-y-4">
          <div className="p-6 rounded-xl bg-surface-lowest border border-outline-variant/30 space-y-6 shadow-xs">
            <div className="pb-4 border-b border-outline-variant/20">
              <div className="flex items-center justify-between">
                <h2 className="font-headline text-[15px] text-ink font-semibold flex items-center gap-2">
                  <Glyph name="add_circle" className="text-primary-container text-base" />
                  <span>Provision New Site Endpoint</span>
                </h2>
                <span className="font-mono text-[11px] text-tertiary bg-tertiary/10 border border-tertiary/20 px-2 py-0.5 rounded">
                  Instant Verification
                </span>
              </div>
              <p className="text-[12px] text-secondary mt-1">
                Attach a WordPress REST target or Next.js ISR webhook to the autonomous publishing pipeline.
              </p>
            </div>

            <form id="provision-form" action={createSiteAction} className="space-y-4">
              {/* Site Display Name */}
              <div className="space-y-1.5">
                <label className="block text-[11px] font-mono uppercase tracking-wider text-secondary">
                  Site Display Name
                </label>
                <input
                  name="name"
                  type="text"
                  placeholder="e.g. Acme Tech Journal"
                  className="w-full px-3.5 py-2 bg-surface-container border border-outline-variant/40 rounded text-ink text-[13px] placeholder:text-secondary/50 focus:outline-none focus:border-primary-container focus:ring-1 focus:ring-primary-container transition-all"
                />
              </div>

              {/* Target Slug */}
              <div className="space-y-1.5">
                <label className="block text-[11px] font-mono uppercase tracking-wider text-secondary">
                  Target Slug / Domain
                </label>
                <div className="relative flex items-center">
                  <span className="absolute left-3 text-secondary font-mono text-[12px] font-bold">#</span>
                  <input
                    name="slug"
                    required
                    type="text"
                    placeholder="domain-or-slug"
                    className="w-full pl-8 pr-3.5 py-2 bg-surface-container border border-outline-variant/40 rounded text-ink font-mono text-[12px] placeholder:text-secondary/50 focus:outline-none focus:border-primary-container focus:ring-1 focus:ring-primary-container transition-all"
                  />
                </div>
              </div>

              {/* CMS Engine Architecture */}
              <div className="space-y-1.5">
                <label className="block text-[11px] font-mono uppercase tracking-wider text-secondary">
                  CMS Engine Architecture
                </label>
                <div className="relative">
                  <select
                    name="site_type"
                    defaultValue="wordpress"
                    className="w-full px-3.5 py-2 bg-surface-container border border-outline-variant/40 rounded text-ink text-[13px] focus:outline-none focus:border-primary-container focus:ring-1 focus:ring-primary-container transition-all appearance-none pr-10 cursor-pointer"
                  >
                    <option value="wordpress">WordPress REST API (v2)</option>
                    <option value="custom">Next.js ISR Webhook</option>
                    <option value="ghost">Ghost CMS Content API</option>
                    <option value="strapi">Strapi Headless GraphQL</option>
                  </select>
                  <Glyph name="unfold_more" className="absolute right-3 top-1/2 -translate-y-1/2 text-secondary pointer-events-none text-base" />
                </div>
              </div>

              {/* Webhook / REST Base URL */}
              <div className="space-y-1.5">
                <label className="block text-[11px] font-mono uppercase tracking-wider text-secondary">
                  Webhook / REST Base URL
                </label>
                <div className="relative flex items-center">
                  <Glyph name="language" className="absolute left-3 text-secondary text-[16px]" />
                  <input
                    name="base_url"
                    required
                    type="url"
                    placeholder="https://yourdomain.com"
                    className="w-full pl-9 pr-3.5 py-2 bg-surface-container border border-outline-variant/40 rounded text-ink font-mono text-[11px] placeholder:text-secondary/50 focus:outline-none focus:border-primary-container focus:ring-1 focus:ring-primary-container transition-all"
                  />
                </div>
              </div>

              {/* Posting Cadence Frequency */}
              <div className="space-y-1.5">
                <label className="block text-[11px] font-mono uppercase tracking-wider text-secondary">
                  Posting Frequency &amp; Cadence
                </label>
                <div className="relative">
                  <select
                    name="posting_frequency"
                    defaultValue="every_2_days"
                    className="w-full px-3.5 py-2 bg-surface-container border border-outline-variant/40 rounded text-ink text-[13px] focus:outline-none focus:border-primary-container focus:ring-1 focus:ring-primary-container transition-all appearance-none pr-10 cursor-pointer"
                  >
                    <option value="every_2_days">Every 2 Days (Recommended)</option>
                    <option value="daily">Daily (1 post / 24h)</option>
                    <option value="twice_a_week">Twice a Week (~8/mo)</option>
                    <option value="weekly">Weekly (1 post / week)</option>
                    <option value="biweekly">Bi-Weekly (2 posts / mo)</option>
                    <option value="monthly">Monthly (1 post / mo)</option>
                    <option value="manual">Manual Only (No auto-publishing)</option>
                  </select>
                  <Glyph name="unfold_more" className="absolute right-3 top-1/2 -translate-y-1/2 text-secondary pointer-events-none text-base" />
                </div>
              </div>

              {/* Publishing Default Mode (Segmented Radio) */}
              <div className="space-y-2 pt-1">
                <label className="block text-[11px] font-mono uppercase tracking-wider text-secondary">
                  Publishing Default Mode
                </label>
                <div className="grid grid-cols-2 gap-2 p-1 bg-surface-container border border-outline-variant/40 rounded">
                  <label className="flex items-center justify-center gap-1.5 py-2 px-2 rounded cursor-pointer transition-all bg-surface-container-high border border-outline-variant/30 text-ink text-[11px] font-mono font-semibold shadow-xs">
                    <input defaultChecked className="hidden" name="publish_mode" type="radio" value="auto" />
                    <Glyph name="bolt" className="text-primary-container text-sm" />
                    <span>Full Autonomous</span>
                  </label>
                  <label className="flex items-center justify-center gap-1.5 py-2 px-2 rounded cursor-pointer transition-all text-secondary hover:text-ink text-[11px] font-mono">
                    <input className="hidden" name="publish_mode" type="radio" value="manual" />
                    <Glyph name="rate_review" className="text-secondary text-sm" />
                    <span>Human Review</span>
                  </label>
                </div>
              </div>

              {/* Live Probe Feedback */}
              {testProbeResult && (
                <div className="p-2.5 rounded bg-tertiary/10 border border-tertiary/20 text-tertiary text-[11px] font-mono animate-fadeIn">
                  {testProbeResult}
                </div>
              )}

              {/* Action Row: Refresh list & Provision */}
              <div className="pt-4 border-t border-outline-variant/20 grid grid-cols-1 gap-2">
                <Link
                  href="/sites"
                  className="flex items-center justify-center gap-1.5 py-2.5 px-3 rounded border border-outline-variant/40 bg-surface-container text-ink font-mono text-[12px] hover:bg-surface-high active:scale-[0.98] transition-all"
                >
                  <Glyph name="visibility" className="text-[16px] text-tertiary" />
                  <span>Refresh list</span>
                </Link>
                <PendingButton
                  pendingLabel="Provisioning…"
                  className="flex items-center justify-center gap-1.5 py-2.5 px-4 rounded bg-primary-container text-white font-mono text-[12px] font-semibold shadow-xs hover:brightness-110 active:scale-[0.98] transition-all"
                  leftIcon={<Glyph name="add" className="text-[16px] font-bold" />}
                >
                  Provision Fleet Site
                </PendingButton>
              </div>
            </form>
          </div>

        </div>
      </div>
    </div>
  );
}
