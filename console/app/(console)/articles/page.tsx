import Link from "next/link";
import { engine, ArticleList } from "@/lib/engine";

export const dynamic = "force-dynamic";

const STATUSES = ["", "briefed", "generated", "approved", "needs_review", "published"];

export default async function ArticlesPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string; err?: string }>;
}) {
  const { status = "", err = "" } = await searchParams;
  let list: ArticleList | null = null;
  let error = "";
  try {
    const qs = new URLSearchParams({ limit: "200" });
    if (status) qs.set("status", status);
    list = await engine<ArticleList>(`/articles?${qs}`);
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Content (generated_posts + approved_unpublished)</h1>
        <span className="text-xs text-slate-500">quality score + summary from the sheet columns</span>
      </div>

      {err ? (
        <div className="rounded-md border border-red-900 bg-red-950/50 px-4 py-3 text-sm text-red-300">
          {err}
        </div>
      ) : null}
      {error ? (
        <div className="rounded-md border border-red-900 bg-red-950/50 px-4 py-3 text-sm text-red-300">
          Engine unreachable: {error}
        </div>
      ) : null}

      <div className="flex flex-wrap gap-2 text-xs">
        {STATUSES.map((s) => (
          <Link
            key={s || "all"}
            href={s ? `/articles?status=${s}` : "/articles"}
            className={`rounded-full border px-3 py-1 ${status === s ? "border-sky-700 text-sky-300" : "border-slate-700 text-slate-400"}`}
          >
            {s || "all"}
          </Link>
        ))}
      </div>

      {!list || list.articles.length === 0 ? (
        <p className="text-sm text-slate-500">No articles.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-800">
          <table className="w-full text-sm">
            <thead className="bg-slate-900 text-left text-xs text-slate-400">
              <tr>
                <th className="px-4 py-2">Title</th>
                <th className="px-4 py-2">Site</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2 text-right">Quality</th>
                <th className="px-4 py-2">Summary</th>
                <th className="px-4 py-2">Created</th>
                <th className="px-4 py-2 text-right">Cost</th>
              </tr>
            </thead>
            <tbody>
              {list.articles.map((a) => (
                <tr key={a.id} className="border-t border-slate-800/80">
                  <td className="px-4 py-2">
                    <Link href={`/articles/${a.id}`} className="hover:text-sky-300">
                      {a.title || `#${a.id}`}
                    </Link>
                  </td>
                  <td className="px-4 py-2 text-xs text-slate-500">{a.site_slug}</td>
                  <td className="px-4 py-2">
                    <span
                      className={`text-xs ${
                        a.status === "published"
                          ? "text-emerald-400"
                          : a.status === "approved"
                            ? "text-sky-400"
                            : a.status === "needs_review"
                              ? "text-amber-400"
                              : "text-slate-400"
                      }`}
                    >
                      {a.status}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-right text-xs">
                    {a.quality != null ? Number(a.quality).toFixed(1) : "—"}
                  </td>
                  <td
                    className="max-w-sm truncate px-4 py-2 text-xs text-slate-400"
                    title={a.summary}
                  >
                    {a.summary || "—"}
                  </td>
                  <td className="px-4 py-2 text-xs text-slate-500">
                    {a.created_at ? a.created_at.slice(0, 10) : "—"}
                  </td>
                  <td className="px-4 py-2 text-right text-xs text-slate-500">
                    {a.cost_usd != null ? `$${Number(a.cost_usd).toFixed(4)}` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
