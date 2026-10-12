import Link from "next/link";
import { engine, QueueView, SiteList } from "@/lib/engine";
import { createArticleAction } from "@/actions/articles";

export const dynamic = "force-dynamic";

export default async function KeywordsPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string; site?: string; err?: string }>;
}) {
  const { status = "", site = "", err = "" } = await searchParams;
  let slug = site;
  let error = "";
  let queue: QueueView | null = null;
  try {
    if (!slug) {
      const sites = await engine<SiteList>("/sites");
      slug = sites.sites[0]?.slug || "";
    }
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
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">
          Keywords (ledger sheet) {slug ? `— ${slug}` : ""}
        </h1>
        <Link href="/stages" className="text-xs text-sky-400 hover:underline">
          run research stage to fill →
        </Link>
      </div>

      {err ? (
        <div className="rounded-md border border-red-900 bg-red-950/50 px-4 py-3 text-sm text-red-300">
          {err}
        </div>
      ) : null}
      {error ? (
        <div className="rounded-md border border-red-900 bg-red-950/50 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      ) : null}

      <form
        action={createArticleAction}
        className="flex flex-wrap items-end gap-3 rounded-lg border border-slate-800 bg-slate-950/40 p-4"
      >
        <input type="hidden" name="site" value={slug} />
        <div className="flex min-w-56 flex-col gap-1">
          <label htmlFor="kw" className="text-xs text-slate-400">
            keyword (ledger row)
          </label>
          <input
            id="kw"
            name="keyword"
            required
            disabled={!slug}
            placeholder="best espresso machine under 500"
            className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white placeholder:text-slate-600 focus:border-sky-600 focus:outline-none disabled:opacity-50"
          />
        </div>
        <div className="flex min-w-44 flex-col gap-1">
          <label htmlFor="ttl" className="text-xs text-slate-400">
            title (optional)
          </label>
          <input
            id="ttl"
            name="title"
            disabled={!slug}
            placeholder="defaults to the keyword"
            className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white placeholder:text-slate-600 focus:border-sky-600 focus:outline-none disabled:opacity-50"
          />
        </div>
        <button
          type="submit"
          disabled={!slug}
          className="rounded-md bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50"
        >
          add
        </button>
        <span className="text-xs text-slate-500">
          creates the ledger row + a briefed article, then opens it — Generate →
          Approve → Publish continue on the detail screen
        </span>
      </form>

      <div className="flex flex-wrap gap-2 text-xs">
        <Link
          href={`/articles/keywords?site=${encodeURIComponent(slug)}`}
          className={`rounded-full border px-3 py-1 ${!status ? "border-sky-700 text-sky-300" : "border-slate-700 text-slate-400"}`}
        >
          all
        </Link>
        {statuses.map((s) => (
          <Link
            key={s}
            href={`/articles/keywords?site=${encodeURIComponent(slug)}&status=${encodeURIComponent(s)}`}
            className={`rounded-full border px-3 py-1 ${status === s ? "border-sky-700 text-sky-300" : "border-slate-700 text-slate-400"}`}
          >
            {s} ({queue?.counts[s]})
          </Link>
        ))}
      </div>

      {!queue || queue.queue.length === 0 ? (
        <p className="text-sm text-slate-500">
          No keyword rows{status ? ` with status “${status}”` : ""}.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-800">
          <table className="w-full text-sm">
            <thead className="bg-slate-900 text-left text-xs text-slate-400">
              <tr>
                <th className="px-4 py-2">Keyword</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2">Intent</th>
                <th className="px-4 py-2 text-right">Volume</th>
                <th className="px-4 py-2 text-right">Diff</th>
                <th className="px-4 py-2 text-right">Priority</th>
                <th className="px-4 py-2">Added</th>
              </tr>
            </thead>
            <tbody>
              {queue.queue.map((r) => (
                <tr key={r.id} className="border-t border-slate-800/80">
                  <td className="px-4 py-2">{r.keyword}</td>
                  <td className="px-4 py-2 text-xs text-slate-400">{r.status}</td>
                  <td className="px-4 py-2 text-xs text-slate-400">{r.intent}</td>
                  <td className="px-4 py-2 text-right">{r.volume || "—"}</td>
                  <td className="px-4 py-2 text-right">{r.difficulty || "—"}</td>
                  <td className="px-4 py-2 text-right text-sky-400">
                    {r.priority_score?.toFixed?.(2) ?? r.priority_score}
                  </td>
                  <td className="px-4 py-2 text-xs text-slate-500">
                    {r.added_at ? r.added_at.slice(0, 10) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
