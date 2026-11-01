import { SiteCadenceSettings } from "./site-cadence-settings";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  engine,
  type ArticleList,
  type ArticleStats,
  type BriefPeek,
  type QueueView,
  type SiteHealth,
  type SiteList,
} from "@/lib/engine";
import { currentInstance } from "@/lib/instances";
import { requireSession } from "@/lib/session";
import { Alert, PageHeader, Pill, checkTier, fmtDate, fmtScore } from "@/lib/ui";
import {
  Activity,
  ArrowLeft,
  ArrowUpRight,
  CheckCircle2,
  ExternalLink,
  FileText,
  Globe,
  KeyRound,
  Layers,
  ListOrdered,
  ScrollText,
  Send,
  Server,
  Settings,
  Sparkles,
  Workflow,
  XCircle,
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

function StatCard({
  label,
  value,
  sub,
  icon: Icon,
}: {
  label: string;
  value: string;
  sub: string;
  icon: React.ElementType;
}) {
  return (
    <div className="rounded-xl border border-line bg-card p-4 shadow-xs">
      <div className="flex items-center justify-between text-ink-faint">
        <span className="text-[11px] font-medium uppercase tracking-wider">{label}</span>
        <Icon className="h-4 w-4 text-accent" />
      </div>
      <p className="mt-2 font-mono text-2xl font-bold text-ink">{value}</p>
      <p className="mt-0.5 text-xs text-ink-faint">{sub}</p>
    </div>
  );
}

function FactItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-line/60 bg-surface/20 p-3">
      <dt className="text-[10px] font-semibold uppercase tracking-wider text-ink-faint">{label}</dt>
      <dd className="mt-1 break-words font-mono text-xs text-ink">{value}</dd>
    </div>
  );
}

function FindingItem({ tier, text }: { tier: "fail" | "warn" | "info"; text: string }) {
  const isFail = tier === "fail";
  const isWarn = tier === "warn";

  return (
    <div
      className={`flex items-start gap-2.5 rounded-lg border px-3 py-2 text-xs ${
        isFail
          ? "border-rose-500/20 bg-rose-500/10 text-rose-600 dark:text-rose-400"
          : isWarn
            ? "border-amber-500/20 bg-amber-500/10 text-amber-600 dark:text-amber-400"
            : "border-line/70 bg-surface/30 text-ink-dim"
      }`}
    >
      <span className="mt-0.5 shrink-0">
        {isFail ? (
          <XCircle className="h-3.5 w-3.5 text-rose-500" />
        ) : isWarn ? (
          <Activity className="h-3.5 w-3.5 text-amber-500" />
        ) : (
          <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
        )}
      </span>
      <span className="min-w-0 font-mono text-[11px]">{text}</span>
    </div>
  );
}

