"use client";

import { useState } from "react";

export function InteractiveQualityMeter({
  scored,
  avgQuality,
  passRate,
  bands,
}: {
  scored: number;
  avgQuality: number | null;
  passRate: number | null;
  bands?: { label: string; count: number }[];
}) {
  const [hovered, setHovered] = useState<string | null>(null);

  const radius = 50;
  const circumference = 2 * Math.PI * radius;
  const base = avgQuality ?? 0;
  const active = hovered
    ? (bands?.find((b) => b.label === hovered)?.count ?? base)
    : base;
  const offset = circumference - (base / 100) * circumference;

  if (scored === 0) {
    return (
      <div className="bg-surface-lowest border border-outline-variant/30 rounded-xl p-6 shadow-xs">
        <h3 className="text-[17px] font-headline font-semibold text-ink">
          Quality coverage
        </h3>
        <p className="text-[12px] text-secondary mt-2">
          No quality scores recorded yet. Scores arrive when articles pass the generate stage.
        </p>
      </div>
    );
  }

  const bandList = bands && bands.length
    ? bands
    : [{ label: "avg", count: avgQuality ?? 0 }];

  return (
    <div className="bg-surface-lowest border border-outline-variant/30 rounded-xl p-6 shadow-xs space-y-5">
      <div className="flex items-center justify-between pb-3 border-b border-outline-variant/15">
        <div>
          <h3 className="text-[17px] font-headline font-semibold text-ink">
            Quality coverage
          </h3>
          <p className="text-[12px] text-secondary mt-0.5">
            {scored} scored article{scored === 1 ? "" : "s"} · avg {avgQuality ?? "—"}/100
          </p>
        </div>
        <span className="text-[11px] font-mono text-tertiary font-semibold px-2.5 py-0.5 rounded-full bg-tertiary/10 border border-tertiary/25">
          {passRate != null ? `${passRate}%` : "—"} pass (≥90)
        </span>
      </div>

      <div className="flex flex-col items-center justify-center my-3">
        <div className="relative w-40 h-40 flex items-center justify-center">
          <svg className="w-full h-full transform -rotate-90 overflow-visible" viewBox="0 0 120 120">
            <circle cx="60" cy="60" r={radius} fill="transparent" stroke="currentColor" className="text-surface-container-high/60" strokeWidth="9" />
            <circle
              cx="60" cy="60" r={radius} fill="transparent"
              stroke="#f2643a" strokeDasharray={circumference} strokeDashoffset={offset}
              strokeLinecap="round" strokeWidth="9" className="transition-all duration-300"
            />
          </svg>
          <div className="absolute flex flex-col items-center pointer-events-none select-none">
            <span className="text-[34px] font-headline font-bold tracking-tight font-mono text-ink">
              {(avgQuality ?? 0).toFixed(1)}
            </span>
            <span className="text-[10px] font-mono text-secondary tracking-wider uppercase font-semibold">
              AVG SCORE
            </span>
          </div>
        </div>
      </div>

      <div className="space-y-2 pt-3 border-t border-outline-variant/20">
        <div className="flex items-center justify-between text-[11px] font-mono text-secondary">
          <span>SCORE DISTRIBUTION</span>
          <span>ARTICLES</span>
        </div>
        {bandList.map((b) => (
          <div
            key={b.label}
            onMouseEnter={() => setHovered(b.label)}
            onMouseLeave={() => setHovered(null)}
            className={`flex items-center justify-between text-[12px] px-2 py-1 rounded transition-colors ${hovered === b.label ? "bg-surface-container" : ""}`}
          >
            <span className="text-secondary">{b.label}</span>
            <span className="font-mono text-ink font-semibold">{b.count}</span>
          </div>
        ))}
        <p className="mt-2 text-[11px] font-mono text-ink-faint">
          Sub-scores (accuracy, depth, SEO, voice, originality, citability) are recorded per article when the eval gate runs; open an article to see its breakdown.
        </p>
      </div>
    </div>
  );
}