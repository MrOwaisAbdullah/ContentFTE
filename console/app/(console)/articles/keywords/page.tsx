import Link from "next/link";
import { engine, QueueView, SiteList } from "@/lib/engine";
import { createArticleAction } from "@/actions/articles";
import { Alert, Empty, PageHeader, Pill, fmtDate, fmtScore } from "@/lib/ui";
import { PendingButton } from "@/lib/interactive";

export const dynamic = "force-dynamic";

export default async function KeywordsPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string; site?: string; err?: string }>;
}) {
  const { status = "", site = "", err = "" } = await searchParams;
  let slug = site;
  let error = "";
  let sites: SiteList = { sites: [], count: 0 };
  let queue: QueueView | null = null;
  try {
    sites = await engine<SiteList>("/sites");
    if (!slug) slug = sites.sites[0]?.slug || "";
    if (slug) {
      const qs = new URLSearchParams({ limit: "200" });
      if (status) qs.set("status", status);
      queue = await engine<QueueView>(`/sites/${encodeURIComponent(slug)}/queue?${qs}`);
    }
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  const statuses = queue ? Object.keys(queue.counts) : [];

  return (
    <div className="space-y-6">
      <PageHeader
        title={`Keywords — ledger sheet ${slug ? `· ${slug}` : ""}`}
        sub="the workbook's keyword ledger, engine-side"
      />

      {err ? <Alert tone="error">{err}</Alert> : null}
      {error ? <Alert tone="error">Engine unreachable: {error}</Alert> : null}

      <form
        action={createArticleAction}
        className="flex flex-wrap items-end gap-3 rounded-xl border border-line bg-card p-4"
      >
        <input type="hidden" name="site" value={slug} />
        <div className="flex min-w-56 flex-col gap-1">
          <label htmlFor="kw" className="text-xs text-ink-dim">
            keyword (ledger row)
          </label>
          <input
            id="kw"
            name="keyword"
            required
            disabled={!slug}
            placeholder="best espresso machine under 500"
            className="rounded-md border border-line bg-page px-3 py-2 text-sm text-ink placeholder:text-ink-faint/70 focus:border-accent"
          />
        </div>
        <div className="flex min-w-44 flex-col gap-1">
          <label htmlFor="ttl" className="text-xs text-ink-dim">
            title (optional)
          </label>
          <input
            id="ttl"
            name="title"
            disabled={!slug}
            placeholder="defaults to the keyword"
            className="rounded-md border border-line bg-page px-3 py-2 text-sm text-ink placeholder:text-ink-faint/70 focus:border-accent"
          />
        </div>
        <PendingButton
          disabled={!slug}
          pendingLabel="Adding…"
          className="inline-flex items-center gap-1.5 rounded-md bg-accent-strong px-4 py-2 text-sm font-medium text-page hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
        >
          add
        </PendingButton>
        <span className="text-xs text-ink-faint">
          creates the ledger row + a briefed article, then opens it — Generate →
          Approve → Publish continue on the detail screen
        </span>
      </form>

      <div className="flex flex-wrap gap-2 text-xs">
        <Link
          href={`/articles/keywords?site=${encodeURIComponent(slug)}`}
          className={`rounded-full border px-3 py-1 transition-colors ${
            !status
              ? "border-accent/60 bg-accent/10 text-accent"
              : "border-line bg-page text-ink-faint hover:border-ink-faint hover:text-ink"
          }`}
        >
          all
        </Link>
        {statuses.map((s) => (
          <Link
            key={s}
            href={`/articles/keywords?site=${encodeURIComponent(slug)}&status=${encodeURIComponent(s)}`}
            className={`rounded-full border px-3 py-1 transition-colors ${
              status === s
                ? "border-accent/60 bg-accent/10 text-accent"
                : "border-line bg-page text-ink-faint hover:border-ink-faint hover:text-ink"
            }`}
          >
            {s} ({queue?.counts[s]})
          </Link>
        ))}
      </div>

      {!queue || queue.queue.length === 0 ? (
        <Empty
          title={`No keyword rows${status ? ` with status “${status}”` : ""}`}
          hint="Add a keyword above, or run the research stage to pull topics into findings."
          cta={{ href: "/stages", label: "Run stages" }}
        />
      ) : (
        <div className="overflow-x-auto rounded-xl border border-line bg-card">
          <table className="w-full text-sm">
            <thead className="border-b border-line text-left text-xs text-ink-faint">
              <tr>
                <th className="px-4 py-2.5">Keyword</th>
                <th className="px-4 py-2.5">Status</th>
                <th className="px-4 py-2.5">Intent</th>
                <th className="px-4 py-2.5 text-right">Volume</th>
                <th className="px-4 py-2.5 text-right">Diff</th>
                <th className="px-4 py-2.5 text-right">Priority</th>
                <th className="px-4 py-2.5">Added</th>
              </tr>
            </thead>
            <tbody>
              {queue.queue.map((r) => (
                <tr key={r.id} className="border-t border-line/60 first:border-t-0 hover:bg-surface/40">
                  <td className="px-4 py-2.5 font-medium">{r.keyword}</td>
                  <td className="px-4 py-2.5">
                    <Pill status={r.status} />
                  </td>
                  <td className="px-4 py-2.5 text-xs text-ink-dim">{r.intent}</td>
                  <td className="px-4 py-2.5 text-right text-xs">{r.volume || "—"}</td>
                  <td className="px-4 py-2.5 text-right text-xs">{r.difficulty || "—"}</td>
                  <td className="px-4 py-2.5 text-right font-mono text-xs text-accent">
                    {fmtScore(r.priority_score, 2)}
                  </td>
                  <td className="px-4 py-2.5 text-xs text-ink-faint">{fmtDate(r.added_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
