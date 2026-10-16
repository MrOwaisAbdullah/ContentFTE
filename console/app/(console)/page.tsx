import Link from "next/link";
import {
  ArticleList,
  BriefPeek,
  engine,
  LogsView,
  QueueView,
  SiteHealth,
  SiteList,
} from "@/lib/engine";
import { Alert, Empty, Pill, SectionCard, checkTier, fmtCost, fmtDate } from "@/lib/ui";
import { CircleCheck, CircleX, Info, TriangleAlert } from "lucide-react";

export const dynamic = "force-dynamic";

const CHECK_ICONS = { fail: CircleX, warn: TriangleAlert, info: Info } as const;
const CHECK_CLASSES = {
  fail: "text-rose-400",
  warn: "text-amber-300",
  info: "text-ink-faint",
} as const;

/** Monday 00:00 UTC of the current week — the WTD cost window. */
function startOfWeekUTC(now = new Date()): Date {
  const day = (now.getUTCDay() + 6) % 7; // Mon=0 … Sun=6
  return new Date(
    Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() - day),
  );
}

function parseStamp(v: string | null): Date | null {
  if (!v) return null;
  const iso = /(Z|[+-]\d\d:?\d\d)$/.test(v) ? v : `${v}Z`;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

function Kpi({
  label,
  value,
  sub,
  href,
  tone = "",
}: {
  label: string;
  value: string;
  sub: string;
  href: string;
  tone?: string;
}) {
  return (
    <Link
      href={href}
      className="rounded-xl border border-line bg-card px-4 py-3.5 transition-colors hover:border-ink-faint/60"
    >
      <p className="text-xs text-ink-faint">{label}</p>
      <p className={`mt-1.5 font-mono text-2xl font-semibold leading-none ${tone || "text-ink"}`}>
        {value}
      </p>
      <p className="mt-1.5 text-[11px] text-ink-faint/80">{sub}</p>
    </Link>
  );
}

export default async function DashboardPage() {
  let sites: SiteList = { sites: [], count: 0 };
  let queue: QueueView | null = null;
  let brief: BriefPeek | null = null;
  let articles: ArticleList | null = null;
  let logs: LogsView | null = null;
  let health: (SiteHealth | null)[] = [];
  let error = "";
  try {
    sites = await engine<SiteList>("/sites");
    if (sites.sites.length > 0) {
      const slug = sites.sites[0].slug;
      [queue, brief, articles, logs, health] = await Promise.all([
        engine<QueueView>(`/sites/${encodeURIComponent(slug)}/queue?limit=5`).catch(() => null),
        engine<BriefPeek>(`/sites/${encodeURIComponent(slug)}/brief`).catch(() => null),
        engine<ArticleList>("/articles?limit=500").catch(() => null),
        engine<LogsView>("/logs?kind=cost&limit=500").catch(() => null),
        // Live probes run per site in parallel; a failed/unreachable site
        // renders as a warning row instead of failing the whole dashboard.
        Promise.all(
          sites.sites.map((s) =>
            engine<SiteHealth>(`/sites/${encodeURIComponent(s.slug)}/health`).catch(() => null),
          ),
        ),
      ]);
    }
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  const all = articles?.articles ?? [];
  const awaiting = all.filter((a) => a.status === "generated" || a.status === "needs_review");
  const reviewQueue = awaiting.slice(0, 6);
  const briefable = health.reduce((n, h) => n + (h?.ledger.briefable ?? 0), 0);
  const published = health.reduce((n, h) => n + (h?.ledger.published ?? 0), 0);

  const weekStart = startOfWeekUTC();
  const costs = logs?.costs ?? [];
  const wtd = costs.reduce((sum, c) => {
    const ts = parseStamp(c.created_at);
    return ts && ts >= weekStart ? sum + Number(c.amount_usd || 0) : sum;
  }, 0);
  const wtdFmt = logs ? (wtd >= 1 ? `$${wtd.toFixed(2)}` : `$${wtd.toFixed(4)}`) : "—";

  return (
    <div className="space-y-8">
      <h1 className="text-xl font-semibold tracking-tight">Overview</h1>
      {error ? <Alert tone="error">Engine unreachable: {error}</Alert> : null}

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Key metrics">
        <Kpi
          label="Needs your review"
          value={String(awaiting.length)}
          sub="generated or flagged — approve or bounce"
          href={"/articles?status=generated"}
          tone={awaiting.length > 0 ? "text-gold" : "text-ink"}
        />
        <Kpi
          label="Briefable now"
          value={String(briefable)}
          sub="ledger rows ready for the brief stage"
          href="/articles/keywords"
          tone={briefable > 0 ? "text-accent" : "text-ink"}
        />
        <Kpi
          label="Published"
          value={String(published)}
          sub="live posts across all sites"
          href="/articles?status=published"
        />
        <Kpi
          label="Cost this week"
          value={wtdFmt}
          sub="LLM + image spend since Monday"
          href="/logs?kind=cost"
          tone="text-gold"
        />
      </section>

      <SectionCard
        title="Needs your review"
        right={
          <Link href="/articles?status=needs_review" className="text-xs text-accent hover:text-accent-strong hover:underline">
            all flagged →
          </Link>
        }
      >
        {reviewQueue.length === 0 ? (
          <p className="flex items-center gap-2 text-sm text-ink-dim">
            <CircleCheck className="h-4 w-4 text-emerald-300" aria-hidden />
            Queue clear — nothing is waiting on a human decision.
          </p>
        ) : (
          <ul className="divide-y divide-line/60">
            {reviewQueue.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center gap-x-3 gap-y-1.5 py-2.5 first:pt-0 last:pb-0">
                <Link href={`/articles/${a.id}`} className="min-w-0 flex-1 truncate text-sm font-medium hover:text-accent">
                  {a.title || `#${a.id}`}
                </Link>
                <span className="font-mono text-xs text-ink-faint">{a.site_slug}</span>
                <Pill status={a.status} />
                <span className="font-mono text-xs text-ink-faint">{fmtDate(a.created_at)}</span>
                <Link
                  href={`/articles/${a.id}`}
                  className="rounded-md border border-line bg-page px-2.5 py-1 text-xs text-ink-dim hover:border-gold/50 hover:text-gold"
                >
                  Review →
                </Link>
              </li>
            ))}
          </ul>
        )}
      </SectionCard>

      {sites.sites.length > 0 ? (
        <SectionCard title="Site health">
          <div className="grid gap-4 sm:grid-cols-2">
            {sites.sites.map((s, i) => {
              const h = health[i];
              if (!h) {
                return (
                  <Alert key={s.id} tone="warn">
                    {s.name || s.slug}: health unreachable
                  </Alert>
                );
              }
              const warnCount = h.checks.filter((c) => checkTier(c) === "warn").length;
              const tier = h.critical.length > 0 ? "fail" : warnCount > 0 ? "watch" : "healthy";
              return (
                <div key={s.id} className="rounded-lg border border-line bg-page px-4 py-3">
                  <div className="mb-2 flex items-center justify-between text-sm">
                    <span className="font-medium text-ink">{s.name || s.slug}</span>
                    <span
                      className={
                        tier === "fail"
                          ? "flex items-center gap-1 text-xs text-rose-300"
                          : tier === "watch"
                            ? "flex items-center gap-1 text-xs text-amber-300"
                            : "flex items-center gap-1 text-xs text-emerald-300"
                      }
                    >
                      <span
                        className={
                          tier === "fail"
                            ? "h-1.5 w-1.5 rounded-full bg-danger"
                            : tier === "watch"
                              ? "h-1.5 w-1.5 rounded-full bg-gold"
                              : "h-1.5 w-1.5 rounded-full bg-emerald-400"
                        }
                        aria-hidden
                      />
                      {tier}
                    </span>
                  </div>
                  <p className="mb-2 text-xs text-ink-faint">
                    ledger: {h.ledger.briefable} briefable · {h.ledger.published} published ·{" "}
                    {h.wp_configured ? "WP config OK" : "WP not configured"}
                  </p>
                  {h.critical.length > 0 ? (
                    <ul className="mb-2 space-y-1 text-xs">
                      {h.critical.map((c) => (
                        <li key={c} className="flex items-start gap-1.5 text-rose-300">
                          <CircleX className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
                          {c}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  <ul className="space-y-1 text-xs">
                    {h.checks.slice(0, 6).map((c) => {
                      const tierC = checkTier(c);
                      const Icon = CHECK_ICONS[tierC];
                      return (
                        <li
                          key={c}
                          className={`flex items-start gap-1.5 ${
                            tierC === "warn" ? "text-amber-300/90" : "text-ink-faint"
                          }`}
                        >
                          <Icon className={`mt-0.5 h-3 w-3 shrink-0 ${CHECK_CLASSES[tierC]}`} aria-hidden />
                          {c}
                        </li>
                      );
                    })}
                    {h.checks.length > 6 ? (
                      <li className="text-ink-faint">… +{h.checks.length - 6} more</li>
                    ) : null}
                  </ul>
                </div>
              );
            })}
          </div>
        </SectionCard>
      ) : null}

      <section className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <SectionCard
          title="Recent articles"
          right={
            <Link href="/articles" className="text-xs text-accent hover:text-accent-strong hover:underline">
              all →
            </Link>
          }
        >
          {all.length === 0 ? (
            <Empty
              title="No articles yet"
              hint="Add a keyword on the ledger — the engine briefs, researches and writes it end-to-end."
              cta={{ href: "/articles/keywords", label: "Open keyword ledger" }}
            />
          ) : (
            <table className="w-full text-sm">
              <tbody>
                {all.slice(0, 8).map((a) => (
                  <tr key={a.id} className="border-t border-line first:border-t-0">
                    <td className="py-2.5 pr-4">
                      <Link href={`/articles/${a.id}`} className="hover:text-accent">
                        {a.title || `#${a.id}`}
                      </Link>
                    </td>
                    <td className="hidden py-2.5 pr-4 font-mono text-xs text-ink-faint sm:table-cell">
                      {a.site_slug}
                    </td>
                    <td className="py-2.5 pr-4 text-right font-mono text-xs text-ink-faint">
                      {fmtCost(a.cost_usd)}
                    </td>
                    <td className="py-2.5 text-right">
                      <Pill status={a.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </SectionCard>

        <SectionCard
          title="Keyword ledger"
          right={
            <Link href="/articles/keywords" className="text-xs text-accent hover:text-accent-strong hover:underline">
              open →
            </Link>
          }
        >
          {!queue ? (
            <p className="text-sm text-ink-faint">—</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {Object.entries(queue.counts).map(([status, n]) => (
                <Link
                  key={status}
                  href={`/articles/keywords?status=${encodeURIComponent(status)}`}
                  className="inline-flex items-center gap-1.5 rounded-full border border-line bg-page px-3 py-1 text-xs text-ink-dim hover:border-ink-faint hover:text-ink"
                >
                  {status} <span className="font-medium text-accent">{n}</span>
                </Link>
              ))}
              {Object.keys(queue.counts).length === 0 ? (
                <p className="text-sm text-ink-faint">Ledger empty.</p>
              ) : null}
            </div>
          )}
          {brief && brief.keyword ? (
            <p className="mt-4 border-t border-line pt-3 text-xs text-ink-dim">
              Next briefable:{" "}
              <span className="rounded bg-surface px-1.5 py-0.5 text-ink">{brief.keyword}</span>
            </p>
          ) : null}
        </SectionCard>
      </section>
    </div>
  );
}
