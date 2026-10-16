import { requireSession } from "@/lib/session";
import { currentInstance, registry } from "@/lib/instances";
import { engine, type ArticleList, type SiteList } from "@/lib/engine";
import { ConsoleShell } from "@/lib/shell";
import { Toaster } from "@/lib/toast";

// Console chrome (Wave 1, docs/console-dashboard-plan.md §4): the sidebar IA
// lives in <ConsoleShell/>; this layout only gathers the chrome's data —
// instance registry, site switcher options, engine health and the approvals
// work-queue count. Every fetch is best-effort: a dead engine renders as a
// red health dot in the topbar instead of taking the whole console down.
export default async function ConsoleLayout({ children }: { children: React.ReactNode }) {
  await requireSession();
  const [instances, current, sitesRes, articlesRes] = await Promise.all([
    registry(),
    currentInstance(),
    engine<SiteList>("/sites").catch(() => null),
    engine<ArticleList>("/articles?limit=500").catch(() => null),
  ]);

  const sites = (sitesRes?.sites ?? []).map((s) => ({ slug: s.slug, name: s.name || s.slug }));
  const approvalsCount =
    articlesRes?.articles.filter((a) => a.status === "generated" || a.status === "needs_review").length ?? 0;

  return (
    <>
      <ConsoleShell
        sites={sites}
        instances={instances.map((i) => i.name)}
        currentInstance={current.name}
        engineOk={sitesRes !== null}
        approvalsCount={approvalsCount}
      >
        {children}
      </ConsoleShell>
      <Toaster />
    </>
  );
}
