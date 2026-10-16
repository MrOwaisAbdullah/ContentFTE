import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import { CircleCheck, CircleX, Inbox, Info, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

export function PageHeader({ title, sub, right }: { title: string; sub?: string; right?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-ink">{title}</h1>
        {sub ? <p className="mt-1 text-sm text-ink-dim">{sub}</p> : null}
      </div>
      {right ? <div className="flex items-center gap-3">{right}</div> : null}
    </div>
  );
}

export function SectionCard({
  title,
  right,
  children,
  className = "",
}: {
  title?: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-xl border border-line bg-card p-5 ${className}`}>
      {title ? (
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-medium text-ink-dim">{title}</h2>
          {right}
        </div>
      ) : null}
      {children}
    </section>
  );
}

/* Status pill — color never carries meaning alone: dot + label.
   Scale: drafted=slate · briefed=sky · generated=violet · approved=gold ·
   needs_review=rose · published=emerald (docs/console-dashboard-plan.md §3). */
const STATUS_STYLES: Record<string, { dot: string; text: string; ring: string }> = {
  drafted: { dot: "bg-slate-400", text: "text-slate-300", ring: "border-slate-800 bg-slate-950/60" },
  briefed: { dot: "bg-sky-400", text: "text-sky-300", ring: "border-sky-900/70 bg-sky-950/50" },
  generated: { dot: "bg-violet-400", text: "text-violet-300", ring: "border-violet-900/70 bg-violet-950/50" },
  approved: { dot: "bg-gold", text: "text-gold", ring: "border-amber-900/70 bg-amber-950/50" },
  needs_review: { dot: "bg-danger", text: "text-rose-300", ring: "border-rose-900/70 bg-rose-950/50" },
  published: { dot: "bg-emerald-400", text: "text-emerald-300", ring: "border-emerald-900/70 bg-emerald-950/50" },
};

const FALLBACK_STATUS = { dot: "bg-slate-400", text: "text-slate-300", ring: "border-slate-800 bg-slate-950/60" };

export function statusStyle(status: string) {
  const key = Object.keys(STATUS_STYLES).find(
    (k) => status === k || (k === "briefed" && status.startsWith("brief")),
  );
  return key ? STATUS_STYLES[key] : FALLBACK_STATUS;
}

export function Pill({ status }: { status: string }) {
  const s = statusStyle(status);
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium ${s.ring}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${s.dot}`} aria-hidden />
      <span className={s.text}>{status}</span>
    </span>
  );
}

/* Alerts — one component for the err / success / started banners. */
const ALERT_TONES: Record<"error" | "success" | "info" | "warn", { box: string; text: string; icon: LucideIcon }> = {
  error: { box: "border-rose-900/70 bg-rose-950/40", text: "text-rose-300", icon: CircleX },
  success: { box: "border-emerald-900/70 bg-emerald-950/40", text: "text-emerald-300", icon: CircleCheck },
  warn: { box: "border-amber-900/70 bg-amber-950/40", text: "text-amber-300", icon: TriangleAlert },
  info: { box: "border-line bg-surface/60", text: "text-ink-dim", icon: Info },
};

export function Alert({ tone = "info", children }: { tone?: "error" | "success" | "info" | "warn"; children: ReactNode }) {
  const t = ALERT_TONES[tone];
  const Icon = t.icon;
  return (
    <div className={`flex items-start gap-2 rounded-lg border px-4 py-3 text-sm ${t.box} ${t.text}`}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="min-w-0">{children}</div>
    </div>
  );
}

/* Empty states always point somewhere (plan finding F7). */
export function Empty({
  title,
  hint,
  cta,
  icon: Icon = Inbox,
}: {
  title: string;
  hint?: string;
  cta?: { href: string; label: string };
  icon?: LucideIcon;
}) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-line bg-card/40 px-6 py-12 text-center">
      <span className="flex h-10 w-10 items-center justify-center rounded-lg border border-line bg-surface text-ink-faint">
        <Icon className="h-5 w-5" aria-hidden />
      </span>
      <div>
        <p className="text-sm font-medium text-ink">{title}</p>
        {hint ? <p className="mt-1 max-w-md text-xs text-ink-dim">{hint}</p> : null}
      </div>
      {cta ? (
        <Link
          href={cta.href}
          className="rounded-md bg-accent-strong px-3.5 py-1.5 text-xs font-medium text-page hover:bg-accent"
        >
          {cta.label}
        </Link>
      ) : null}
    </div>
  );
}

/* Button class recipes (plain buttons rendered server-side). */
export const BTN =
  "inline-flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50";
export const BTN_GHOST = `${BTN} border border-line bg-page text-ink-dim hover:border-ink-faint hover:text-ink`;
export const BTN_PRIMARY = `${BTN} bg-accent-strong text-page hover:bg-accent`;
export const BTN_GOLD = `${BTN} bg-gold text-page hover:bg-amber-400`;
export const BTN_DANGER = `${BTN} border border-rose-900 bg-rose-950/40 text-rose-300 hover:bg-rose-950/70`;

/* Formatters — plan finding F4: zeros are “—”, real money keeps 4 decimals. */
export function fmtCost(v: number | null | undefined): string {
  if (v == null) return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  return n === 0 ? "—" : `$${n.toFixed(4)}`;
}

export function fmtScore(v: number | null | undefined, digits = 1): string {
  if (v == null) return "—";
  const n = Number(v);
  return Number.isFinite(n) ? n.toFixed(digits) : "—";
}

export function fmtDate(v: string | null | undefined): string {
  return v ? String(v).slice(0, 10) : "—";
}

/* Health findings tiering (plan finding F4): engine `critical` checks are
   failures; connection/probe breaks are warnings; the rest (WP env not set,
   empty queue hints, engine-generated sitemap notes) is configuration info —
   not red. */
export type CheckTier = "fail" | "warn" | "info";

export function checkTier(line: string): CheckTier {
  if (/(ConnectionError|unreachable|failed|timed out|Connection aborted)/i.test(line)) return "warn";
  return "info";
}
