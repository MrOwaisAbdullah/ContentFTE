import { requireSession } from "@/lib/session";
import { currentInstance, registry } from "@/lib/instances";
import { engine, type ArticleList, type ArticleStats, type SiteList } from "@/lib/engine";
import { ConsoleShell } from "@/lib/shell";
import { Toaster } from "@/lib/toast";
import { FlashToaster } from "@/components/flash-toaster";

export default async function ConsoleLayout({ children }: { children: React.ReactNode }) {
  await requireSession();
  const [instances, current, sitesRes, statsRes] = await Promise.all([
    registry(),
    currentInstance(),
    engine<SiteList>("/sites").catch(() => null),
    engine<ArticleStats>("/articles/stats").catch(() => null),
  ]);

  const sites = (sitesRes?.sites ?? []).map((s) => ({ slug: s.slug, name: s.name || s.slug }));
  const approvalsCount = (statsRes?.by_status?.generated ?? 0) + (statsRes?.by_status?.needs_review ?? 0);

  // recent articles for the command palette (UX-16)
  const recentArticles = (await engine<ArticleList>("/articles?limit=100").catch(() => null))
    ?.articles.map((a) => ({ id: a.id, title: a.title, slug: a.slug, site: a.site_slug, status: a.status })) ?? [];

  return (
    <>
      <ConsoleShell
        sites={sites}
        instances={instances.map((i) => i.name)}
        currentInstance={current.name}
        engineOk={sitesRes !== null}
        approvalsCount={approvalsCount}
        articles={recentArticles}
      >
        {children}
      </ConsoleShell>
      <Toaster />
      <FlashToaster />
    </>
  );
}
