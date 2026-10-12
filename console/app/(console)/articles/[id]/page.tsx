import Link from "next/link";
import { engine, ArticleDetail } from "@/lib/engine";
import {
  approveArticleAction,
  generateArticleAction,
  patchContentAction,
  publishArticleAction,
  refreshArticleAction,
  stageImagesAction,
} from "@/actions/articles";

export const dynamic = "force-dynamic";

function ActionForm({
  action,
  id,
  extra,
  children,
}: {
  action: (formData: FormData) => Promise<void>;
  id: number;
  extra?: Record<string, string>;
  children: React.ReactNode;
}) {
  return (
    <form action={action}>
      <input type="hidden" name="id" value={id} />
      {Object.entries(extra || {}).map(([k, v]) => (
        <input key={k} type="hidden" name={k} value={v} />
      ))}
      <button
        type="submit"
        className="rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs text-slate-200 hover:border-slate-500"
      >
        {children}
      </button>
    </form>
  );
}

export default async function ArticlePage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ err?: string }>;
}) {
  const { id } = await params;
  const { err = "" } = await searchParams;
  let article: ArticleDetail | null = null;
  let error = "";
  try {
    article = await engine<ArticleDetail>(`/articles/${id}/content`);
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  if (!article) {
    return (
      <div className="space-y-4">
        <Link href="/articles" className="text-xs text-sky-400">← articles</Link>
        <div className="rounded-md border border-red-900 bg-red-950/50 px-4 py-3 text-sm text-red-300">
          {error || "Article not found."}
        </div>
      </div>
    );
  }

  const meta = (article.meta || {}) as Record<string, unknown>;
  const faqs = meta.faqs;
  const editLog = Array.isArray(meta.edit_log) ? (meta.edit_log as unknown[]) : [];
  const quality = (article.scores || {}).quality;

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <Link href="/articles" className="text-xs text-sky-400">← articles</Link>
          <h1 className="mt-1 text-lg font-semibold">{article.title || `#${article.id}`}</h1>
          <p className="mt-1 text-xs text-slate-500">
            #{article.id} · {article.status} ·{" "}
            {quality != null ? `quality ${quality}` : "no score"}
            {article.cost_usd != null ? ` · $${Number(article.cost_usd).toFixed(4)}` : ""}
            {article.slug ? ` · /${article.slug}` : ""}
          </p>
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          {article.status === "briefed" ? (
            <ActionForm action={generateArticleAction} id={article.id}>
              Generate
            </ActionForm>
          ) : null}
          {article.status !== "approved" && article.status !== "published" ? (
            <ActionForm action={approveArticleAction} id={article.id} extra={{ approved: "1" }}>
              Approve
            </ActionForm>
          ) : null}
          {article.status === "approved" || article.status === "needs_review" ? (
            <ActionForm action={approveArticleAction} id={article.id} extra={{ approved: "0" }}>
              <span className="text-amber-300">Needs review</span>
            </ActionForm>
          ) : null}
          {article.status === "approved" ? (
            <form action={publishArticleAction}>
              <input type="hidden" name="id" value={article.id} />
              <input type="hidden" name="mode" value="draft" />
              <button className="rounded-md bg-sky-600 px-3 py-1.5 text-xs font-medium hover:bg-sky-500">
                Publish (draft)
              </button>
            </form>
          ) : null}
          {article.status === "published" ? (
            <>
              <ActionForm action={refreshArticleAction} id={article.id}>
                Refresh live post
              </ActionForm>
              <ActionForm action={stageImagesAction} id={article.id}>
                Stage images
              </ActionForm>
            </>
          ) : null}
        </div>
      </div>

      {err ? (
        <div className="rounded-md border border-red-900 bg-red-950/50 px-4 py-3 text-sm text-red-300">
          {err}
        </div>
      ) : null}

      <section className="rounded-lg border border-slate-800 bg-slate-900 p-5">
        <h2 className="mb-3 text-sm font-medium text-slate-400">Edit content</h2>
        <form action={patchContentAction} className="space-y-3">
          <input type="hidden" name="id" value={article.id} />
          <textarea
            name="content_md"
            defaultValue={article.markdown || ""}
            rows={22}
            className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-xs leading-5 outline-none focus:border-sky-600"
          />
          <div className="flex items-center gap-3">
            <input
              name="note"
              placeholder="Edit note (optional)"
              className="rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs outline-none focus:border-sky-600"
            />
            <button className="rounded-md bg-emerald-700 px-3 py-1.5 text-xs font-medium hover:bg-emerald-600">
              Save content
            </button>
            {editLog.length > 0 ? (
              <span className="text-xs text-slate-500">
                {editLog.length} edit{editLog.length === 1 ? "" : "s"} logged
              </span>
            ) : null}
          </div>
        </form>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-slate-800 bg-slate-900 p-5">
          <h2 className="mb-3 text-sm font-medium text-slate-400">Scores</h2>
          <pre className="overflow-x-auto text-xs text-slate-300">
            {JSON.stringify(article.scores || {}, null, 2)}
          </pre>
        </div>
        <div className="rounded-lg border border-slate-800 bg-slate-900 p-5">
          <h2 className="mb-3 text-sm font-medium text-slate-400">FAQs / meta</h2>
          <pre className="max-h-80 overflow-auto text-xs text-slate-300">
            {JSON.stringify({ faqs, summary: meta.summary, edit_log: editLog }, null, 2)}
          </pre>
        </div>
      </section>
    </div>
  );
}
