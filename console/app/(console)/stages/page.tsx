import Link from "next/link";
import {
  engine,
  type ArticleList,
  type BriefPeek,
  type QueueView,
  type SiteList,
  type StageRun,
  type StagesView,
} from "@/lib/engine";
import { runStageAction } from "@/actions/stages";
import { Alert, Empty, PageHeader, SectionCard, fmtAgo, fmtScore } from "@/lib/ui";
import { PendingButton } from "@/lib/interactive";
import { History } from "lucide-react";

export const dynamic = "force-dynamic";

/* Risk tiers (plan Wave 5 "destructive coloring"): internal = engine tables
   only; spend = burns model/image credits; write = modifies the live site.
   Same confirm split as before — internal stages skip the confirm. */
type Risk = "internal" | "spend" | "write";

const STAGES: { name: string; desc: string; risk: Risk }[] = [
  { name: "research", desc: "Pull keywords from the ledger into research findings", risk: "internal" },
  { name: "brief", desc: "Turn the next research row into a content brief", risk: "internal" },
  { name: "content", desc: "Generate content from the next ungenerated brief", risk: "spend" },
  { name: "post", desc: "Publish the next approved post to the CMS / WordPress", risk: "write" },
  { name: "discover_topics", desc: "Discover new topic ideas", risk: "internal" },
  { name: "edit_post", desc: "Run a targeted edit (needs EDIT_TITLE / EDIT_INSTRUCTION env)", risk: "write" },
  { name: "freshness_sweep", desc: "Rotate freshness checks over published posts", risk: "write" },
  { name: "repurpose", desc: "Build repurposing bundles for published posts", risk: "spend" },
  { name: "search_performance_review", desc: "Log performance review rows", risk: "spend" },
  { name: "mine_feedback", desc: "Mine review feedback into new keywords", risk: "spend" },
  { name: "log_coverage", desc: "Audit approve/reject coverage", risk: "internal" },
  { name: "decay", desc: "Decay/refresh job over aging posts", risk: "write" },
  { name: "serp_drift", desc: "SERP drift check", risk: "internal" },
];

const RISK: Record<Risk, { label: string; chip: string; btn: string; confirm: string }> = {
  internal: {
    label: "internal",
    chip: "border-line bg-surface/60 text-ink-faint",
    btn: "border border-line bg-page text-ink-dim hover:border-accent/50 hover:text-accent",
    confirm: "",
  },
  spend: {
    label: "spends credits",
    chip: "border-gold/40 bg-gold/10 text-gold",
    btn: "border border-gold/40 bg-gold/10 text-gold hover:bg-gold/20",
    confirm: "It spends model/image credits.",
  },
  write: {
    label: "writes live site",
    chip: "border-rose-900 bg-rose-950/30 text-rose-300",
    btn: "border border-rose-900 bg-rose-950/40 text-rose-300 hover:bg-rose-950/70",
    confirm: "It writes to the live site.",
  },
};

