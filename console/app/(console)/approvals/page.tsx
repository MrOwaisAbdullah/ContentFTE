import Link from "next/link";
import { engine, type ArticleList } from "@/lib/engine";
import { Alert, Empty, PageHeader, Pill, fmtCost, fmtDate } from "@/lib/ui";
import { Check, CheckCircle2, ChevronRight, ClipboardCheck, X as XIcon } from "lucide-react";
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
import { approveArticleAction } from "@/actions/articles";
import { PendingButton } from "@/lib/interactive";

export const dynamic = "force-dynamic";

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
    const siteParam = site ? `?site_slug=${encodeURIComponent(site)}&status=generated&limit=200` : "?status=generated&limit=200";
    const siteParam2 = site ? `?site_slug=${encodeURIComponent(site)}&status=needs_review&limit=200` : "?status=needs_review&limit=200";
    const [generated, needsReview] = await Promise.all([
      engine<ArticleList>(`/articles${siteParam}`).catch(() => null),
      engine<ArticleList>(`/articles${siteParam2}`).catch(() => null),
    ]);
    list = {
      articles: [...(generated?.articles ?? []), ...(needsReview?.articles ?? [])],
      count: (generated?.count ?? 0) + (needsReview?.count ?? 0),
      total: (generated?.total ?? 0) + (needsReview?.total ?? 0),
      limit: 400,
      offset: 0,
    };
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  const queue = (list?.articles ?? [])
    .filter((a) => a.status === "generated" || a.status === "needs_review")
    .sort(
      (a, b) =>
        (STATUS_RANK[a.status] ?? 9) - (STATUS_RANK[b.status] ?? 9) ||
        (a.created_at || "").localeCompare(b.created_at || ""),
    );

  const needsReview = queue.filter((a) => a.status === "needs_review").length;

  const scoreBadge = (score: number | null | undefined) => {
    if (score == null || !Number.isFinite(score)) {
      return (
        <span className="text-[11px] font-mono text-ink-faint" title="No eval recorded for this run">
          Not scored
        </span>
      );
    }
    const n = Math.round(score);
    if (n >= 90) {
      return (
        <Badge variant="success" dot className="font-mono font-semibold">
          {n}/100
        </Badge>
      );
    }
    if (n >= 75) {
      return (
        <Badge variant="warning" dot className="font-mono font-semibold">
          {n}/100
        </Badge>
      );
    }
    return (
      <Badge variant="destructive" dot className="font-mono font-semibold">
        {n}/100
      </Badge>
    );
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Approvals Queue"
        sub={
          list
            ? `${queue.length} article${queue.length === 1 ? "" : "s"} waiting for editorial decision${
                site ? ` on ${site}` : " across all sites"
              }${needsReview ? ` • ${needsReview} flagged needs review` : ""} — articles waiting for an editorial decision before they can be published.`
            : "Human review & editorial gate queue"
        }
        right={
          <Link
            href="/publish"
            className="inline-flex items-center gap-1 text-xs font-semibold text-accent transition-colors hover:underline"
          >
            <span>Publish queue</span>
            <ChevronRight className="h-3.5 w-3.5" />
          </Link>
        }
      />

      {err ? <Alert tone="error">{err}</Alert> : null}
      {error ? <Alert tone="error">Engine unreachable: {error}</Alert> : null}

      {!list ? null : queue.length === 0 ? (
        <Empty
          icon={CheckCircle2}
          title={site ? `Queue clear on ${site}` : "Approvals queue clear"}
          hint="Nothing is waiting for review. Newly generated articles land here the moment the pipeline finishes one."
          cta={{ href: "/articles", label: "Open Content Pipeline" }}
        />
      ) : (
        <div className="space-y-4">
          {site ? (
            <div className="flex items-center justify-between text-xs text-ink-faint">
              <p>
                Showing drafts waiting review on <span className="font-mono font-medium text-ink">{site}</span>
              </p>
              <Link href="/approvals" className="text-accent hover:underline">
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
                    <TableHead className="text-center">Quality Gate</TableHead>
                    <TableHead>Waiting Since</TableHead>
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
                        {fmtDate(a.created_at)}
                      </TableCell>

                      <TableCell className="hidden text-right font-mono text-xs text-ink-dim sm:table-cell whitespace-nowrap">
                        {fmtCost(a.cost_usd)}
                      </TableCell>

                      <TableCell className="text-right whitespace-nowrap">
                        <div className="flex items-center justify-end gap-1.5">
                          <form action={approveArticleAction}>
                            <input type="hidden" name="id" value={a.id} />
                            <input type="hidden" name="approved" value="1" />
                            <input type="hidden" name="from" value="/approvals" />
                            <PendingButton
                              title="Approve article"
                              pendingLabel="…"
                              className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white px-2.5 py-1 text-xs font-semibold shadow-xs transition-all active:scale-[0.98] cursor-pointer"
                              leftIcon={<Check className="h-3.5 w-3.5" />}
                            >
                              <span>Approve</span>
                            </PendingButton>
                          </form>

                          <form action={approveArticleAction}>
                            <input type="hidden" name="id" value={a.id} />
                            <input type="hidden" name="approved" value="0" />
                            <input type="hidden" name="from" value="/approvals" />
                            <input type="hidden" name="note" value="Rejected from approvals queue" />
                            <PendingButton
                              title="Reject / request review"
                              pendingLabel="…"
                              confirmTitle="Reject Draft for Review"
                              confirmMessage={`Are you sure you want to reject "${a.title || `#${a.id}`}"? It will be flagged for review and sent back with quality notes.`}
                              confirmButtonLabel="Reject Draft"
                              confirmVariant="danger"
                              className="inline-flex items-center gap-1 rounded-lg bg-surface-container hover:bg-rose-500/10 hover:text-rose-400 hover:border-rose-500/30 text-secondary border border-line px-2 py-1 text-xs font-medium transition-all active:scale-[0.98] cursor-pointer"
                              leftIcon={<XIcon className="h-3 w-3" />}
                            >
                              <span>Reject</span>
                            </PendingButton>
                          </form>

                          <Link
                            href={`/articles/${a.id}`}
                            className="inline-flex items-center gap-1 rounded-lg bg-surface-container hover:bg-surface-high border border-line px-2 py-1 text-xs font-medium text-ink transition-colors"
                            title="Open full editor and audit evidence"
                          >
                            <span>Diff</span>
                            <ChevronRight className="h-3 w-3 text-secondary" />
                          </Link>
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
