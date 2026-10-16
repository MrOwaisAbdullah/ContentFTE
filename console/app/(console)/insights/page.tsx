import Link from "next/link";
import { BarChart3 } from "lucide-react";

import { engine, ArticleList, LogsView } from "@/lib/engine";
import { Alert, Empty, PageHeader, SectionCard, fmtCost } from "@/lib/ui";

export const dynamic = "force-dynamic";

/* Insights (plan §6 Wave 4): cost cards (llm/image/data/total per article +
   site) and a usage breakdown, aggregated console-side from the newest
   ledger rows (`/logs?kind=cost|usage`). Ledger rollup rows (kind "total")
   are excluded so sums don't double count; raw rows with paging live on
   /logs. */

const COST_KINDS = ["llm", "image", "data"] as const;
type CostKind = (typeof COST_KINDS)[number];
const KIND_LABEL: Record<CostKind, string> = {
  llm: "LLM",
  image: "Images",
  data: "Data & APIs",
};
const isCostKind = (k: string): k is CostKind =>
  (COST_KINDS as readonly string[]).includes(k);

export default async function InsightsPage({
  searchParams,
}: {
  searchParams: Promise<{ site?: string }>;
}) {
  const { site = "" } = await searchParams;

  const [costsRes, usageRes, artsRes] = await Promise.allSettled([
    engine<LogsView>("/logs?kind=cost&limit=500"),
    engine<LogsView>("/logs?kind=usage&limit=500"),
    engine<ArticleList>("/articles?limit=500"),
  ]);

  const errors: string[] = [];
  if (costsRes.status === "rejected") errors.push("cost rows");
  if (usageRes.status === "rejected") errors.push("usage rows");
  if (artsRes.status === "rejected") errors.push("article index");

  const costs = costsRes.status === "fulfilled" ? costsRes.value.costs : [];
  const usage = usageRes.status === "fulfilled" ? usageRes.value.audit : [];
  const articles = artsRes.status === "fulfilled" ? artsRes.value.articles : [];
  const artById = new Map(articles.map((a) => [a.id, a]));

  const inSite = (articleId: number | null | undefined) =>
    !site || (articleId != null && artById.get(articleId)?.site_slug === site);

  const scopedCosts = costs.filter((c) => inSite(c.article_id));
  const scopedUsage = usage.filter((u) => inSite(u.article_id));

  // Category sums + grand total (rollup "total" rows excluded).
  const kindSum = new Map<CostKind, { amount: number; rows: number }>();
  let total = 0;
  for (const c of scopedCosts) {
    if (!isCostKind(c.kind)) continue;
    const amt = Number(c.amount_usd) || 0;
    const rec = kindSum.get(c.kind) ?? { amount: 0, rows: 0 };
    rec.amount += amt;
    rec.rows += 1;
    kindSum.set(c.kind, rec);
    total += amt;
  }
  const catRows = [...kindSum.values()].reduce((n, r) => n + r.rows, 0);

  // Per-article + per-site rollups.
  type ArtRow = { llm: number; image: number; data: number; total: number };
  const byArticle = new Map<number, ArtRow>();
  for (const c of scopedCosts) {
    if (!isCostKind(c.kind)) continue;
    const row = byArticle.get(c.article_id) ?? { llm: 0, image: 0, data: 0, total: 0 };
    const amt = Number(c.amount_usd) || 0;
    row[c.kind] += amt;
    row.total += amt;
    byArticle.set(c.article_id, row);
  }
  const topArticles = [...byArticle.entries()]
    .sort((a, b) => b[1].total - a[1].total)
    .slice(0, 8);

  const bySite = new Map<string, { total: number; articles: number }>();
  for (const [aid, row] of byArticle) {
    const slug = artById.get(aid)?.site_slug ?? "unattributed";
    const rec = bySite.get(slug) ?? { total: 0, articles: 0 };
    rec.total += row.total;
    rec.articles += 1;
    bySite.set(slug, rec);
  }
  const siteRows = [...bySite.entries()].sort((a, b) => b[1].total - a[1].total);

  // Usage breakdown by model, split by lane (model vs image calls).
  type ModelRow = { lane: "model" | "image"; calls: number; failed: number };
  const byModel = new Map<string, ModelRow>();
  for (const u of scopedUsage) {
    const payload = (u.payload ?? {}) as Record<string, unknown>;
    const model = String(payload.model || "unknown");
    const lane: "model" | "image" = u.action === "usage.image" ? "image" : "model";
    const key = `${lane}:${model}`;
    const rec = byModel.get(key) ?? { lane, calls: 0, failed: 0 };
    rec.calls += 1;
    if (String(payload.status ?? "").toLowerCase() !== "success") rec.failed += 1;
    byModel.set(key, rec);
  }
  const modelRows = [...byModel.entries()]
    .map(([key, v]) => ({ model: key.slice(key.indexOf(":") + 1), ...v }))
    .sort((a, b) => b.calls - a.calls);
  const totalCalls = modelRows.reduce((n, r) => n + r.calls, 0);
  const totalFailed = modelRows.reduce((n, r) => n + r.failed, 0);
  const maxCalls = modelRows[0]?.calls ?? 0;

  const emptyAll = scopedCosts.length === 0 && modelRows.length === 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Insights"
        sub="cost + usage, aggregated from the newest ledger rows"
        right={
          <Link href="/logs" className="text-xs text-accent hover:text-accent-strong hover:underline">
            raw logs →
          </Link>
        }
      />

      {errors.length ? (
        <Alert tone="warn">Partial data — unavailable: {errors.join(", ")}.</Alert>
      ) : null}

      {site ? (
        <p className="text-xs text-ink-faint">
          Filtered to <span className="font-mono text-ink-dim">{site}</span> ·{" "}
          <Link href="/insights" className="text-accent hover:underline">
            show all sites
          </Link>
        </p>
      ) : null}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat
          label="Total spend"
          value={fmtCost(total)}
          sub={`${catRows} category row${catRows === 1 ? "" : "s"}`}
          strong
        />
        {COST_KINDS.map((k) => {
          const rec = kindSum.get(k);
          return (
            <Stat
              key={k}
              label={KIND_LABEL[k]}
              value={fmtCost(rec?.amount ?? 0)}
              sub={`${rec?.rows ?? 0} row${(rec?.rows ?? 0) === 1 ? "" : "s"}`}
            />
          );
        })}
      </div>

      {emptyAll ? (
        <Empty
          icon={BarChart3}
          title={site ? `No ledger or usage rows on ${site} in the window` : "No ledger or usage rows in the window"}
          hint="Insights aggregates what the engine logs — run a stage or publish to see spend and model usage."
          cta={{ href: "/stages", label: "Open stage runs" }}
        />
      ) : (
        <>
          <SectionCard title="Spend by category">
            {total === 0 ? (
              <p className="text-sm text-ink-faint">No categorized spend in the window yet.</p>
            ) : (
              <ul className="space-y-3">
                {COST_KINDS.map((k) => {
                  const rec = kindSum.get(k);
                  if (!rec || rec.rows === 0) return null;
                  const pct = total > 0 ? (rec.amount / total) * 100 : 0;
                  return (
                    <li key={k}>
                      <div className="flex items-baseline justify-between gap-3 text-xs">
                        <span className="text-ink-dim">{KIND_LABEL[k]}</span>
                        <span className="font-mono text-ink-faint">
                          {fmtCost(rec.amount)} · {pct.toFixed(0)}%
                        </span>
                      </div>
                      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-surface/70">
                        <div className="h-full rounded-full bg-accent" style={{ width: `${pct}%` }} />
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </SectionCard>

          <SectionCard
            title="Top articles by cost"
            right={
              <Link href="/articles" className="text-xs text-accent hover:underline">
                pipeline →
              </Link>
            }
          >
            {topArticles.length === 0 ? (
              <p className="text-sm text-ink-faint">No per-article spend in the window yet.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-left text-xs text-ink-faint">
                    <tr>
                      <th className="py-2 pr-4 font-medium">Article</th>
                      <th className="py-2 pr-4 font-medium">Site</th>
                      <th className="py-2 pr-4 text-right font-medium">LLM</th>
                      <th className="py-2 pr-4 text-right font-medium">Images</th>
                      <th className="py-2 pr-4 text-right font-medium">Data</th>
                      <th className="py-2 text-right font-medium">Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topArticles.map(([aid, row]) => {
                      const art = artById.get(aid);
                      return (
                        <tr key={aid} className="border-t border-line/60">
                          <td className="max-w-[280px] truncate py-2 pr-4 text-xs">
                            {art ? (
                              <Link
                                href={`/articles/${aid}`}
                                className="text-accent hover:underline"
                                title={`#${aid} ${art.title}`}
                              >
                                #{aid} {art.title}
                              </Link>
                            ) : (
                              <span className="text-ink-faint" title="Ledger row's article is not in the article index">
                                #{aid} (not in article index)
                              </span>
                            )}
                          </td>
                          <td className="py-2 pr-4 font-mono text-[11px] text-ink-faint">
                            {art?.site_slug ?? "—"}
                          </td>
                          <td className="py-2 pr-4 text-right font-mono text-xs text-gold">{fmtCost(row.llm)}</td>
                          <td className="py-2 pr-4 text-right font-mono text-xs text-gold">{fmtCost(row.image)}</td>
                          <td className="py-2 pr-4 text-right font-mono text-xs text-gold">{fmtCost(row.data)}</td>
                          <td className="py-2 text-right font-mono text-xs text-gold">{fmtCost(row.total)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </SectionCard>

          <SectionCard title={`By site (${siteRows.length})`}>
            {siteRows.length === 0 ? (
              <p className="text-sm text-ink-faint">No site-attributed spend in the window yet.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-left text-xs text-ink-faint">
                    <tr>
                      <th className="py-2 pr-4 font-medium">Site</th>
                      <th className="py-2 pr-4 text-right font-medium">Articles with spend</th>
                      <th className="py-2 text-right font-medium">Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {siteRows.map(([slug, rec]) => (
                      <tr key={slug} className="border-t border-line/60">
                        <td className="py-2 pr-4 font-mono text-xs text-ink-dim">{slug}</td>
                        <td className="py-2 pr-4 text-right font-mono text-xs text-ink-faint">
                          {rec.articles}
                        </td>
                        <td className="py-2 text-right font-mono text-xs text-gold">{fmtCost(rec.total)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </SectionCard>

          <SectionCard
            title={`Usage by model (${modelRows.length})`}
            right={
              totalCalls > 0 ? (
                <span className="font-mono text-[11px] text-ink-faint">
                  {totalCalls} calls · {totalFailed} not ok
                </span>
              ) : undefined
            }
          >
            {modelRows.length === 0 ? (
              <p className="text-sm text-ink-faint">No usage rows in the window.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-left text-xs text-ink-faint">
                    <tr>
                      <th className="py-2 pr-4 font-medium">Model</th>
                      <th className="py-2 pr-4 font-medium">Lane</th>
                      <th className="py-2 pr-4 font-medium">Share</th>
                      <th className="py-2 pr-4 text-right font-medium">Calls</th>
                      <th className="py-2 text-right font-medium">Not ok</th>
                    </tr>
                  </thead>
                  <tbody>
                    {modelRows.map((r) => (
                      <tr key={`${r.lane}:${r.model}`} className="border-t border-line/60">
                        <td
                          className="max-w-[300px] truncate py-2 pr-4 font-mono text-xs text-ink-dim"
                          title={r.model}
                        >
                          {r.model}
                        </td>
                        <td className="py-2 pr-4">
                          <span className="rounded border border-line px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-ink-faint">
                            {r.lane}
                          </span>
                        </td>
                        <td className="py-2 pr-4">
                          <div className="h-1.5 w-24 overflow-hidden rounded-full bg-surface/70">
                            <div
                              className="h-full rounded-full bg-accent"
                              style={{ width: `${maxCalls > 0 ? (r.calls / maxCalls) * 100 : 0}%` }}
                            />
                          </div>
                        </td>
                        <td className="py-2 pr-4 text-right font-mono text-xs text-ink-dim">{r.calls}</td>
                        <td
                          className={`py-2 text-right font-mono text-xs ${
                            r.failed > 0 ? "text-rose-300" : "text-ink-faint"
                          }`}
                        >
                          {r.failed > 0 ? r.failed : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </SectionCard>

          <p className="text-[11px] leading-5 text-ink-faint">
            Windows: newest 500 cost rows + 500 usage rows{site ? ", filtered to this site via its articles" : ""}.
            Ledger rollup rows (kind <span className="font-mono">total</span>) are excluded from sums so nothing
            double-counts; page raw rows on{" "}
            <Link href="/logs" className="text-accent hover:underline">
              Logs
            </Link>
            .
          </p>
        </>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  sub,
  strong = false,
}: {
  label: string;
  value: string;
  sub?: string;
  strong?: boolean;
}) {
  return (
    <div className="rounded-xl border border-line bg-card px-4 py-3">
      <p className="text-[11px] uppercase tracking-widest text-ink-faint/80">{label}</p>
      <p className={`mt-1 font-mono text-xl ${strong ? "text-gold" : "text-ink"}`}>{value}</p>
      {sub ? <p className="mt-0.5 text-[11px] text-ink-faint">{sub}</p> : null}
    </div>
  );
}
