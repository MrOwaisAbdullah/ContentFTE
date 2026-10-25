"use client";

import { useState } from "react";

export type VelocityPoint = {
  day: string;
  created: number;
  gscImpressions?: number;
};

export function InteractiveVelocityChart({
  points,
  connected = false,
}: {
  points: VelocityPoint[];
  connected?: boolean;
}) {
  const [activeIdx, setActiveIdx] = useState<number | null>(null);
  const data = points && points.length ? points : [];
  const maxCreated = Math.max(1, ...data.map((p) => p.created));
  const maxImp = Math.max(1, ...data.map((p) => p.gscImpressions ?? 0));

  if (data.length === 0) {
    return (
      <div className="bg-surface-lowest border border-outline-variant/30 rounded-xl p-6 shadow-xs">
        <h2 className="text-[17px] font-headline font-semibold text-ink">
          Publishing velocity
        </h2>
        <p className="text-[12px] text-secondary mt-2">No article data yet.</p>
      </div>
    );
  }

  return (
    <div className="bg-surface-lowest border border-outline-variant/30 rounded-xl p-6 shadow-xs space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-outline-variant/15">
        <div>
          <h2 className="text-[17px] font-headline font-semibold text-ink">
            Publishing velocity
          </h2>
          <p className="text-[12px] text-secondary mt-0.5">
            Articles created per day{connected ? " · GSC impressions overlaid" : " · GSC not connected"}
          </p>
        </div>
        <div className="flex items-center gap-4 text-[11px] font-mono shrink-0">
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-primary-container shrink-0" />
            <span className="text-secondary">Articles created</span>
          </div>
          {connected ? (
            <div className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-tertiary shrink-0" />
              <span className="text-secondary">GSC impressions (k)</span>
            </div>
          ) : null}
        </div>
      </div>

      <div
        className="relative w-full h-64 bg-surface-container/30 rounded-lg border border-outline-variant/20 p-4 flex flex-col justify-end overflow-hidden select-none cursor-crosshair"
        onMouseLeave={() => setActiveIdx(null)}
      >
        <div className="absolute inset-0 flex flex-col justify-between p-4 pointer-events-none opacity-20">
          <div className="w-full border-b border-outline-variant border-dashed" />
          <div className="w-full border-b border-outline-variant border-dashed" />
          <div className="w-full border-b border-outline-variant border-dashed" />
          <div className="w-full border-b border-outline-variant border-dashed" />
        </div>
        <div className="relative z-10 flex items-end justify-between gap-1 h-full">
          {data.map((p, idx) => {
            const isHovered = activeIdx === idx;
            const h = Math.max(4, (p.created / maxCreated) * 100);
            return (
              <div
                key={p.day}
                className="flex-1 flex flex-col items-center justify-end gap-1 min-w-0"
                onMouseEnter={() => setActiveIdx(idx)}
              >
                {isHovered ? (
                  <div className="mb-1 bg-surface-high/95 backdrop-blur-md border border-line rounded-lg px-2.5 py-1.5 shadow-xl text-[10px] font-mono text-ink space-y-0.5">
                    <div className="font-semibold border-b border-line pb-0.5">{p.day}</div>
                    <div className="flex items-center justify-between gap-3 text-primary-container">
                      <span>Articles:</span>
                      <span className="font-bold">{p.created}</span>
                    </div>
                    {connected && p.gscImpressions != null ? (
                      <div className="flex items-center justify-between gap-3 text-tertiary">
                        <span>Impressions:</span>
                        <span className="font-bold">{p.gscImpressions}k</span>
                      </div>
                    ) : null}
                  </div>
                ) : null}
                <div
                  className={`w-full rounded-t transition-all duration-150 ${isHovered ? "bg-primary-container" : "bg-primary-container/60"}`}
                  style={{ height: `${h}%` }}
                  aria-label={`${p.day}: ${p.created} articles`}
                />
                <span className="text-[9px] font-mono text-secondary truncate w-full text-center">
                  {p.day.slice(0, 5)}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      <p className="text-[11px] font-mono text-ink-faint">
        {connected
          ? "GSC impressions overlaid where a connected property is configured."
          : "GSC not connected — impressions series unavailable. Connect a property on the Sites screen."}
      </p>
    </div>
  );
}