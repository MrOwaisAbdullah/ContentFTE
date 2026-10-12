import Link from "next/link";
import { engine, QueueView, SiteList } from "@/lib/engine";

export const dynamic = "force-dynamic";

export default async function QueuePage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string; site?: string }>;
}) {
  const { status = "", site = "" } = await searchParams;
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
        <h1 className="text-lg font-semibold">Keyword queue {slug ? `— ${slug}` : ""}</h1>
        <Link href="/stages" className="text-xs text-sky-400 hover:underline">
          run research stage to fill →
        </Link>
      </div>

      {error ? (
        <div className="rounded-md border border-red-900 bg-red-950/50 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      ) : null}

      <div className="flex flex-wrap gap-2 text-xs">
        <Link
          href={`/queue?site=${encodeURIComponent(slug)}`}
          className={`rounded-full border px-3 py-1 ${!status ? "border-sky-700 text-sky-300" : "border-slate-700 text-slate-400"}`}
        >
          all
        </Link>
        {statuses.map((s) => (
          <Link
            key={s}
            href={`/queue?site=${encodeURIComponent(slug)}&status=${encodeURIComponent(s)}`}
            className={`rounded-full border px-3 py-1 ${status === s ? "border-sky-700 text-sky-300" : "border-slate-700 text-slate-400"}`}
          >
            {s} ({queue?.counts[s]})
          </Link>
        ))}
      </div>

      {!queue || queue.queue.length === 0 ? (
        <p className="text-sm text-slate-500">Nothing in the queue{status ? ` with status “${status}”` : ""}.</p>
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
