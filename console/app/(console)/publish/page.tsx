import Link from "next/link";
import { engine, ArticleList, LogsView } from "@/lib/engine";
import { Alert, Empty, PageHeader, Pill, fmtCost, fmtDate, fmtScore } from "@/lib/ui";
import { PendingButton } from "@/lib/interactive";
import { publishArticleAction } from "@/actions/articles";
import { Send } from "lucide-react";

export const dynamic = "force-dynamic";

/* Publish queue (plan §4): approved-but-unpublished articles. Publishing from
   here runs the same op as the detail screen — status flip + WP push in one
   call — with a confirm dialog; the action returns to this page. The
   "approved" date comes from audit rows (`article.approve`, newest first). */
const CONFIRM_PUBLISH =
  "Publish this article? WordPress sites get the post pushed (draft mode); custom sites flip to published and re-pull the payload.";

export default async function PublishPage({
  searchParams,
}: {
  searchParams: Promise<{ site?: string; err?: string }>;
}) {
  const { site = "", err = "" } = await searchParams;
  let list: ArticleList | null = null;
  let error = "";
  const approvedAt = new Map<number, string>();
  try {
    const [articles, log] = await Promise.all([
      engine<ArticleList>(`/articles?limit=500`),
      // Fail-soft: a missing log just means no "approved" dates on the rows.
      engine<LogsView>(`/logs?kind=article.approve&limit=500`).catch(() => null),
    ]);
    list = articles;
    for (const row of log?.audit ?? []) {
      if (row.article_id && row.created_at && !approvedAt.has(row.article_id)) {
        approvedAt.set(row.article_id, row.created_at);
      }
    }
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  const queue = (list?.articles ?? [])
    .filter((a) => a.status === "approved")
    .filter((a) => !site || a.site_slug === site)
    .sort(
      (a, b) =>
        (approvedAt.get(a.id) ?? a.created_at ?? "").localeCompare(
          approvedAt.get(b.id) ?? b.created_at ?? "",
        ),
    );

  return (
    <div className="space-y-6">
      <PageHeader
        title="Publish queue"
        sub={
          list
            ? `${queue.length} approved and waiting${site ? ` on ${site}` : " across all sites"} — publish creates the WordPress draft (or flips the status on custom sites)`
            : "approved articles waiting to go out"
        }
        right={
          <Link href="/approvals" className="text-xs text-accent hover:text-accent-strong hover:underline">
            approvals →
          </Link>
        }
      />

      {err ? <Alert tone="error">{err}</Alert> : null}
      {error ? <Alert tone="error">Engine unreachable: {error}</Alert> : null}

      {!list ? null : queue.length === 0 ? (
        <Empty
          icon={Send}
          title={site ? `Nothing to publish on ${site}` : "Nothing to publish"}
          hint="Approved articles wait here until they're pushed. Approve something first and it lands in this queue."
          cta={{ href: "/approvals", label: "Open approvals" }}
        />
      ) : (
        <>
          {site ? (
            <p className="text-xs text-ink-faint">
              Filtered to <span className="font-mono text-ink-dim">{site}</span> ·{" "}
              <Link href="/publish" className="text-accent hover:underline">
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
                  <th className="px-4 py-2.5">Approved</th>
                  <th className="px-4 py-2.5 text-right">Cost</th>
                  <th className="px-4 py-2.5 text-right">Actions</th>
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
                    <td className="whitespace-nowrap px-4 py-2.5 text-xs text-ink-faint">
                      {fmtDate(approvedAt.get(a.id) ?? null)}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-xs text-ink-faint">{fmtCost(a.cost_usd)}</td>
                    <td className="whitespace-nowrap px-4 py-2.5 text-right">
                      <div className="inline-flex items-center gap-2">
                        <Link
                          href={`/articles/${a.id}`}
                          className="inline-flex items-center rounded-md border border-line bg-page px-2.5 py-1 text-xs text-ink-dim transition-colors hover:border-ink-faint hover:text-ink"
                        >
                          Open
                        </Link>
                        <form action={publishArticleAction} className="inline-flex">
                          <input type="hidden" name="id" value={a.id} />
                          <input type="hidden" name="mode" value="draft" />
                          <input type="hidden" name="from" value="/publish" />
                          <PendingButton
                            className="inline-flex items-center justify-center rounded-md bg-accent-strong px-2.5 py-1 text-xs font-medium text-page transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
                            confirmMessage={CONFIRM_PUBLISH}
                            pendingLabel="Publishing…"
                          >
                            Publish (draft)
                          </PendingButton>
                        </form>
                      </div>
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
