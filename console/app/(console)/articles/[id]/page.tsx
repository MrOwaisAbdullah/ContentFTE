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
import { Alert, BTN_DANGER, BTN_GHOST, BTN_GOLD, BTN_PRIMARY, PageHeader, Pill, SectionCard, fmtCost } from "@/lib/ui";
import { PendingButton } from "@/lib/interactive";

export const dynamic = "force-dynamic";

/* Confirm before anything that spends credits or writes externally (plan §3).
   Approve / needs-review stay confirmation-free: both are reversible. */
const CONFIRM = {
  generate: "Generate content now? It spends LLM credits for this article.",
  stageImages: "Stage images now? It spends image-generation credits.",
  publishDraft: "Create a WordPress draft of this article?",
};

function ActionForm({
  action,
  id,
  extra,
  className,
  confirmMessage,
  pendingLabel,
  children,
}: {
  action: (formData: FormData) => Promise<void>;
  id: number;
  extra?: Record<string, string>;
  className: string;
  confirmMessage?: string;
  pendingLabel?: string;
  children: React.ReactNode;
}) {
  return (
    <form action={action}>
      <input type="hidden" name="id" value={id} />
      {Object.entries(extra || {}).map(([k, v]) => (
        <input key={k} type="hidden" name={k} value={v} />
      ))}
      <PendingButton className={className} confirmMessage={confirmMessage} pendingLabel={pendingLabel}>
        {children}
      </PendingButton>
    </form>
  );
}

