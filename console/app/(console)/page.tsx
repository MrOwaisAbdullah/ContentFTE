import Link from "next/link";
import {
  ArticleList,
  BriefPeek,
  engine,
  QueueView,
  SiteHealth,
  SiteList,
} from "@/lib/engine";
import { Alert, Empty, Pill, SectionCard, checkTier } from "@/lib/ui";
import { CircleX, Info, TriangleAlert } from "lucide-react";

export const dynamic = "force-dynamic";

const CHECK_ICONS = { fail: CircleX, warn: TriangleAlert, info: Info } as const;
const CHECK_CLASSES = {
  fail: "text-rose-400",
  warn: "text-amber-300",
  info: "text-ink-faint",
} as const;

export default async function DashboardPage() {
  let sites: SiteList = { sites: [], count: 0 };
  let queue: QueueView | null = null;
  let brief: BriefPeek | null = null;
  let articles: ArticleList | null = null;
  let health: (SiteHealth | null)[] = [];
  let error = "";
  try {
    sites = await engine<SiteList>("/sites");
    if (sites.sites.length > 0) {
      const slug = sites.sites[0].slug;
      queue = await engine<QueueView>(`/sites/${encodeURIComponent(slug)}/queue?limit=5`);
      brief = await engine<BriefPeek>(`/sites/${encodeURIComponent(slug)}/brief`);
      articles = await engine<ArticleList>("/articles?limit=8");
      // Live probes run per site in parallel; a failed/unreachable site
      // renders as a warning row instead of failing the whole dashboard.
      health = await Promise.all(
        sites.sites.map((s) =>
          engine<SiteHealth>(`/sites/${encodeURIComponent(s.slug)}/health`).catch(
            () => null,
          ),
        ),
      );
    }
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <div className="space-y-8">
      <h1 className="text-xl font-semibold tracking-tight">Dashboard</h1>
      {error ? <Alert tone="error">Engine unreachable: {error}</Alert> : null}

      <section className="grid gap-4 sm:grid-cols-2">
        <SectionCard title="Sites">
          {sites.sites.length === 0 ? (
            <p className="text-sm text-ink-faint">No sites yet.</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {sites.sites.map((s) => (
                <li key={s.id} className="flex items-center justify-between">
                  <span className="text-ink-dim">
                    <span className="text-ink">{s.name || s.slug}</span>{" "}
                    <span className="text-ink-faint">({s.site_type})</span>
                  </span>
                  <a
                    href={s.base_url || "#"}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs text-accent hover:text-accent-strong hover:underline"
                  >
                    {s.base_url}
                  </a>
                </li>
              ))}
            </ul>
          )}
        </SectionCard>

        <SectionCard
          title="Keyword counts"
          right={
            <Link href="/articles/keywords" className="text-xs text-accent hover:text-accent-strong hover:underline">
              ledger →
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
            <p className="mt-4 text-xs text-ink-dim">
              Next briefable: <span className="rounded bg-surface px-1.5 py-0.5 text-ink">{brief.keyword}</span>
            </p>
          ) : null}
        </SectionCard>
      </section>

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
                    {h.checks.length > 6 ? <li className="text-ink-faint">… +{h.checks.length - 6} more</li> : null}
                  </ul>
                </div>
              );
            })}
          </div>
        </SectionCard>
      ) : null}

      <SectionCard
        title="Recent articles"
        right={
          <Link href="/articles" className="text-xs text-accent hover:text-accent-strong hover:underline">
            all →
          </Link>
        }
      >
        {!articles || articles.articles.length === 0 ? (
          <Empty
            title="No articles yet"
            hint="Add a keyword on the ledger — the engine briefs, researches and writes it end-to-end."
            cta={{ href: "/articles/keywords", label: "Open keyword ledger" }}
          />
        ) : (
          <table className="w-full text-sm">
            <tbody>
              {articles.articles.map((a) => (
                <tr key={a.id} className="border-t border-line first:border-t-0">
                  <td className="py-2.5 pr-4">
                    <Link href={`/articles/${a.id}`} className="hover:text-accent">
                      {a.title || `#${a.id}`}
                    </Link>
                  </td>
                  <td className="hidden py-2.5 pr-4 text-xs text-ink-faint sm:table-cell">{a.site_slug}</td>
                  <td className="py-2.5 text-right">
                    <Pill status={a.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </SectionCard>
    </div>
  );
}