function fmtDuration(ms: number): string {
  const n = Number(ms) || 0;
  if (n < 1000) return `${n}ms`;
  const s = n / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${Math.round(s % 60)}s`;
}

const HISTORY_ROWS = 25;

export default async function StagesPage({
  searchParams,
}: {
  searchParams: Promise<{ started?: string; err?: string; site?: string }>;
}) {
  const { started = "", err = "", site = "" } = await searchParams;

  let view: StagesView | null = null;
  let loadErr = "";
  try {
    view = await engine<StagesView>("/stages?limit=200");
  } catch (e) {
    loadErr = e instanceof Error ? e.message : String(e);
  }

  const running = new Set(view?.running ?? []);
  const last = view?.last ?? {};
  const history = view?.history ?? [];

  /* Next-row peeks — read-only mirrors of what brief/post pick, only
     meaningful with a site context (?site=). The engine ops never claim. */
  const sitesList = await engine<SiteList>("/sites").catch(() => null);
  let peekBrief: BriefPeek | null = null;
  let approved: ArticleList | null = null;
  let queue: QueueView | null = null;
  if (site) {
    [peekBrief, approved, queue] = await Promise.all([
      engine<BriefPeek>(`/sites/${encodeURIComponent(site)}/brief`).catch(() => null),
      engine<ArticleList>(`/articles?site_slug=${encodeURIComponent(site)}&status=approved&limit=1`).catch(() => null),
      engine<QueueView>(`/sites/${encodeURIComponent(site)}/queue?limit=1`).catch(() => null),
    ]);
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Pipeline stages"
        sub="Triggers the legacy one-shot stages against this engine — cards carry their credit/live-site risk, history is recorded per finished run."
        right={
          <span
            className={`flex items-center gap-1.5 text-xs ${
              view ? "text-emerald-300" : "text-rose-300"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${view ? "bg-emerald-400" : "bg-danger"}`}
              aria-hidden
            />
            {view ? "engine reachable" : "engine unreachable"}
          </span>
        }
      />

      {started ? (
        <Alert tone="success">
          Stage “{started}” accepted — it runs in the engine background; its
          result lands in the run history below when it finishes.
        </Alert>
      ) : null}
      {err ? <Alert tone="error">{err}</Alert> : null}
      {loadErr ? (
        <Alert tone="warn">
          Could not load run history: {loadErr} — cards still trigger stages.
        </Alert>
      ) : null}

      {site ? (
        <SectionCard
          title={`Next up — ${site}`}
          right={
            <Link href="/stages" className="text-xs text-accent hover:underline">
              clear site
            </Link>
          }
        >
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-lg border border-line bg-page px-4 py-3">
              <p className="text-[11px] uppercase tracking-wide text-ink-faint">
                Next briefable keyword
              </p>
              {peekBrief?.keyword ? (
                <>
                  <p className="mt-1 truncate text-sm text-ink" title={peekBrief.keyword}>
                    {peekBrief.keyword}
                  </p>
                  <p className="mt-0.5 text-xs text-ink-faint">
                    {peekBrief.intent || "no intent"} · priority {fmtScore(peekBrief.priority_score)}
                  </p>
                </>
              ) : (
                <p className="mt-1 text-xs text-ink-faint">
                  {peekBrief?.hint || peekBrief?.error || "peek unavailable"}
                </p>
              )}
            </div>
            <div className="rounded-lg border border-line bg-page px-4 py-3">
              <p className="text-[11px] uppercase tracking-wide text-ink-faint">
                Approved awaiting publish
              </p>
              <p className="mt-1 font-mono text-2xl text-ink">
                {approved ? approved.total : "—"}
              </p>
              <Link
                href="/articles?status=approved"
                className="mt-0.5 inline-block text-xs text-accent hover:underline"
              >
                open the filter →
              </Link>
            </div>
            <div className="rounded-lg border border-line bg-page px-4 py-3">
              <p className="text-[11px] uppercase tracking-wide text-ink-faint">Ledger depth</p>
              {queue && Object.keys(queue.counts).length > 0 ? (
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {Object.entries(queue.counts).map(([st, n]) => (
                    <span
                      key={st}
                      className="rounded-full border border-line bg-surface/60 px-2 py-0.5 text-[11px] text-ink-dim"
                    >
                      {st} {n}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="mt-1 text-xs text-ink-faint">ledger empty</p>
              )}
              <Link
                href={`/keywords?site=${encodeURIComponent(site)}`}
                className="mt-1 inline-block text-xs text-accent hover:underline"
              >
                keyword ledger →
              </Link>
            </div>
          </div>
        </SectionCard>
      ) : sitesList && sitesList.sites.length > 0 ? (
        <p className="flex flex-wrap items-center gap-2 text-xs text-ink-faint">
          Next-row peeks for a site:
          {sitesList.sites.map((s) => (
            <Link
              key={s.slug}
              href={`/stages?site=${encodeURIComponent(s.slug)}`}
              className="rounded-full border border-line bg-surface/60 px-2.5 py-0.5 font-mono text-[11px] text-accent hover:border-accent/50"
            >
              {s.slug}
            </Link>
          ))}
        </p>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2">
        {STAGES.map((s) => {
          const tier = RISK[s.risk];
          const confirmMessage = tier.confirm
            ? `Run stage "${s.name}" now? ${tier.confirm}`
            : undefined;
          const run = last[s.name] as StageRun | undefined;
          const isRunning = running.has(s.name);
          return (
            <div
              key={s.name}
              className="rounded-xl border border-line bg-card px-4 py-3"
            >
              <div className="flex items-center justify-between gap-4">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-ink">{s.name}</p>
                  <p className="text-xs text-ink-faint">{s.desc}</p>
                </div>
                <form action={runStageAction}>
                  <input type="hidden" name="stage" value={s.name} />
                  <PendingButton
                    pendingLabel="Starting…"
                    confirmMessage={confirmMessage}
                    className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${tier.btn}`}
                  >
                    Run
                  </PendingButton>
                </form>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px]">
                <span className={`rounded-full border px-2 py-0.5 ${tier.chip}`}>
                  {tier.label}
                </span>
                {isRunning ? (
                  <span className="flex items-center gap-1.5 rounded-full border border-amber-900/70 bg-amber-950/40 px-2 py-0.5 text-amber-300">
                    <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-400" aria-hidden />
                    running now
                  </span>
                ) : run ? (
                  <span
                    className={`flex items-center gap-1.5 ${run.ok ? "text-emerald-300" : "text-rose-300"}`}
                    title={run.detail || undefined}
                  >
                    <span
                      className={`h-1.5 w-1.5 rounded-full ${run.ok ? "bg-emerald-400" : "bg-danger"}`}
                      aria-hidden
                    />
                    {run.ok ? "ok" : "failed"} · {fmtAgo(run.finished_at)} · {fmtDuration(run.duration_ms)}
                    {!run.ok && run.detail ? (
                      <span className="max-w-[200px] truncate text-rose-300/80">{run.detail}</span>
                    ) : null}
                  </span>
                ) : (
                  <span className="text-ink-faint">no runs recorded</span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <SectionCard
        title="Run history"
        right={
          <Link href="/logs?kind=stage" className="text-xs text-accent hover:underline">
            full stage log →
          </Link>
        }
      >
        {history.length > 0 ? (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-line text-xs uppercase tracking-wide text-ink-faint">
                  <tr>
                    <th className="px-3 py-2">When</th>
                    <th className="px-3 py-2">Stage</th>
                    <th className="px-3 py-2">Result</th>
                    <th className="px-3 py-2">Duration</th>
                    <th className="px-3 py-2">Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {history.slice(0, HISTORY_ROWS).map((h) => (
                    <tr key={h.id} className="border-t border-line/60">
                      <td className="whitespace-nowrap px-3 py-2 text-xs text-ink-dim" title={h.finished_at ?? undefined}>
                        {fmtAgo(h.finished_at)}
                      </td>
                      <td className="px-3 py-2 font-mono text-xs text-accent">{h.stage}</td>
                      <td className="px-3 py-2">
                        <span
                          className={`flex items-center gap-1.5 text-xs ${h.ok ? "text-emerald-300" : "text-rose-300"}`}
                        >
                          <span
                            className={`h-1.5 w-1.5 rounded-full ${h.ok ? "bg-emerald-400" : "bg-danger"}`}
                            aria-hidden
                          />
                          {h.ok ? "ok" : "failed"}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 font-mono text-xs text-ink-dim">
                        {fmtDuration(h.duration_ms)}
                      </td>
                      <td className="max-w-[320px] truncate px-3 py-2 text-xs text-ink-faint" title={h.detail || undefined}>
                        {h.detail || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {history.length > HISTORY_ROWS ? (
              <p className="mt-2 text-xs text-ink-faint">
                Showing the newest {HISTORY_ROWS} of {history.length} recorded runs — the rest live
                in the stage log.
              </p>
            ) : null}
          </>
        ) : (
          <Empty
            icon={History}
            title="No finished runs recorded yet"
            hint="Runs triggered here are recorded when they finish (pass or fail). Scheduled CI runs execute in their own environment and don't write this history."
          />
        )}
      </SectionCard>

      <p className="text-xs text-ink-faint">
        Recorded runs only cover stages triggered through this console/engine
        instance; live status comes from this engine process.
      </p>
    </div>
  );
}
