import { engine } from "@/lib/engine";
import { runStageAction } from "@/actions/stages";

export const dynamic = "force-dynamic";

const STAGES: { name: string; desc: string }[] = [
  { name: "research", desc: "Pull keywords from the ledger into research findings" },
  { name: "brief", desc: "Turn the next research row into a content brief" },
  { name: "content", desc: "Generate content from the next ungenerated brief" },
  { name: "post", desc: "Publish the next approved post to the CMS / WordPress" },
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
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Pipeline stages</h1>
        <span className={`text-xs ${ping.startsWith("engine reachable") ? "text-emerald-400" : "text-red-400"}`}>
          {ping}
        </span>
      </div>

      {started ? (
        <div className="rounded-md border border-emerald-800 bg-emerald-950/50 px-4 py-3 text-sm text-emerald-300">
          Stage “{started}” accepted — it runs in the engine background; refresh the
          queue/articles pages to watch progress.
        </div>
      ) : null}
      {err ? (
        <div className="rounded-md border border-red-900 bg-red-950/50 px-4 py-3 text-sm text-red-300">
          {err}
        </div>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2">
        {STAGES.map((s) => (
          <div
            key={s.name}
            className="flex items-center justify-between gap-4 rounded-lg border border-slate-800 bg-slate-900 px-4 py-3"
          >
            <div>
              <p className="text-sm font-medium">{s.name}</p>
              <p className="text-xs text-slate-500">{s.desc}</p>
            </div>
            <form action={runStageAction}>
              <input type="hidden" name="stage" value={s.name} />
              <button className="rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs hover:border-slate-500">
                Run
              </button>
            </form>
          </div>
        ))}
      </div>
    </div>
  );
}
