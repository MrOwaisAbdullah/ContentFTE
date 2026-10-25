import { engine, ArticleList } from "@/lib/engine";
import { Alert, PageHeader } from "@/lib/ui";
import { ArticlesTable } from "./table";

export const dynamic = "force-dynamic";

export default async function ArticlesPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string; site?: string; err?: string }>;
}) {
  const { status = "", site = "", err = "" } = await searchParams;
  let list: ArticleList | null = null;
  let error = "";

  try {
    const qs = new URLSearchParams({ limit: "500" });
    if (status) qs.set("status", status);
    if (site) qs.set("site_slug", site);
    list = await engine<ArticleList>(`/articles?${qs}`);
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Content Pipeline"
        sub={
          site
            ? `Generated & published articles scoped to ${site}`
            : "Complete inventory of drafts, briefs, approved posts, and published articles across all sites"
        }
      />

      {err ? <Alert tone="error">{err}</Alert> : null}
      {error ? <Alert tone="error">Engine unreachable: {error}</Alert> : null}

      <ArticlesTable
        articles={list?.articles ?? []}
        activeSite={site}
        initialStatus={status}
      />
    </div>
  );
}
