import Link from "next/link";
import { engine, ResearchView, SiteList } from "@/lib/engine";
import { Alert, Empty, PageHeader, Pill } from "@/lib/ui";
import { SiteSwitcher } from "@/lib/interactive";

export const dynamic = "force-dynamic";

export default async function ResearchPage({
  searchParams,
}: {
  searchParams: Promise<{ site?: string }>;
}) {
  const { site = "" } = await searchParams;
  let slug = site;
  let error = "";
  let sites: SiteList = { sites: [], count: 0 };
  let data: ResearchView | null = null;
  try {
    sites = await engine<SiteList>("/sites");
    if (!slug) slug = sites.sites[0]?.slug || "";
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
      <PageHeader
        title={`Research — research_data sheet ${slug ? `· ${slug}` : ""}`}
        sub="findings pulled from the ledger before briefing"
        right={<SiteSwitcher sites={sites.sites} current={slug} basePath="/articles/research" />}
      />

      {error ? <Alert tone="error">Engine unreachable: {error}</Alert> : null}

      {!data || data.research.length === 0 ? (
        <Empty
          title="No research rows yet"
          hint="Run the research stage — it turns ledger keywords into findings with intent, volume and summaries."
          cta={{ href: "/stages", label: "Run stages" }}
        />
      ) : (
        <div className="overflow-x-auto rounded-xl border border-line bg-card">
          <table className="w-full text-sm">
            <thead className="border-b border-line text-left text-xs text-ink-faint">
              <tr>
                <th className="px-4 py-2.5">Keyword / Topic</th>
                <th className="px-4 py-2.5">Status</th>
                <th className="px-4 py-2.5">Intent</th>
                <th className="px-4 py-2.5 text-right">Volume</th>
                <th className="px-4 py-2.5 text-right">Diff</th>
                <th className="px-4 py-2.5">Generated</th>
                <th className="px-4 py-2.5">Content Summary</th>
                <th className="px-4 py-2.5">Secondary Keywords</th>
              </tr>
            </thead>
            <tbody>
              {data.research.map((r) => (
                <tr key={r.id} className="border-t border-line/60 first:border-t-0 hover:bg-surface/40">
                  <td className="px-4 py-2.5">
                    <span className="font-medium">{r.subject || r.keyword}</span>
                    {r.subject && r.primary_keyword ? (
                      <span className="block font-mono text-xs text-ink-faint">
                        targets: {r.primary_keyword}
                      </span>
                    ) : null}
                  </td>
                  <td className="px-4 py-2.5">
                    <Pill status={r.status} />
                  </td>
                  <td className="px-4 py-2.5 text-xs text-ink-dim">{r.intent}</td>
                  <td className="px-4 py-2.5 text-right text-xs">{r.volume || "—"}</td>
                  <td className="px-4 py-2.5 text-right text-xs">{r.difficulty || "—"}</td>
                  <td className="px-4 py-2.5 text-xs">
                    {r.generated ? (
                      <span className="font-medium text-emerald-300">yes</span>
                    ) : (
                      <span className="text-ink-faint">no</span>
                    )}
                  </td>
                  <td className="max-w-md truncate px-4 py-2.5 text-xs text-ink-dim" title={r.summary}>
                    {r.summary || "—"}
                  </td>
                  <td className="max-w-40 truncate px-4 py-2.5 font-mono text-xs text-ink-faint" title={r.secondary_keywords}>
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
