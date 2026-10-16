import { engine } from "@/lib/engine";
import { runStageAction } from "@/actions/stages";
import { Alert, PageHeader } from "@/lib/ui";
import { PendingButton } from "@/lib/interactive";

export const dynamic = "force-dynamic";

const STAGES: { name: string; desc: string; confirm?: string }[] = [
  { name: "research", desc: "Pull keywords from the ledger into research findings" },
  { name: "brief", desc: "Turn the next research row into a content brief" },
  { name: "content", desc: "Generate content from the next ungenerated brief" },
  {
    name: "post",
    desc: "Publish the next approved post to the CMS / WordPress",
  },
  { name: "discover_topics", desc: "Discover new topic ideas" },
  { name: "edit_post", desc: "Run a targeted edit (needs EDIT_TITLE / EDIT_INSTRUCTION env)" },
  { name: "freshness_sweep", desc: "Rotate freshness checks over published posts" },
  { name: "repurpose", desc: "Build repurposing bundles for published posts" },
  { name: "search_performance_review", desc: "Log performance review rows" },
  { name: "mine_feedback", desc: "Mine review feedback into new keywords" },
  { name: "log_coverage", desc: "Audit approve/reject coverage" },
  { name: "decay", desc: "Decay/refresh job over aging posts" },
  { name: "serp_drift", desc: "SERP drift check" },
];

// Destructive-ish stages get a confirm; everything else just gets a pending state.
const NEUTRAL_STAGES = new Set(["research", "brief", "discover_topics", "log_coverage", "serp_drift"]);

export default async function StagesPage({
  searchParams,
}: {
  searchParams: Promise<{ started?: string; err?: string }>;
}) {
  const { started = "", err = "" } = await searchParams;
  let ping = "";
  try {
    await engine("/sites?limit=1");
    ping = "engine reachable";
  } catch (e) {
    ping = `engine unreachable: ${e instanceof Error ? e.message : String(e)}`;
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Pipeline stages"
        right={
          <span
            className={`flex items-center gap-1.5 text-xs ${
              ping.startsWith("engine reachable") ? "text-emerald-300" : "text-rose-300"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                ping.startsWith("engine reachable") ? "bg-emerald-400" : "bg-danger"
              }`}
              aria-hidden
            />
            {ping}
          </span>
        }
      />

      {started ? (
        <Alert tone="success">
          Stage “{started}” accepted — it runs in the engine background; refresh the
          queue/articles pages to watch progress.
        </Alert>
      ) : null}
      {err ? <Alert tone="error">{err}</Alert> : null}

      <div className="grid gap-3 sm:grid-cols-2">
        {STAGES.map((s) => {
          const confirmMessage = NEUTRAL_STAGES.has(s.name)
            ? undefined
            : `Run stage "${s.name}" now? It may spend credits or write to the live site.`;
          return (
            <div
              key={s.name}
              className="flex items-center justify-between gap-4 rounded-xl border border-line bg-card px-4 py-3"
            >
              <div>
                <p className="text-sm font-medium text-ink">{s.name}</p>
                <p className="text-xs text-ink-faint">{s.desc}</p>
              </div>
              <form action={runStageAction}>
                <input type="hidden" name="stage" value={s.name} />
                <PendingButton
                  pendingLabel="Starting…"
                  confirmMessage={confirmMessage}
                  className="inline-flex items-center gap-1.5 rounded-md border border-line bg-page px-3 py-1.5 text-xs font-medium text-ink-dim transition-colors hover:border-accent/50 hover:text-accent disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Run
                </PendingButton>
              </form>
            </div>
          );
        })}
      </div>
    </div>
  );
}
