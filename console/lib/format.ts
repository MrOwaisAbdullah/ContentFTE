// Pure (no React) formatting helpers. Shared by the console pages and the
// node-based test suite (run with --experimental-strip-types).

export function fmtCost(v: number | null | undefined): string {
  if (v == null) return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  if (n === 0) return "—";
  return `$${n.toFixed(4)}`;
}

export function fmtNum(v: number | null | undefined, decimals = 0): string {
  if (v == null) return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function fmtCompact(v: number | null | undefined): string {
  if (v == null) return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(Math.round(n));
}

export function fmtDate(v: string | null | undefined): string {
  return v ? String(v).slice(0, 10) : "—";
}

export function fmtAgo(v: string | null | undefined): string {
  if (!v) return "—";
  const raw = String(v).replace(" ", "T");
  const t = Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(raw) ? raw : `${raw}Z`);
  if (!Number.isFinite(t)) return "—";
  const s = Math.floor((Date.now() - t) / 1000);
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export function fmtWordCount(v: number | null | undefined): string {
  if (v == null) return "—";
  const n = Number(v);
  if (!Number.isFinite(n) || n <= 0) return "—";
  return `${Math.round(n).toLocaleString()} words`;
}

export function fmtPercent(v: number | null | undefined): string {
  if (v == null) return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  return `${n.toFixed(1)}%`;
}

export function rangeDays(range: string | null | undefined): number {
  switch (range) {
    case "24h": return 1;
    case "7d": return 7;
    case "30d": return 30;
    case "90d": return 90;
    case "qtd": return 65;
    default: return 30;
  }
}

export function isWithinDays(iso: string | null | undefined, days: number, now: number = Date.now()): boolean {
  if (!iso) return false;
  const raw = String(iso).replace(" ", "T");
  const t = Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(raw) ? raw : `${raw}Z`);
  if (!Number.isFinite(t)) return false;
  return now - t <= days * 24 * 60 * 60 * 1000;
}

export function csvEscape(v: unknown): string {
  const s = String(v ?? "");
  return `"${s.replace(/"/g, '""')}"`;
}

export function scopeLabel(site: string | null | undefined): string {
  const s = (site || "").trim();
  return s ? `Scoped to ${s}` : "All sites (fleet)";
}