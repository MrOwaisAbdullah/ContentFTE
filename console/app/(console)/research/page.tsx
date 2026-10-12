import Link from "next/link";
import { engine, ResearchView, SiteList } from "@/lib/engine";

export const dynamic = "force-dynamic";

export default async function ResearchPage({
  searchParams,
}: {
  searchParams: Promise<{ site?: string }>;
}) {
  const { site = "" } = await searchParams;
  let slug = site;
  let error = "";
  let data: ResearchView | null = null;
  try {
    if (!slug) {
      const sites = await engine<SiteList>("/sites");
      slug = sites.sites[0]?.slug || "";
    }
    if (slug) {
      data = await engine<ResearchView>(
        `/sites/${encodeURIComponent(slug)}/research?limit=200`,
      );
    }
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">
          Research (research_data sheet) {slug ? `— ${slug}` : ""}
        </h1>
        <Link href="/stages" className="text-xs text-sky-400 hover:underline">
          run research stage to fill →
        </Link>
      </div>

      {error ? (
        <div className="rounded-md border border-red-900 bg-red-950/50 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      ) : null}

      {!data || data.research.length === 0 ? (
        <p className="text-sm text-slate-500">No research rows yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-800">
          <table className="w-full text-sm">
            <thead className="bg-slate-900 text-left text-xs text-slate-400">
              <tr>
                <th className="px-4 py-2">Keyword / Topic</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2">Intent</th>
                <th className="px-4 py-2 text-right">Volume</th>
                <th className="px-4 py-2 text-right">Diff</th>
                <th className="px-4 py-2">Generated</th>
                <th className="px-4 py-2">Content Summary</th>
                <th className="px-4 py-2">Secondary Keywords</th>
              </tr>
            </thead>
            <tbody>
              {data.research.map((r) => (
                <tr key={r.id} className="border-t border-slate-800/80">
                  <td className="px-4 py-2">
                    {r.subject || r.keyword}
                    {r.subject && r.primary_keyword ? (
                      <span className="block text-xs text-slate-500">
                        targets: {r.primary_keyword}
                      </span>
                    ) : null}
                  </td>
                  <td className="px-4 py-2 text-xs text-slate-400">{r.status}</td>
                  <td className="px-4 py-2 text-xs text-slate-400">{r.intent}</td>
                  <td className="px-4 py-2 text-right">{r.volume || "—"}</td>
                  <td className="px-4 py-2 text-right">{r.difficulty || "—"}</td>
                  <td className="px-4 py-2 text-xs">
                    {r.generated ? (
                      <span className="text-emerald-400">yes</span>
                    ) : (
                      <span className="text-slate-500">no</span>
                    )}
                  </td>
                  <td className="max-w-md truncate px-4 py-2 text-xs text-slate-400" title={r.summary}>
                    {r.summary || "—"}
                  </td>
                  <td className="max-w-40 truncate px-4 py-2 text-xs text-slate-500" title={r.secondary_keywords}>
                    {r.secondary_keywords || "—"}
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
