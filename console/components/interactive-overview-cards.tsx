"use client";

import { useState } from "react";
import Link from "next/link";
import { Glyph } from "@/components/glyph";

export interface OverviewCardsProps {
  totalSites: number;
  healthySites: number;
  wpSites: number;
  customSites: number;
  site: string;
  totalArticles: number;
  publishedCount: number;
  awaitingCount: number;
  generatingCount: number;
  queueCount: number;
  briefCount: number;
  avgQuality: number | null;
  passRate: number | null;
  wtdFmt: string;
  gscImpressions: number;
  gscClicks: number;
  gscConnectedSites: number;
}

export function InteractiveKpiCards({
  totalSites,
  healthySites,
  wpSites,
  customSites,
  site,
  publishedCount,
  awaitingCount,
  wtdFmt,
  avgQuality,
  passRate,
  gscImpressions,
  gscClicks,
  gscConnectedSites,
}: OverviewCardsProps) {
  const [hoveredKpi, setHoveredKpi] = useState<number | null>(null);

  const formatImp = (val: number) => {
    if (val >= 1_000_000) return `${(val / 1_000_000).toFixed(2)}M`;
    if (val >= 1_000) return `${(val / 1_000).toFixed(1)}k`;
    return val.toLocaleString("en-US");
  };

  const kpis = [
    {
      id: 1,
      title: site ? "Selected Site" : "Active Sites",
      icon: "domain",
      val: site ? "1" : String(totalSites),
      statusText: site
        ? `${site} • Active`
        : totalSites > 0
        ? `${Math.round((healthySites / Math.max(1, totalSites)) * 100)}% Endpoints Healthy`
        : "No sites connected",
      statusColor: "tertiary",
      meta: site ? "Scoped Tenant View" : `${wpSites} WordPress • ${customSites} Custom`,
      actionLabel: site ? "Configure" : "Manage",
      actionHref: site ? `/sites/${encodeURIComponent(site)}` : "/sites",
      hoverDetail: site
        ? `Scoped Site: ${site} • Connected & Health Checked`
        : `Fleet: ${totalSites} Provisioned • ${healthySites} Healthy • ${wpSites} WordPress • ${customSites} Custom`,
    },
    {
      id: 2,
      title: "Search Console Impressions",
      icon: "trending_up",
      val: gscImpressions > 0 ? formatImp(gscImpressions) : "0",
      statusText: gscConnectedSites > 0 ? `${gscConnectedSites} GSC properties linked` : "Pending GSC connection",
      statusColor: gscImpressions > 0 ? "tertiary" : "secondary",
      meta: gscClicks > 0 ? `${formatImp(gscClicks)} Organic Clicks` : "Google Search Console",
      actionLabel: "Telemetry",
      actionHref: "/insights",
      hoverDetail: gscImpressions > 0
        ? `GSC Telemetry: ${gscImpressions.toLocaleString("en-US")} impressions across ${gscConnectedSites} verified property(ies)`
        : `GSC Verification: ${gscConnectedSites} site(s) configured • Ingestion active`,
    },
    {
      id: 3,
      title: "Quality Pass Rate",
      icon: "verified",
      val: passRate != null ? `${passRate}%` : "—",
      statusText: avgQuality != null ? `Avg Score: ${avgQuality}/100` : "Awaiting evaluations",
      statusColor: (passRate ?? 0) >= 75 ? "tertiary" : "secondary",
      meta: awaitingCount > 0 ? `${awaitingCount} in human review queue` : "All checks clear",
      actionLabel: awaitingCount > 0 ? `${awaitingCount} Review` : "Approvals",
      actionHref: "/approvals",
      hoverDetail: avgQuality != null
        ? `Average Model Evaluation: ${avgQuality}/100 • Pass Rate: ${passRate}% • ${awaitingCount} draft(s) awaiting approval`
        : "Evaluation gate active: automated factual, citation, and readability audits",
    },
    {
      id: 4,
      title: "Publishing Output",
      icon: "speed",
      val: String(publishedCount),
      valSuffix: publishedCount === 1 ? "article live" : "articles live",
      statusText: publishedCount > 0 ? "Dispatched to Edge CMS" : "Queue waiting for dispatch",
      statusColor: publishedCount > 0 ? "tertiary" : "secondary",
      meta: `Spend: ${wtdFmt}`,
      actionLabel: "Publish Queue",
      actionHref: "/publish",
      hoverDetail: `Total Published: ${publishedCount} • Rolling API Spend: ${wtdFmt} • Auto-sync active`,
    },
  ];

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
      {kpis.map((kpi) => {
        const isHovered = hoveredKpi === kpi.id;
        return (
          <div
            key={kpi.id}
            onMouseEnter={() => setHoveredKpi(kpi.id)}
            onMouseLeave={() => setHoveredKpi(null)}
            className={`p-6 rounded-xl bg-surface-lowest border transition-all duration-200 space-y-4 shadow-xs relative cursor-pointer ${
              isHovered
                ? "border-primary-container/40 bg-surface-container/50 -translate-y-0.5 shadow-md"
                : "border-outline-variant/30 hover:border-outline-variant/60"
            }`}
          >
            <div className="flex items-center justify-between text-secondary">
              <span className="text-[12px] font-mono tracking-wider uppercase font-semibold text-secondary/80">
                {kpi.title}
              </span>
              <Glyph name={kpi.icon} className="text-[18px] text-secondary/70" />
            </div>

            <div>
              <div className="flex items-baseline gap-2">
                <span className="text-[32px] font-headline font-bold text-ink tracking-tight font-mono">
                  {kpi.val}
                </span>
                {kpi.valSuffix && (
                  <span className="text-[12px] font-mono text-secondary">{kpi.valSuffix}</span>
                )}
              </div>
              <div className="flex items-center gap-1.5 text-[12px] font-mono mt-1">
                <span className={kpi.statusColor === "tertiary" ? "text-tertiary" : "text-secondary"}>
                  {kpi.statusText}
                </span>
              </div>
            </div>

            {/* Hover Detailed Breakdown Pill vs Default Metadata */}
            {isHovered ? (
              <div className="pt-3 border-t border-line text-[11px] font-mono text-tertiary leading-relaxed animate-in fade-in duration-100">
                {kpi.hoverDetail}
              </div>
            ) : (
              <div className="pt-3 border-t border-outline-variant/15 flex flex-wrap items-center justify-between gap-x-2 gap-y-1 text-[11px] font-mono">
                <span className="text-secondary/70 whitespace-nowrap">{kpi.meta}</span>
                <Link
                  href={kpi.actionHref}
                  className="text-primary-container hover:underline font-semibold whitespace-nowrap"
                >
                  {kpi.actionLabel}
                </Link>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export function InteractiveStreamStages({
  queueCount,
  briefCount,
  awaitingCount,
  publishedCount,
  generatingCount = 0,
  mediaCount = 0,
}: {
  queueCount: number;
  briefCount: number;
  awaitingCount: number;
  publishedCount: number;
  generatingCount?: number;
  mediaCount?: number;
}) {
  const [hoveredStage, setHoveredStage] = useState<number | null>(null);

  const stages = [
    {
      num: "01",
      name: "RESEARCH",
      val: queueCount,
      sub: "Topics In Queue",
      engine: "SERP Intelligence",
      active: queueCount > 0,
      detail: `${queueCount} keyword topic(s) currently tracked in ledger queue`,
    },
    {
      num: "02",
      name: "BRIEFS",
      val: briefCount,
      sub: "Outlines Ready",
      engine: "Semantic Architecture",
      active: briefCount > 0,
      detail: `${briefCount} editorial brief(s) generated and ready for synthesis`,
    },
    {
      num: "03",
      name: "SYNTHESIS",
      val: generatingCount > 0 ? `${generatingCount} Generating` : awaitingCount > 0 ? `${awaitingCount} In Pipeline` : "Idle",
      sub: "Content Generation",
      engine: "Multi-Agent Drafter",
      active: generatingCount > 0 || awaitingCount > 0,
      detail: `Pipeline processing: ${generatingCount} generating • ${awaitingCount} generated`,
    },
    {
      num: "04",
      name: "MEDIA",
      val: mediaCount,
      sub: "Visual Assets Staged",
      engine: "Visual Generator",
      active: mediaCount > 0,
      detail: `${mediaCount} custom infographics and visual figures generated for content`,
    },
    {
      num: "05",
      name: "QUALITY GATE",
      val: `${awaitingCount} Awaiting Review`,
      sub: "Editorial & Audit Gate",
      engine: "Verification Guardrails",
      active: awaitingCount > 0,
      detail: `${awaitingCount} article(s) require human editorial decision before publishing`,
    },
    {
      num: "06",
      name: "DISPATCH",
      val: `${publishedCount} Published`,
      sub: "Live on Site Endpoints",
      engine: "REST / Webhook Push",
      active: publishedCount > 0,
      detail: `${publishedCount} article(s) successfully pushed to CMS production targets`,
    },
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
      {stages.map((st, idx) => {
        const isHovered = hoveredStage === idx;
        return (
          <div
            key={st.num}
            onMouseEnter={() => setHoveredStage(idx)}
            onMouseLeave={() => setHoveredStage(null)}
            className={`p-5 rounded-xl border transition-all duration-200 space-y-3 cursor-pointer ${
              st.active
                ? "bg-surface-lowest border-primary-container/40 hover:border-primary-container/80 shadow-[0_0_12px_rgba(242,100,58,0.12)]"
                : isHovered
                ? "bg-surface-container/60 border-primary-container/30 -translate-y-0.5 shadow-md"
                : "bg-surface-lowest border-outline-variant/30 hover:border-outline-variant/60"
            }`}
          >
            <div className="flex items-center justify-between">
              <span
                className={`text-[11px] font-mono font-medium ${
                  st.active ? "text-primary-container font-semibold" : "text-secondary"
                }`}
              >
                {st.num} // {st.name}
              </span>
              <span
                className={`w-2 h-2 rounded-full ${
                  st.active
                    ? "bg-primary-container animate-pulse shadow-[0_0_8px_rgba(242,100,58,0.7)]"
                    : "bg-tertiary/70"
                }`}
              />
            </div>

            <div className="space-y-1">
              <div className="text-[20px] font-headline font-semibold text-ink font-mono">{st.val}</div>
              <div className="text-[12px] text-secondary font-sans">{st.sub}</div>
            </div>

            {isHovered ? (
              <div className="pt-2.5 border-t border-line text-[11px] font-mono text-tertiary animate-in fade-in duration-100">
                {st.detail}
              </div>
            ) : (
              <div
                className={`pt-3 border-t border-outline-variant/15 text-[11px] font-mono ${
                  st.active ? "text-primary-container font-medium" : "text-secondary/70"
                }`}
              >
                {st.engine}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
