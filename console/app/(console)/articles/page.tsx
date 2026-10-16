import Link from "next/link";
import { engine, ArticleList } from "@/lib/engine";
import { Alert, Empty, PageHeader, Pill, fmtCost, fmtDate, fmtScore } from "@/lib/ui";
import { FileText } from "lucide-react";

export const dynamic = "force-dynamic";

const STATUSES = ["", "briefed", "generated", "approved", "needs_review", "published"];

export default async function ArticlesPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string; err?: string }>;
}) {
  const { status = "", err = "" } = await searchParams;
  let list: ArticleList | null = null;
  let error = "";
  try {
    const qs = new URLSearchParams({ limit: "200" });
    if (status) qs.set("status", status);
    list = await engine<ArticleList>(`/articles?${qs}`);
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Content"
        sub="generated_posts + approved_unpublished — quality score and summary from the sheet columns"
      />

      {err ? <Alert tone="error">{err}</Alert> : null}
      {error ? <Alert tone="error">Engine unreachable: {error}</Alert> : null}

      <div className="flex flex-wrap gap-2 text-xs">
        {STATUSES.map((s) => (
          <Link
            key={s || "all"}
            href={s ? `/articles?status=${s}` : "/articles"}
            className={`rounded-full border px-3 py-1 transition-colors ${
              status === s
                ? "border-accent/60 bg-accent/10 text-accent"
                : "border-line bg-page text-ink-faint hover:border-ink-faint hover:text-ink"
            }`}
          >
            {s || "all"}
          </Link>
        ))}
      </div>

      {!list || list.articles.length === 0 ? (
        <Empty
          icon={FileText}
          title={status ? `No ${status} articles` : "No articles yet"}
          hint="Add a keyword on the ledger to create a briefed article, or run the content stage to fill the pipeline."
          cta={{ href: "/articles/keywords", label: "Add a keyword" }}
        />
      ) : (
        <div className="overflow-x-auto rounded-xl border border-line bg-card">
          <table className="w-full text-sm">
            <thead className="border-b border-line text-left text-xs text-ink-faint">
              <tr>
                <th className="px-4 py-2.5">Title</th>
                <th className="px-4 py-2.5">Site</th>
                <th className="px-4 py-2.5">Status</th>
                <th className="px-4 py-2.5 text-right">Quality</th>
                <th className="px-4 py-2.5">Summary</th>
                <th className="px-4 py-2.5">Created</th>
                <th className="px-4 py-2.5 text-right">Cost</th>
              </tr>
            </thead>
            <tbody>
              {list.articles.map((a) => (
                <tr key={a.id} className="border-t border-line/60 first:border-t-0 hover:bg-surface/40">
                  <td className="max-w-xs truncate px-4 py-2.5">
                    <Link href={`/articles/${a.id}`} className="font-medium hover:text-accent">
                      {a.title || `#${a.id}`}
                    </Link>
                  </td>
                  <td className="px-4 py-2.5 font-mono text-xs text-ink-faint">{a.site_slug}</td>
                  <td className="px-4 py-2.5">
                    <Pill status={a.status} />
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono text-xs text-ink-dim">
                    {fmtScore(a.quality)}
                  </td>
                  <td
                    className="max-w-sm truncate px-4 py-2.5 text-xs text-ink-dim"
                    title={a.summary}
                  >
                    {a.summary || "—"}
                  </td>
                  <td className="px-4 py-2.5 text-xs text-ink-faint">{fmtDate(a.created_at)}</td>
                  <td className="px-4 py-2.5 text-right font-mono text-xs text-ink-faint">
                    {fmtCost(a.cost_usd)}
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
