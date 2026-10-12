import Link from "next/link";
import {
  ArticleList,
  BriefPeek,
  engine,
  QueueView,
  SiteHealth,
  SiteList,
} from "@/lib/engine";

export const dynamic = "force-dynamic";

function errBox(msg: string) {
  return (
    <div className="rounded-md border border-red-900 bg-red-950/50 px-4 py-3 text-sm text-red-300">
      Engine unreachable: {msg}
    </div>
  );
}

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
      <h1 className="text-lg font-semibold">Dashboard</h1>
      {error ? errBox(error) : null}

      <section className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-lg border border-slate-800 bg-slate-900 p-5">
          <h2 className="mb-3 text-sm font-medium text-slate-400">Sites</h2>
          {sites.sites.length === 0 ? (
            <p className="text-sm text-slate-500">No sites yet.</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {sites.sites.map((s) => (
                <li key={s.id} className="flex items-center justify-between">
                  <span>
                    {s.name || s.slug}{" "}
                    <span className="text-slate-500">({s.site_type})</span>
                  </span>
                  <a
                    href={s.base_url || "#"}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs text-sky-400 hover:underline"
                  >
                    {s.base_url}
                  </a>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="rounded-lg border border-slate-800 bg-slate-900 p-5">
          <h2 className="mb-3 text-sm font-medium text-slate-400">
            Keyword counts{" "}
            <Link href="/articles/keywords" className="text-xs text-sky-400 hover:underline">
              ledger →
            </Link>
          </h2>
          {!queue ? (
            <p className="text-sm text-slate-500">—</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {Object.entries(queue.counts).map(([status, n]) => (
                <Link
                  key={status}
                  href={`/articles/keywords?status=${encodeURIComponent(status)}`}
                  className="rounded-full border border-slate-700 bg-slate-950 px-3 py-1 text-xs"
                >
                  {status} <span className="text-sky-400">{n}</span>
                </Link>
              ))}
              {Object.keys(queue.counts).length === 0 ? (
                <p className="text-sm text-slate-500">Ledger empty.</p>
              ) : null}
            </div>
          )}
          {brief && brief.keyword ? (
            <p className="mt-4 text-xs text-slate-400">
              Next briefable: <span className="text-slate-200">{brief.keyword}</span>
            </p>
          ) : null}
        </div>
      </section>

      {sites.sites.length > 0 ? (
        <section className="rounded-lg border border-slate-800 bg-slate-900 p-5">
          <h2 className="mb-3 text-sm font-medium text-slate-400">Site health</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            {sites.sites.map((s, i) => {
              const h = health[i];
              if (!h) {
                return (
                  <div key={s.id} className="rounded-md border border-amber-900 bg-amber-950/40 px-4 py-3 text-sm text-amber-300">
                    {s.name || s.slug}: health unreachable
                  </div>
                );
              }
              return (
                <div key={s.id} className="rounded-md border border-slate-800 bg-slate-950 px-4 py-3">
                  <div className="mb-2 flex items-center justify-between text-sm">
                    <span className="text-slate-200">{s.name || s.slug}</span>
                    <span className={h.ok ? "text-emerald-400" : "text-red-400"}>
                      {h.ok ? "healthy" : "attention"}
                    </span>
                  </div>
                  <p className="mb-2 text-xs text-slate-500">
                    ledger: {h.ledger.briefable} briefable · {h.ledger.published} published ·{" "}
                    {h.wp_configured ? "WP config OK" : "WP not configured"}
                  </p>
                  {h.critical.length > 0 ? (
                    <ul className="mb-2 space-y-1 text-xs text-red-400">
                      {h.critical.map((c) => (
                        <li key={c}>● {c}</li>
                      ))}
                    </ul>
                  ) : null}
                  <ul className="space-y-0.5 text-xs text-slate-500">
                    {h.checks.slice(0, 6).map((c) => (
                      <li key={c}>{c}</li>
                    ))}
                    {h.checks.length > 6 ? <li>… +{h.checks.length - 6} more</li> : null}
                  </ul>
                </div>
              );
            })}
          </div>
        </section>
      ) : null}

      <section className="rounded-lg border border-slate-800 bg-slate-900 p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-medium text-slate-400">Recent articles</h2>
          <Link href="/articles" className="text-xs text-sky-400 hover:underline">
            all →
          </Link>
        </div>
        {!articles || articles.articles.length === 0 ? (
          <p className="text-sm text-slate-500">No articles yet.</p>
        ) : (
          <table className="w-full text-sm">
            <tbody>
              {articles.articles.map((a) => (
                <tr key={a.id} className="border-t border-slate-800">
                  <td className="py-2 pr-4">
                    <Link href={`/articles/${a.id}`} className="hover:text-sky-300">
                      {a.title || `#${a.id}`}
                    </Link>
                  </td>
                  <td className="py-2 pr-4 text-xs text-slate-500">{a.site_slug}</td>
                  <td className="py-2 text-right">
                    <StatusBadge status={a.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const color =
    status === "published"
      ? "text-emerald-400"
      : status === "approved"
        ? "text-sky-400"
        : status === "needs_review"
          ? "text-amber-400"
          : "text-slate-400";
  return <span className={`text-xs ${color}`}>{status}</span>;
}
