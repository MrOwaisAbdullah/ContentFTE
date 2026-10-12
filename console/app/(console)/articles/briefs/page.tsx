import { engine, BriefsView, SiteList } from "@/lib/engine";

export const dynamic = "force-dynamic";

export default async function BriefsPage({
  searchParams,
}: {
  searchParams: Promise<{ site?: string }>;
}) {
  const { site = "" } = await searchParams;
  let slug = site;
  let error = "";
  let data: BriefsView | null = null;
  try {
    if (!slug) {
      const sites = await engine<SiteList>("/sites");
      slug = sites.sites[0]?.slug || "";
    }
    if (slug) {
      data = await engine<BriefsView>(`/sites/${encodeURIComponent(slug)}/briefs?limit=200`);
    }
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">
          Briefs (content_briefs sheet) {slug ? `— ${slug}` : ""}
        </h1>
        <span className="text-xs text-slate-500">
          only rows that carry a brief · next briefable stays on the dashboard
        </span>
      </div>

      {error ? (
        <div className="rounded-md border border-red-900 bg-red-950/50 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      ) : null}

      {!data || data.briefs.length === 0 ? (
        <p className="text-sm text-slate-500">No briefs yet.</p>
      ) : (
        <div className="space-y-3">
          {data.briefs.map((b) => (
            <details key={b.id} className="rounded-lg border border-slate-800 bg-slate-900/60 px-4 py-3">
              <summary className="cursor-pointer text-sm">
                <span className="text-slate-200">{b.keyword}</span>{" "}
                <span className="ml-2 text-xs text-slate-500">
                  {b.status} · {b.intent}
                </span>
                {b.summary ? (
                  <span className="ml-3 text-xs text-slate-400">— {b.summary}</span>
                ) : null}
              </summary>
              <div className="mt-3 space-y-3 text-sm">
                <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded border border-slate-800 bg-slate-950 p-3 text-xs text-slate-300">
                  {b.brief}
                </pre>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <h3 className="text-xs font-medium uppercase text-slate-500">FAQs</h3>
                    <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap text-xs text-slate-400">
                      {b.faqs || "—"}
                    </pre>
                  </div>
                  <div>
                    <h3 className="text-xs font-medium uppercase text-slate-500">
                      External Source Links
                    </h3>
                    <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap text-xs text-slate-400">
                      {b.sources || "—"}
                    </pre>
                    {b.secondary_keywords ? (
                      <p className="mt-2 text-xs text-slate-500">
                        secondary: {b.secondary_keywords}
                      </p>
                    ) : null}
                  </div>
                </div>
              </div>
            </details>
          ))}
        </div>
      )}
    </div>
  );
}
