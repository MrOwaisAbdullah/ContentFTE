import Link from "next/link";
import { engine, ArticleList } from "@/lib/engine";
import { Alert, Empty, PageHeader, Pill, fmtCost, fmtDate, fmtScore } from "@/lib/ui";
import { ClipboardCheck } from "lucide-react";

export const dynamic = "force-dynamic";

/* Approvals queue (plan §4): every article the pipeline produced that hasn't
   been decided on — `generated` (fresh) and `needs_review` (reopened or
   flagged). The queue is for triage: each row opens the review screen, where
   the checklist + rendered preview sit. No blind-approve button here (F2). */
const STATUS_RANK: Record<string, number> = { needs_review: 0, generated: 1 };

export default async function ApprovalsPage({
  searchParams,
}: {
  searchParams: Promise<{ site?: string; err?: string }>;
}) {
  const { site = "", err = "" } = await searchParams;
  let list: ArticleList | null = null;
  let error = "";
  try {
    list = await engine<ArticleList>(`/articles?limit=500`);
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  const queue = (list?.articles ?? [])
    .filter((a) => a.status === "generated" || a.status === "needs_review")
    .filter((a) => !site || a.site_slug === site)
    .sort(
      (a, b) =>
        (STATUS_RANK[a.status] ?? 9) - (STATUS_RANK[b.status] ?? 9) ||
        (a.created_at || "").localeCompare(b.created_at || ""),
    );
  const needsReview = queue.filter((a) => a.status === "needs_review").length;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Approvals"
        sub={
          list
            ? `${queue.length} waiting${site ? ` on ${site}` : " across all sites"}${
                needsReview ? ` · ${needsReview} flagged needs-review` : ""
              } — open a row to review against its checklist`
            : "the work queue for review decisions"
        }
        right={
          <Link href="/publish" className="text-xs text-accent hover:text-accent-strong hover:underline">
            publish queue →
          </Link>
        }
      />

      {err ? <Alert tone="error">{err}</Alert> : null}
      {error ? <Alert tone="error">Engine unreachable: {error}</Alert> : null}

      {!list ? null : queue.length === 0 ? (
        <Empty
          icon={ClipboardCheck}
          title={site ? `Queue clear on ${site}` : "Queue clear"}
          hint="Nothing is waiting for review. Newly generated articles land here the moment the pipeline finishes one."
          cta={{ href: "/articles", label: "Open content pipeline" }}
        />
      ) : (
        <>
          {site ? (
            <p className="text-xs text-ink-faint">
              Filtered to <span className="font-mono text-ink-dim">{site}</span> ·{" "}
              <Link href="/approvals" className="text-accent hover:underline">
                show all sites
              </Link>
            </p>
          ) : null}
          <div className="overflow-x-auto rounded-xl border border-line bg-card">
            <table className="w-full text-sm">
              <thead className="border-b border-line text-left text-xs text-ink-faint">
                <tr>
                  <th className="px-4 py-2.5">Article</th>
                  <th className="px-4 py-2.5">Site</th>
                  <th className="px-4 py-2.5">Status</th>
                  <th className="px-4 py-2.5 text-right">Quality</th>
                  <th className="px-4 py-2.5">Waiting since</th>
                  <th className="px-4 py-2.5 text-right">Cost</th>
                  <th className="px-4 py-2.5 text-right">Review</th>
                </tr>
              </thead>
              <tbody>
                {queue.map((a) => (
                  <tr key={a.id} className="border-t border-line/60 first:border-t-0 hover:bg-surface/40">
                    <td className="max-w-md px-4 py-2.5">
                      <Link href={`/articles/${a.id}`} className="font-medium hover:text-accent">
                        {a.title || `#${a.id}`}
                      </Link>
                      <p className="mt-0.5 truncate text-xs text-ink-faint" title={a.summary}>
                        {a.summary || `#${a.id}`}
                      </p>
                    </td>
                    <td className="whitespace-nowrap px-4 py-2.5 font-mono text-xs text-ink-faint">{a.site_slug}</td>
                    <td className="px-4 py-2.5">
                      <Pill status={a.status} />
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-xs text-ink-dim">{fmtScore(a.quality)}</td>
                    <td className="whitespace-nowrap px-4 py-2.5 text-xs text-ink-faint">{fmtDate(a.created_at)}</td>
                    <td className="px-4 py-2.5 text-right font-mono text-xs text-ink-faint">{fmtCost(a.cost_usd)}</td>
                    <td className="px-4 py-2.5 text-right">
                      <Link
                        href={`/articles/${a.id}`}
                        className="inline-flex items-center rounded-md border border-line bg-page px-2.5 py-1 text-xs text-ink-dim transition-colors hover:border-ink-faint hover:text-ink"
                      >
                        Review →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
