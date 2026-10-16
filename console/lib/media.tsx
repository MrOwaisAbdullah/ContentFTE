import type { ReactNode } from "react";

import { fmtCost } from "./ui";

/* Media gallery pieces (plan §5/§6 Wave 3): article `meta.images` rows.
   Thumbnails stream through the console's own proxy route
   (/api/media/{id}/{name}) — the engine keeps its X-Site-Key auth and the
   browser never talks to the engine directly. Rows without a local `path`
   (remote-only stock picks) fall back to their source URL.

   QA badges are tiered honestly: current runs carry a `qa` block with the
   Jev style pick (style_pick/style_source) and the VLM lanes; legacy rows
   (pre-Jev) render whatever they recorded and say what's missing instead of
   guessing. */

export interface MediaImageQa {
  passed?: boolean;
  matches_blog?: number | null;
  matches_style?: number | null;
  clean?: number | null;
  theme_fit?: number | null;
  threshold_blog?: number;
  threshold_style?: number;
  threshold_clean?: number;
  threshold_theme?: number;
  style_pick?: string | null;
  style_source?: string | null;
  style_scores?: Record<string, number> | null;
  attempts?: number;
  max_revisions?: number;
  model?: string;
  issues?: string[];
  recovered_from?: number;
  vlm_rank?: number;
  [k: string]: unknown;
}

export interface MediaImage {
  slot?: string;
  path?: string;
  url?: string;
  alt?: string;
  after_h2?: number;
  source?: string;
  cost_usd?: number;
  qa?: MediaImageQa;
  [k: string]: unknown;
}

/** Thumbnail source: console proxy for staged files, source URL otherwise. */
export function imageSrc(articleId: number, image: MediaImage): string | null {
  const p = typeof image.path === "string" ? image.path : "";
  if (p) {
    const name = p.split(/[\\/]/).pop();
    if (name) return `/api/media/${articleId}/${encodeURIComponent(name)}`;
  }
  const u = typeof image.url === "string" ? image.url : "";
  return u || null;
}

function Chip({
  tone,
  title,
  children,
}: {
  tone: "pass" | "warn" | "accent" | "dim";
  title?: string;
  children: ReactNode;
}) {
  const cls = {
    pass: "border-emerald-900/60 bg-emerald-950/40 text-emerald-300",
    warn: "border-amber-900/60 bg-amber-950/40 text-amber-300",
    accent: "border-teal-900/70 bg-teal-950/40 text-teal-300",
    dim: "border-line bg-surface/60 text-ink-faint",
  }[tone];
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px] leading-none ${cls}`}
    >
      {children}
    </span>
  );
}

export function MediaCard({ articleId, image }: { articleId: number; image: MediaImage }) {
  const src = imageSrc(articleId, image);
  const qa = (image.qa || {}) as MediaImageQa;
  const lanes = (
    [
      { label: "blog", value: qa.matches_blog, floor: qa.threshold_blog },
      { label: "style", value: qa.matches_style, floor: qa.threshold_style },
      { label: "clean", value: qa.clean, floor: qa.threshold_clean },
      { label: "theme", value: qa.theme_fit, floor: qa.threshold_theme },
    ] as { label: string; value?: number | null; floor?: number }[]
  ).filter((l) => typeof l.value === "number");
  const stylePick = typeof qa.style_pick === "string" ? qa.style_pick : "";
  const styleSource = typeof qa.style_source === "string" ? qa.style_source : "";
  const slot = image.slot === "inpost" ? "inline" : image.slot || "image";
  const alt = typeof image.alt === "string" ? image.alt : "";
  const issues = Array.isArray(qa.issues) ? qa.issues : [];

  return (
    <figure className="overflow-hidden rounded-xl border border-line bg-card">
      {src ? (
        // Plain <img>: engine files are arbitrary formats and the proxy
        // route sets its own cache headers — next/image adds nothing here.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={src}
          alt={alt || `${slot} image`}
          loading="lazy"
          className="aspect-[16/9] w-full bg-page object-cover"
        />
      ) : (
        <div className="flex aspect-[16/9] w-full items-center justify-center bg-page text-xs text-ink-faint">
          no local file and no source URL
        </div>
      )}
      <figcaption className="space-y-2 p-3">
        <div className="flex flex-wrap items-center gap-1.5">
          <Chip tone="dim">{slot}</Chip>
          {typeof image.after_h2 === "number" ? (
            <Chip tone="dim" title="Injected inline before this H2 on delivery">
              before H2 #{image.after_h2}
            </Chip>
          ) : null}
          {stylePick ? (
            <Chip
              tone={styleSource === "jev" ? "accent" : "dim"}
              title={qa.style_scores ? `direction ranking: ${JSON.stringify(qa.style_scores)}` : undefined}
            >
              {styleSource === "jev" ? "Jev pick" : styleSource === "fallback_hash" ? "hash fallback" : "style"} · {stylePick}
            </Chip>
          ) : (
            <Chip tone="dim">pre-Jev — no style recorded</Chip>
          )}
          {qa.passed === true ? <Chip tone="pass">QA passed</Chip> : null}
          {qa.passed === false ? <Chip tone="warn">QA not passing</Chip> : null}
          {typeof qa.attempts === "number" && typeof qa.max_revisions === "number" ? (
            <Chip tone="dim" title="generation attempts used / allowed">
              try {qa.attempts}/{qa.max_revisions}
            </Chip>
          ) : null}
          {typeof qa.recovered_from === "number" ? (
            <Chip tone="warn" title="recovered by vlm ranking from an earlier attempt">
              recovered
            </Chip>
          ) : null}
        </div>

        {lanes.length ? (
          <div className="flex flex-wrap items-center gap-2 font-mono text-[10px]">
            {lanes.map((l) => {
              const pass = typeof l.floor === "number" ? (l.value as number) >= l.floor : undefined;
              return (
                <span
                  key={l.label}
                  title={typeof l.floor === "number" ? `VLM lane floor ${l.floor}` : "no stored floor"}
                  className={pass === false ? "text-amber-300" : pass === true ? "text-emerald-300" : "text-ink-dim"}
                >
                  {l.label} {(l.value as number).toFixed(2)}
                </span>
              );
            })}
          </div>
        ) : (
          <p className="text-[10px] text-ink-faint">VLM lanes not recorded on this run.</p>
        )}

        {alt ? (
          <p className="line-clamp-2 text-xs leading-5 text-ink-dim" title={alt}>
            {alt}
          </p>
        ) : null}
        {issues.length ? (
          <p className="truncate text-[10px] text-amber-300/90" title={issues.join(" · ")}>
            {String(issues[0])}
          </p>
        ) : null}
        <p className="flex items-center justify-between gap-2 border-t border-line/60 pt-2 text-[10px] text-ink-faint">
          <span className="truncate font-mono" title={typeof qa.model === "string" ? qa.model : undefined}>
            {typeof qa.model === "string" ? qa.model.replace(/^@cf\//, "") : "—"}
          </span>
          <span className="font-mono">{fmtCost(typeof image.cost_usd === "number" ? image.cost_usd : null)}</span>
        </p>
      </figcaption>
    </figure>
  );
}
