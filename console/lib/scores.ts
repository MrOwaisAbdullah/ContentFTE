// Pure (no React) score helpers shared by the article detail page, the
// articles table, and the Insights quality panel. Kept JSX-free so the
// console's node-based tests can import it via --experimental-strip-types.
//
// The engine stores scores in meta["scores"] in one of several shapes:
//   {"quality": 94.0}                 (legacy / sheet-backfilled)
//   {"overall": 94.0, "sub_scores": {...}}  (eval-gated runs)
//   {"overall": 94.0, "accuracy": 96, ...}  (flat sub-scores)
// All three must resolve to the same overall number (UX-03).

export type RawScores = Record<string, unknown> | null | undefined;

export interface NormalizedScores {
  overall: number | null;
  subScores: Record<string, number>;
  hasSubScores: boolean;
  raw: Record<string, unknown>;
}

const SUB_KEYS = ["accuracy", "depth", "seo", "voice", "originality", "citability"] as const;

export function normalizeScores(raw: RawScores): NormalizedScores {
  const r: Record<string, unknown> =
    raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const sub = r.sub_scores && typeof r.sub_scores === "object"
    ? (r.sub_scores as Record<string, unknown>)
    : {};
  let overall: number | null = null;
  const candidates = [r.overall, r.quality, sub.overall, sub.quality];
  for (const c of candidates) {
    if (typeof c === "number" && Number.isFinite(c)) { overall = c; break; }
    if (typeof c === "string" && Number.isFinite(Number(c))) { overall = Number(c); break; }
  }
  const subs: Record<string, number> = {};
  for (const k of SUB_KEYS) {
    const v = (typeof r[k] === "number" ? r[k] : sub[k]);
    if (typeof v === "number" && Number.isFinite(v)) subs[k] = v;
  }
  return { overall, subScores: subs, hasSubScores: Object.keys(subs).length === SUB_KEYS.length, raw: r };
}

export function qualityLabel(s: NormalizedScores, status: string): string {
  if (s.overall === null) {
    return status === "published" || status === "approved"
      ? "Not scored (legacy run)"
      : "Not scored";
  }
  const gate = s.overall >= 90;
  if (!s.hasSubScores) {
    return `${Math.round(s.overall)}/100 · sub-scores not recorded`;
  }
  return `${Math.round(s.overall)}/100 · ${gate ? "gate clear" : "below gate"}`;
}

export function scoreBand(value: number): "pass" | "warn" | "fail" {
  if (value >= 90) return "pass";
  if (value >= 75) return "warn";
  return "fail";
}

export function gateStatus(overall: number | null, subs: Record<string, number>): "clear" | "not_clear" | "unknown" {
  if (overall === null) return "unknown";
  if (overall < 90) return "not_clear";
  const keys = ["accuracy", "depth", "seo", "voice", "originality", "citability"];
  for (const k of keys) {
    const v = subs[k];
    if (typeof v === "number" && v < 80) return "not_clear";
  }
  return "clear";
}