import Link from "next/link";
import { engine, type ArticleList, type LogsView } from "@/lib/engine";
import { Alert, Empty, PageHeader, Pill, fmtCost, fmtDate, fmtScore } from "@/lib/ui";
import { PendingButton } from "@/lib/interactive";
import { publishArticleAction } from "@/actions/articles";
import {
  CheckCircle2,
  ChevronRight,
  ExternalLink,
  Eye,
  Send,
  Sparkles,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export const dynamic = "force-dynamic";

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
    const siteParam = site ? `?site_slug=${encodeURIComponent(site)}&status=approved&limit=200` : "?status=approved&limit=200";
    const [articles, log] = await Promise.all([
      engine<ArticleList>(`/articles${siteParam}`),
      engine<LogsView>(`/logs?kind=article.approve&limit=200`).catch(() => null),
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
    .sort(
      (a, b) =>
        (approvedAt.get(a.id) ?? a.created_at ?? "").localeCompare(
          approvedAt.get(b.id) ?? b.created_at ?? "",
        ),
    );

  const scoreBadge = (score: number | null | undefined) => {
    if (score == null || !Number.isFinite(score)) return <span className="text-ink-faint">—</span>;
    const n = Math.round(score);
    const variant = n >= 90 ? "success" : n >= 75 ? "warning" : "destructive";
    return (
      <Badge variant={variant} dot className="font-mono font-semibold">
        {n}/100
      </Badge>
    );
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Publish Queue"
        sub={
          list
            ? `${queue.length} approved article${queue.length === 1 ? "" : "s"} waiting for publication — dispatch pushes them to the CMS (WordPress) or flips them live (custom sites).${
                site ? ` on ${site}` : " across all sites"
              }`
            : "Approved posts ready to dispatch"
        }
        right={
          <Link
            href="/approvals"
            className="inline-flex items-center gap-1 text-xs font-semibold text-accent transition-colors hover:underline"
          >
            <span>Review pending drafts</span>
            <ChevronRight className="h-3.5 w-3.5" />
          </Link>
        }
      />

      {err ? <Alert tone="error">{err}</Alert> : null}
      {error ? <Alert tone="error">Engine unreachable: {error}</Alert> : null}

      {!list ? null : queue.length === 0 ? (
        <Empty
          icon={CheckCircle2}
          title={site ? `Nothing to publish on ${site}` : "Publish queue is clear"}
          hint="All approved articles have been published. Newly approved articles will automatically queue up here for dispatch."
          cta={{ href: "/approvals", label: "Open Approvals" }}
        />
      ) : (
        <div className="space-y-4">
          {site ? (
            <div className="flex items-center justify-between text-xs text-ink-faint">
              <p>
                Showing approved posts for <span className="font-mono font-medium text-ink">{site}</span>
              </p>
              <Link href="/publish" className="text-accent hover:underline">
                Show all sites
              </Link>
            </div>
          ) : null}

          <Card className="overflow-hidden">
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[380px]">Article Title</TableHead>
                    <TableHead>Target Site</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-center">Quality</TableHead>
                    <TableHead>Approved On</TableHead>
                    <TableHead className="hidden text-right sm:table-cell">Cost</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {queue.map((a) => (
                    <TableRow key={a.id} className="group">
                      <TableCell className="max-w-sm">
                        <Link
                          href={`/articles/${a.id}`}
                          className="font-semibold text-ink transition-colors hover:text-accent block leading-snug"
                        >
                          {a.title || `#${a.id}`}
                        </Link>
                        <p className="mt-0.5 truncate text-[11px] text-ink-faint" title={a.summary || a.slug}>
                          {a.summary || a.slug}
                        </p>
                      </TableCell>

                      <TableCell className="font-mono text-xs text-ink-dim whitespace-nowrap">
                        <Badge variant="outline" className="text-[10px]">
                          {a.site_slug}
                        </Badge>
                      </TableCell>

                      <TableCell className="whitespace-nowrap">
                        <Pill status={a.status} />
                      </TableCell>

                      <TableCell className="text-center whitespace-nowrap">
                        {scoreBadge(a.quality)}
                      </TableCell>

                      <TableCell className="text-xs text-ink-faint whitespace-nowrap">
                        {fmtDate(approvedAt.get(a.id) ?? a.created_at ?? null)}
                      </TableCell>

                      <TableCell className="hidden text-right font-mono text-xs text-ink-dim sm:table-cell whitespace-nowrap">
                        {fmtCost(a.cost_usd)}
                      </TableCell>

                      <TableCell className="text-right whitespace-nowrap">
                        <div className="inline-flex items-center gap-1.5">
                          <Link
                            href={`/articles/${a.id}`}
                            className="inline-flex items-center gap-1 rounded-xl border border-line bg-card px-2.5 py-1 text-xs font-medium text-ink-dim shadow-xs transition-colors hover:bg-surface hover:text-ink"
                          >
                            <Eye className="h-3 w-3" />
                            <span>Preview</span>
                          </Link>
                          <form action={publishArticleAction} className="inline-flex">
                            <input type="hidden" name="id" value={a.id} />
                            <input type="hidden" name="mode" value="draft" />
                            <input type="hidden" name="from" value="/publish" />
                            <PendingButton
                              className="inline-flex items-center justify-center gap-1.5 rounded-xl bg-primary-container px-3 py-1 text-xs font-semibold text-white shadow-[0_0_12px_rgba(242,100,58,0.25)] transition-all hover:brightness-110 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 cursor-pointer"
                              confirmTitle="Dispatch Article to Fleet"
                              confirmMessage={CONFIRM_PUBLISH}
                              confirmButtonLabel="Publish to Fleet"
                              confirmVariant="primary"
                              pendingLabel="Publishing…"
                              leftIcon={<Send className="h-3 w-3" />}
                            >
                              Publish
                            </PendingButton>
                          </form>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