function scoreRows(scores: Record<string, unknown>) {
  return Object.entries(scores);
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
        <Link href="/articles" className="text-xs text-accent">← articles</Link>
        <Alert tone="error">{error || "Article not found."}</Alert>
      </div>
    );
  }

  const meta = (article.meta || {}) as Record<string, unknown>;
  const faqs = Array.isArray(meta.faqs)
    ? (meta.faqs as unknown[]).filter(
        (f): f is { question: string; answer: string } =>
          !!f &&
          typeof f === "object" &&
          typeof (f as { question?: unknown }).question === "string" &&
          typeof (f as { answer?: unknown }).answer === "string",
      )
    : [];
  const summary = typeof meta.summary === "string" ? meta.summary : "";
  const editLog = Array.isArray(meta.edit_log) ? (meta.edit_log as unknown[]) : [];
  const scores = scoreRows(article.scores || {});

  return (
    <div className="space-y-6">
      <PageHeader
        title={article.title || `#${article.id}`}
        sub={`#${article.id} · ${article.slug ? `/${article.slug}` : "no slug"}`}
        right={
          <>
            {article.status === "briefed" ? (
              <ActionForm
                action={generateArticleAction}
                id={article.id}
                className={BTN_GHOST}
                confirmMessage={CONFIRM.generate}
                pendingLabel="Generating…"
              >
                Generate
              </ActionForm>
            ) : null}
            {article.status !== "approved" && article.status !== "published" ? (
              <ActionForm
                action={approveArticleAction}
                id={article.id}
                extra={{ approved: "1" }}
                className={BTN_GOLD}
              >
                Approve
              </ActionForm>
            ) : null}
            {article.status === "approved" || article.status === "needs_review" ? (
              <ActionForm
                action={approveArticleAction}
                id={article.id}
                extra={{ approved: "0" }}
                className={BTN_DANGER}
              >
                Needs review
              </ActionForm>
            ) : null}
            {article.status === "approved" ? (
              <form action={publishArticleAction}>
                <input type="hidden" name="id" value={article.id} />
                <input type="hidden" name="mode" value="draft" />
                <PendingButton
                  className={BTN_PRIMARY}
                  confirmMessage={CONFIRM.publishDraft}
                  pendingLabel="Publishing…"
                >
                  Publish (draft)
                </PendingButton>
              </form>
            ) : null}
            {article.status === "published" ? (
              <>
                <ActionForm action={refreshArticleAction} id={article.id} className={BTN_GHOST}>
                  Refresh live post
                </ActionForm>
                <ActionForm
                  action={stageImagesAction}
                  id={article.id}
                  className={BTN_GHOST}
                  confirmMessage={CONFIRM.stageImages}
                  pendingLabel="Staging…"
                >
                  Stage images
                </ActionForm>
              </>
            ) : null}
          </>
        }
      />

      <div className="flex items-center gap-3 border-b border-line pb-4">
        <Pill status={article.status} />
        <span className="font-mono text-xs text-ink-faint">
          {article.scores && Number(article.scores.overall) > 0
            ? `overall ${Number(article.scores.overall).toFixed(1)}`
            : "no score"}
        </span>
        <span className="font-mono text-xs text-ink-faint">{fmtCost(article.cost_usd)}</span>
        {editLog.length > 0 ? (
          <span className="text-xs text-ink-faint">
            {editLog.length} edit{editLog.length === 1 ? "" : "s"} logged
          </span>
        ) : null}
      </div>

      {err ? <Alert tone="error">{err}</Alert> : null}

      <SectionCard title="Edit content">
        <form action={patchContentAction} className="space-y-3">
          <input type="hidden" name="id" value={article.id} />
          <textarea
            name="content_md"
            defaultValue={article.markdown || ""}
            rows={22}
            className="w-full rounded-lg border border-line bg-page px-3 py-2 font-mono text-xs leading-5 text-ink-dim outline-none focus:border-accent"
            placeholder="Content markdown — empty for briefed articles until Generate runs."
          />
          <div className="flex items-center gap-3">
            <input
              name="note"
              placeholder="Edit note (optional)"
              className="rounded-md border border-line bg-page px-3 py-1.5 text-xs text-ink placeholder:text-ink-faint/70 focus:border-accent"
            />
            <PendingButton
              className={BTN_PRIMARY}
              pendingLabel="Saving…"
            >
              Save content
            </PendingButton>
          </div>
        </form>
      </SectionCard>

      <section className="grid gap-4 lg:grid-cols-2">
        <SectionCard title="Scores">
          {scores.length === 0 ? (
            <p className="text-sm text-ink-faint">No scores yet — run Generate to evaluate this article.</p>
          ) : (
            <dl className="space-y-2 text-sm">
              {scores.map(([k, v]) => (
                <div key={k} className="flex items-center justify-between gap-4 border-b border-line/60 pb-2 last:border-b-0 last:pb-0">
                  <dt className="text-xs text-ink-dim">{k}</dt>
                  <dd className="font-mono text-xs text-ink">
                    {typeof v === "number" ? v.toFixed(1) : String(v)}
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </SectionCard>

        <SectionCard title="FAQs / meta">
          {faqs.length === 0 && !summary ? (
            <p className="text-sm text-ink-faint">No FAQs or summary yet — they arrive with Generate.</p>
          ) : (
            <div className="space-y-4">
              {summary ? (
                <p className="rounded-lg border border-line bg-page p-3 text-xs leading-5 text-ink-dim">{summary}</p>
              ) : null}
              {faqs.length > 0 ? (
                <ol className="space-y-3">
                  {faqs.map((f, i) => (
                    <li key={i} className="text-xs">
                      <p className="font-medium text-ink">{f.question}</p>
                      <p className="mt-0.5 leading-5 text-ink-dim">{f.answer}</p>
                    </li>
                  ))}
                </ol>
              ) : null}
              <details className="text-xs text-ink-faint">
                <summary className="cursor-pointer hover:text-ink-dim">Raw meta JSON</summary>
                <pre className="mt-2 max-h-60 overflow-auto rounded-lg border border-line bg-page p-3 text-[11px] text-ink-faint">
                  {JSON.stringify({ faqs: meta.faqs, summary, edit_log: editLog }, null, 2)}
                </pre>
              </details>
            </div>
          )}
        </SectionCard>
      </section>
    </div>
  );
}
