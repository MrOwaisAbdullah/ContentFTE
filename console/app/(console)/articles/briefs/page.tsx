import Link from "next/link";
import { engine, BriefsView, SiteList } from "@/lib/engine";
import { Alert, Empty, PageHeader, Pill } from "@/lib/ui";
import { SiteSwitcher } from "@/lib/interactive";
import { ScrollText } from "lucide-react";

export const dynamic = "force-dynamic";

export default async function BriefsPage({
  searchParams,
}: {
  searchParams: Promise<{ site?: string }>;
}) {
  const { site = "" } = await searchParams;
  let slug = site;
  let error = "";
  let sites: SiteList = { sites: [], count: 0 };
  let data: BriefsView | null = null;
  try {
    sites = await engine<SiteList>("/sites");
    if (!slug) slug = sites.sites[0]?.slug || "";
    if (slug) {
      data = await engine<BriefsView>(`/sites/${encodeURIComponent(slug)}/briefs?limit=200`);
    }
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title={`Briefs — content_briefs sheet ${slug ? `· ${slug}` : ""}`}
        sub="only rows that carry a brief · next briefable stays on the dashboard"
        right={<SiteSwitcher sites={sites.sites} current={slug} basePath="/articles/briefs" />}
      />

      {error ? <Alert tone="error">Engine unreachable: {error}</Alert> : null}

      {!data || data.briefs.length === 0 ? (
        <Empty
          icon={ScrollText}
          title="No briefs yet"
          hint="Run the brief stage — it turns the next research finding into a full content brief with FAQs and sources."
          cta={{ href: "/stages", label: "Run stages" }}
        />
      ) : (
        <div className="space-y-3">
          {data.briefs.map((b) => (
            <details key={b.id} className="group rounded-xl border border-line bg-card px-4 py-3 open:bg-card">
              <summary className="cursor-pointer list-none text-sm [&::-webkit-details-marker]:hidden">
                <span className="font-medium text-ink">{b.keyword}</span>{" "}
                <Pill status={b.status} />
                <span className="ml-1 text-xs text-ink-dim">{b.intent}</span>
                {b.summary ? (
                  <span className="ml-2 text-xs text-ink-faint">— {b.summary}</span>
                ) : null}
              </summary>
              <div className="mt-3 space-y-3 text-sm">
                <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-lg border border-line bg-page p-3 text-xs text-ink-dim">
                  {b.brief}
                </pre>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <h3 className="text-xs font-medium uppercase tracking-wide text-ink-faint">FAQs</h3>
                    <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap text-xs text-ink-dim">
                      {b.faqs || "—"}
                    </pre>
                  </div>
                  <div>
                    <h3 className="text-xs font-medium uppercase tracking-wide text-ink-faint">
                      External Source Links
                    </h3>
                    <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap text-xs text-ink-dim">
                      {b.sources || "—"}
                    </pre>
                    {b.secondary_keywords ? (
                      <p className="mt-2 text-xs text-ink-faint">
                        secondary: <span className="font-mono">{b.secondary_keywords}</span>
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