export default async function SiteDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams?: Promise<{ ok?: string; err?: string }>;
}) {
  await requireSession();
  const { slug } = await params;
  const sp = searchParams ? await searchParams : {};
  const okMsg = sp?.ok;
  const errMsg = sp?.err;
  const inst = await currentInstance();

  let sites: SiteList | null = null;
  let loadErr = "";
  try {
    sites = await engine<SiteList>("/sites");
  } catch (e) {
    loadErr = e instanceof Error ? e.message : String(e);
  }

  if (loadErr) {
    return (
      <div className="space-y-6">
        <PageHeader title={`Site ${slug}`} sub={`instance ${inst.name} (${inst.baseUrl})`} />
        <Alert tone="warn">Could not load sites: {loadErr}</Alert>
        <Link href="/sites" className="inline-flex items-center gap-1 text-xs text-accent hover:underline">
          <ArrowLeft className="h-3 w-3" /> Back to all sites
        </Link>
      </div>
    );
  }

  const site = sites?.sites.find((s) => s.slug === slug);
  if (!site) notFound();

  // Status counts come from the stats endpoint and the list is only the 6 newest
  // rows. This page used to download up to 500 full articles (markdown included)
  // just to count statuses client-side (plan CON-09). `articles.total` is the full
  // count regardless of `limit`.
  const [health, queue, brief, articles, stats] = await Promise.all([
    engine<SiteHealth>(`/sites/${encodeURIComponent(slug)}/health`).catch(() => null),
    engine<QueueView>(`/sites/${encodeURIComponent(slug)}/queue?limit=1`).catch(() => null),
    engine<BriefPeek>(`/sites/${encodeURIComponent(slug)}/brief`).catch(() => null),
    engine<ArticleList>(`/articles?site_slug=${encodeURIComponent(slug)}&limit=6`).catch(() => null),
    engine<ArticleStats>(`/articles/stats?site_slug=${encodeURIComponent(slug)}`).catch(() => null),
  ]);

  const statusCounts: Record<string, number> = stats?.by_status ?? {};
  const readyToPublish = statusCounts["approved"] ?? 0;
  const latest = (articles?.articles ?? []).slice(0, 6);

  const settings = site.settings ?? {};
  const settingsEmpty = Object.keys(settings).length === 0;

  const links: { href: string; label: string; icon: React.ElementType }[] = [
    { href: `/articles/keywords?site=${encodeURIComponent(slug)}`, label: "Keyword ledger", icon: ListOrdered },
    { href: `/articles/research?site=${encodeURIComponent(slug)}`, label: "Research", icon: Sparkles },
    { href: `/articles/briefs?site=${encodeURIComponent(slug)}`, label: "Briefs", icon: ScrollText },
    { href: `/insights?site=${encodeURIComponent(slug)}`, label: "Insights", icon: Activity },
    { href: `/stages?site=${encodeURIComponent(slug)}`, label: "Stages", icon: Workflow },
    { href: `/publish?site=${encodeURIComponent(slug)}`, label: "Publish Queue", icon: Send },
  ];

  return (
    <div className="space-y-6">
      {okMsg && <Alert tone="success">{okMsg}</Alert>}
      {errMsg && <Alert tone="error">{errMsg}</Alert>}
      <PageHeader
        title={site.name || site.slug}
        sub={`${site.slug} · ${site.site_type} · publish: ${site.publish_mode || "draft"} · ${
          site.base_url || "no base url"
        } — instance ${inst.name}`}
        right={
          <div className="flex items-center gap-2">
            <Link
              href="/sites"
              className="inline-flex items-center gap-1.5 rounded-xl border border-line bg-card px-3 py-1.5 text-xs font-medium text-ink-dim shadow-xs transition-colors hover:bg-surface hover:text-ink"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              <span>All Sites</span>
            </Link>
          </div>
        }
      />

      {/* Quick Metrics */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Briefable keywords"
          value={health ? String(health.ledger.briefable) : "—"}
          sub="Ledger rows ready for brief stage"
          icon={ListOrdered}
        />
        <StatCard
          label="Published articles"
          value={health ? String(health.ledger.published) : "—"}
          sub="Live articles marked published"
          icon={CheckCircle2}
        />
        <StatCard
          label="Total Pipeline Articles"
          value={articles ? String(articles.total) : "—"}
          sub="All statuses across this site"
          icon={FileText}
        />
        <StatCard
          label="Ready to Publish"
          value={articles ? String(readyToPublish) : "—"}
          sub="Articles in approved state"
          icon={Send}
        />
      </div>

      {/* Health Probes Card */}
      <Card>
        <CardHeader className="bg-surface/30 pb-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-accent" />
              <CardTitle className="text-sm font-semibold">Engine Health & Target Connectivity</CardTitle>
            </div>
            {health && (
              <Badge variant={health.wp_configured ? "success" : "warning"} dot>
                {health.wp_configured ? "CMS Configured" : "CMS Needs Setup"}
              </Badge>
            )}
          </div>
        </CardHeader>
        <CardContent className="pt-4">
          {health ? (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2 text-xs text-ink-faint">
                <span className="font-mono text-ink-dim">{health.ledger.briefable}</span> briefable ·{" "}
                <span className="font-mono text-ink-dim">{health.ledger.published}</span> published ·{" "}
                <span className="font-mono text-ink-dim">Base URL: {health.base_url || "—"}</span>
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                {health.critical.map((line) => (
                  <FindingItem key={`c-${line}`} tier="fail" text={line} />
                ))}
                {health.checks.map((line) => (
                  <FindingItem key={`k-${line}`} tier={checkTier(line)} text={line} />
                ))}
              </div>
              {health.critical.length === 0 && health.checks.length === 0 ? (
                <p className="text-xs text-emerald-600 dark:text-emerald-400">
                  ✓ All automated engine probes passed successfully.
                </p>
              ) : null}
            </div>
          ) : (
            <p className="text-xs text-ink-faint">Health unreachable — the engine probe failed.</p>
          )}
        </CardContent>
      </Card>

      {/* Pipeline Snapshot & Quick Actions */}
      <Card>
        <CardHeader className="bg-surface/30 pb-3">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-accent" />
            <CardTitle className="text-sm font-semibold">Pipeline Snapshot</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="pt-4">
          <div className="grid gap-6 lg:grid-cols-2">
            <div>
              <p className="text-[11px] uppercase tracking-wider font-semibold text-ink-faint">
                Next Briefable Keyword
              </p>
              {brief?.keyword ? (
                <div className="mt-2 rounded-xl border border-line bg-surface/30 p-3">
                  <p className="font-semibold text-ink text-sm" title={brief.keyword}>
                    {brief.keyword}
                  </p>
                  <div className="mt-1.5 flex items-center gap-2 text-xs text-ink-faint">
                    <Badge variant="outline" className="text-[10px] uppercase">
                      {brief.intent || "informational"}
                    </Badge>
                    <span>Priority {fmtScore(brief.priority_score)}</span>
                  </div>
                </div>
              ) : (
                <p className="mt-2 text-xs text-ink-faint">
                  {brief?.hint || brief?.error || "No briefable keywords currently queued."}
                </p>
              )}
            </div>

            <div>
              <p className="text-[11px] uppercase tracking-wider font-semibold text-ink-faint">
                Ledger Status Breakdown
              </p>
              {queue && Object.keys(queue.counts).length > 0 ? (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {Object.entries(queue.counts).map(([st, n]) => (
                    <span
                      key={st}
                      className="inline-flex items-center gap-1 rounded-full border border-line bg-card px-2.5 py-1 text-xs text-ink-dim shadow-xs"
                    >
                      <span className="capitalize">{st}</span>
                      <span className="font-mono font-bold text-accent">{n}</span>
                    </span>
                  ))}
                </div>
              ) : (
                <p className="mt-2 text-xs text-ink-faint">Ledger empty.</p>
              )}
            </div>
          </div>

          <div className="mt-5 border-t border-line/60 pt-4">
            <p className="text-[11px] uppercase tracking-wider font-semibold text-ink-faint mb-2">
              Site Navigation
            </p>
            <div className="flex flex-wrap gap-2">
              {links.map((l) => {
                const Icon = l.icon;
                return (
                  <Link
                    key={l.href}
                    href={l.href}
                    className="inline-flex items-center gap-1.5 rounded-xl border border-line bg-card px-3 py-1.5 text-xs font-medium text-ink-dim shadow-xs transition-colors hover:border-accent hover:text-accent hover:bg-accent/5"
                  >
                    <Icon className="h-3.5 w-3.5" />
                    <span>{l.label}</span>
                    <ArrowUpRight className="h-3 w-3 opacity-60" />
                  </Link>
                );
              })}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Interactive Cadence & Site Settings */}
      <SiteCadenceSettings site={site} cadence={health?.cadence} />

      {/* Articles Table Card */}
      <Card className="overflow-hidden">
        <CardHeader className="bg-surface/30 pb-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <FileText className="h-4 w-4 text-accent" />
              <CardTitle className="text-sm font-semibold">Recent Pipeline Articles</CardTitle>
            </div>
            <Link
              href="/articles"
              className="inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline"
            >
              <span>View all articles</span>
              <ArrowUpRight className="h-3 w-3" />
            </Link>
          </div>
        </CardHeader>

        {articles && articles.articles.length > 0 ? (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[80px]">ID</TableHead>
                  <TableHead>Title</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Created</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {latest.map((a) => (
                  <TableRow key={a.id} className="group">
                    <TableCell className="font-mono text-xs">
                      <Link
                        href={`/articles/${a.id}`}
                        className="inline-flex items-center gap-1 text-accent font-semibold hover:underline"
                      >
                        #{a.id}
                      </Link>
                    </TableCell>
                    <TableCell className="max-w-[400px] truncate font-medium text-ink" title={a.title}>
                      {a.title}
                    </TableCell>
                    <TableCell>
                      <Pill status={a.status} />
                    </TableCell>
                    <TableCell className="text-right text-xs text-ink-faint">
                      {fmtDate(a.created_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <CardContent className="pt-4">
            <p className="text-xs text-ink-faint">
              No articles on this site yet — submit a keyword on the ledger and run the brief/content stages.
            </p>
          </CardContent>
        )}
      </Card>
    </div>
  );
}
