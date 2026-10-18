import Link from "next/link";
import {
  engine,
  ArticleDetail,
  LogsView,
  SiteList,
  WpPostReadback,
} from "@/lib/engine";
import {
  approveArticleAction,
  generateArticleAction,
  patchMetaAction,
  publishArticleAction,
  refreshArticleAction,
  regenerateImageAction,
  stageImagesAction,
} from "@/actions/articles";
import {
  actionColor,
  Alert,
  BTN_GHOST,
  BTN_GOLD,
  BTN_PRIMARY,
  Pill,
  SectionCard,
  fmtCost,
  fmtScore,
} from "@/lib/ui";
import { PendingButton } from "@/lib/interactive";
import { ContentWorkspace } from "@/lib/workspace";
import { MediaCard, MediaImage } from "@/lib/media";
import { Braces, CircleCheck, ExternalLink, FileClock, Info, TriangleAlert } from "lucide-react";

export const dynamic = "force-dynamic";

/* Confirm before anything that spends credits or writes externally (plan §3).
   Approve / send-to-review stay confirmation-free: both are reversible. */
const CONFIRM = {
  generate: "Generate content now? It spends LLM credits for this article.",
  stageImages: "Stage images now? It spends image-generation credits.",
  regenerate:
    "Regenerate this image? It re-runs generation for this slot and spends image credits.",
  publishDraft:
    "Publish this article? WordPress sites get the post pushed (draft mode); custom sites flip to published and re-pull the payload.",
};

/* Shared input styling (matches the review-note input in the Decision card). */
const FIELD_INPUT =
  "w-full rounded-md border border-line bg-page px-3 py-1.5 text-xs text-ink placeholder:text-ink-faint/70 focus:border-accent";

/* Mirror of lib/eval_gate.py — the approve checklist shows what the engine
   gate will say (≥90 overall AND every sub-score ≥80). */
const SUB_SCORES = ["accuracy", "depth", "seo", "voice", "originality", "citability"] as const;
const PUBLISH_THRESHOLD = 90;
const SUB_SCORE_FLOOR = 80;
const SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}

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

/* ── checklist (plan §5: each row links to its evidence) ───────────────── */

type ChecklistTier = "pass" | "warn" | "info";
type ChecklistRow = { key: string; label: string; value: string; tier: ChecklistTier; href?: string };

const TIER_STYLE: Record<ChecklistTier, { icon: typeof CircleCheck; cls: string }> = {
  pass: { icon: CircleCheck, cls: "text-emerald-400" },
  warn: { icon: TriangleAlert, cls: "text-amber-400" },
  info: { icon: Info, cls: "text-ink-faint" },
};

function Checklist({ rows }: { rows: ChecklistRow[] }) {
  return (
    <SectionCard title="Approve checklist">
      <ul className="space-y-3.5">
        {rows.map((row) => {
          const { icon: Icon, cls } = TIER_STYLE[row.tier];
          return (
            <li key={row.key} className="flex gap-2.5 text-xs">
              <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${cls}`} aria-hidden />
              <div className="min-w-0">
                <p className="font-medium text-ink">{row.label}</p>
                <p className="mt-0.5 leading-5 text-ink-dim">{row.value}</p>
                {row.href ? (
                  <Link href={row.href} className="mt-1 inline-block text-accent hover:underline">
                    see evidence →
                  </Link>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
    </SectionCard>
  );
}

/* ── scores ────────────────────────────────────────────────────────────── */

function ScoreBar({ value, floor }: { value: number; floor?: number }) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div className="relative h-1.5 w-full overflow-hidden rounded-full bg-surface">
      <div className="h-full rounded-full bg-accent/70" style={{ width: `${pct}%` }} />
      {floor ? (
        <span
          className="absolute top-0 h-full w-px bg-gold/90"
          style={{ left: `${floor}%` }}
          title={`gate floor ${floor}`}
        />
      ) : null}
    </div>
  );
}

function ScoresCard({
  overall,
  subs,
  subsPresent,
  raw,
}: {
  overall: number | null;
  subs: { k: string; v: number | null }[];
  subsPresent: boolean;
  raw: Record<string, unknown>;
}) {
  return (
    <SectionCard title="Scores" id="scores">
      {overall === null ? (
        <p className="text-sm text-ink-faint">No scores yet — run Generate to evaluate this article.</p>
      ) : (
        <div className="space-y-4">
          <div>
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-2xl font-semibold text-ink">{overall}</span>
              <span className="font-mono text-[11px] text-ink-faint">overall · gate ≥ {PUBLISH_THRESHOLD}</span>
            </div>
            <div className="mt-2">
              <ScoreBar value={overall} floor={PUBLISH_THRESHOLD} />
            </div>
          </div>

          {subsPresent ? (
            <ul className="space-y-3">
              {subs.map((s) => (
                <li key={s.k}>
                  <div className="mb-1 flex items-center justify-between gap-3 text-xs">
                    <span className="text-ink-dim">{s.k}</span>
                    <span className="font-mono text-ink-faint">{s.v?.toFixed(1)}</span>
                  </div>
                  <ScoreBar value={s.v ?? 0} floor={SUB_SCORE_FLOOR} />
                </li>
              ))}
              <li className="pt-1 text-[11px] text-ink-faint">
                Gold tick = floor {SUB_SCORE_FLOOR} — every sub-score must clear it.
              </li>
            </ul>
          ) : (
            <p className="text-[11px] leading-5 text-ink-faint">
              Six sub-scores ({SUB_SCORES.join(" · ")}) weren&apos;t recorded for this run — the gate can&apos;t be
              fully re-verified from stored scores. Regenerate for a full gated report.
            </p>
          )}

          <details className="text-xs text-ink-faint">
            <summary className="cursor-pointer hover:text-ink-dim">Raw scores JSON</summary>
            <pre className="mt-2 max-h-60 overflow-auto rounded-lg border border-line bg-page p-3 text-[11px] text-ink-faint">
              {JSON.stringify(raw, null, 2)}
            </pre>
          </details>
        </div>
      )}
    </SectionCard>
  );
}

/* ── live post vs local (published articles) ───────────────────────────── */

function Pane({ label, note, body }: { label: string; note?: string; body: string }) {
  return (
    <div className="min-w-0">
      <p className="mb-1.5 text-xs font-medium text-ink-dim">
        {label} {note ? <span className="font-normal text-ink-faint">({note})</span> : null}
      </p>
      <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-line bg-page p-3 font-mono text-[11px] leading-5 text-ink-faint">
        {body}
      </pre>
    </div>
  );
}

function LivePostCard({
  wpPostId,
  wpUrl,
  markdown,
  words,
  lastEditAt,
  livePost,
  liveError,
}: {
  wpPostId: number;
  wpUrl: string;
  markdown: string;
  words: number;
  lastEditAt: string;
  livePost: WpPostReadback | null;
  liveError: string;
}) {
  return (
    <SectionCard
      title={`Live post vs local — WP #${wpPostId}`}
      right={
        livePost?.url || wpUrl ? (
          <a
            href={livePost?.url || wpUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
          >
            open live post <ExternalLink className="h-3 w-3" aria-hidden />
          </a>
        ) : undefined
      }
    >
      {liveError ? (
        <div className="mb-3">
          <Alert tone="warn">Live readback unavailable — {liveError}</Alert>
        </div>
      ) : null}
      {livePost ? (
        <p className="mb-3 font-mono text-[11px] text-ink-faint">
          live: {livePost.status} · modified {livePost.modified ? livePost.modified.slice(0, 19).replace("T", " ") : "—"} ·{" "}
          {livePost.content_raw.length.toLocaleString()} chars · {livePost.categories.length} categories
        </p>
      ) : null}
      <div className="grid gap-3 md:grid-cols-2">
        <Pane
          label="Local markdown"
          note={`${words} words${lastEditAt ? ` · last edit ${lastEditAt}` : " · never edited"}`}
          body={markdown || "—"}
        />
        <Pane
          label="WordPress live"
          note="raw blocks, context=edit"
          body={livePost ? livePost.content_raw : "readback unavailable — check WP config on the engine instance"}
        />
      </div>
      <p className="mt-3 text-[11px] leading-5 text-ink-faint">
        Local edits do not touch the live post until <span className="text-ink-dim">Refresh live post</span> re-renders
        this markdown onto the existing WP post. FAQ + Article JSON-LD ride along on every refresh.
      </p>
    </SectionCard>
  );
}

/* ── media tab ─────────────────────────────────────────────────────────── */

function MediaPanel({ articleId, images }: { articleId: number; images: MediaImage[] }) {
  return (
    <SectionCard title={`Media (${images.length})`}>
      {images.length === 0 ? (
        <p className="text-xs leading-5 text-ink-dim">
          No art staged yet. Once a draft exists, <span className="text-ink">Stage images</span> (header
          action — publishing also auto-stages) generates the featured thumbnail plus section-aware
          inline art.
        </p>
      ) : (
        <>
          <p className="mb-3 text-xs leading-5 text-ink-faint">
            Thumbnails stream through the console&apos;s engine proxy; badges come from each row&apos;s{" "}
            <code className="font-mono text-[11px]">qa</code> block (Jev style pick + VLM lanes). Staged files
            live in the engine staging dir. <span className="text-ink-dim">Regenerate</span> re-runs that one
            slot (featured, or the section an inline image is injected before) and spends image credits.
          </p>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {images.map((img, i) => {
              const name = typeof img.path === "string" ? (img.path.split(/[\\/]/).pop() ?? "") : "";
              return (
                <MediaCard
                  key={`${img.slot || "img"}-${i}`}
                  articleId={articleId}
                  image={img}
                  extra={
                    name ? (
                      <form action={regenerateImageAction}>
                        <input type="hidden" name="id" value={articleId} />
                        <input type="hidden" name="name" value={name} />
                        <PendingButton
                          className={`${BTN_GOLD} w-full`}
                          confirmMessage={CONFIRM.regenerate}
                          pendingLabel="Regenerating…"
                        >
                          Regenerate
                        </PendingButton>
                      </form>
                    ) : null
                  }
                />
              );
            })}
          </div>
        </>
      )}
    </SectionCard>
  );
}

/* ── SEO & meta tab ────────────────────────────────────────────────────── */

function SerpPreview({ article }: { article: ArticleDetail }) {
  const title = article.seo?.title || article.title || "";
  const url = article.url || (article.slug ? `/${article.slug}` : "");
  const desc = article.seo?.description || article.excerpt || "";
  const focus = str(article.seo?.focus_keyword);
  const longTitle = title.length > 60;
  const longDesc = desc.length > 160;
  return (
    <SectionCard title="SERP preview">
      <div className="rounded-lg border border-line bg-surface/50 px-4 py-3">
        <p className={`truncate text-base ${longTitle ? "text-amber-300" : "text-sky-300"}`}>
          {title || "—"}
        </p>
        <p className="mt-0.5 truncate text-xs text-emerald-300/90">{url || "no URL — site base_url + slug"}</p>
        <p className={`mt-1 line-clamp-2 text-xs leading-5 ${longDesc ? "text-amber-300/90" : "text-ink-dim"}`}>
          {desc || "No meta description — the brief description or meta summary fills this on delivery."}
        </p>
      </div>
      <div className="mt-2 flex flex-wrap gap-4 font-mono text-[11px] text-ink-faint">
        <span className={longTitle ? "text-amber-300" : undefined}>title {title.length}/60</span>
        <span className={longDesc ? "text-amber-300" : undefined}>desc {desc.length}/160</span>
        {focus ? <span>focus “{focus}”</span> : null}
      </div>
    </SectionCard>
  );
}

function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1 border-b border-line/60 py-2.5 last:border-b-0 sm:grid-cols-[150px_1fr]">
      <dt className="text-xs text-ink-faint">{label}</dt>
      <dd className="min-w-0 break-words text-xs text-ink-dim">{children}</dd>
    </div>
  );
}

/* ── activity tab ──────────────────────────────────────────────────────── */

function ActivityPanel({ audit, costs }: { audit: LogsView["audit"]; costs: LogsView["costs"] }) {
  return (
    <div className="space-y-4">
      <SectionCard
        title={`Audit rows (${audit.length})`}
        right={
          <Link href="/logs" className="text-xs text-accent hover:underline">
            all logs →
          </Link>
        }
      >
        {audit.length === 0 ? (
          <p className="text-sm text-ink-faint">No audit rows for this article yet.</p>
        ) : (
          <ul className="space-y-1.5">
            {audit.map((a) => (
              <li key={a.id} className="overflow-hidden rounded-lg border border-line/60 bg-page/40">
                <details>
                  <summary className="flex cursor-pointer flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-xs">
                    <FileClock className="h-3.5 w-3.5 shrink-0 text-ink-faint" aria-hidden />
                    <span className="whitespace-nowrap font-mono text-[11px] text-ink-faint">
                      {a.created_at ? a.created_at.slice(0, 19).replace("T", " ") : "—"}
                    </span>
                    <span className={`font-mono ${actionColor(a.action)}`}>{a.action}</span>
                    <span className="max-w-md truncate font-mono text-[11px] text-ink-faint/80">
                      {JSON.stringify(a.payload)}
                    </span>
                  </summary>
                  <pre className="max-h-64 overflow-auto border-t border-line/60 px-3 py-2 font-mono text-[11px] leading-5 text-ink-faint">
                    {JSON.stringify(a.payload, null, 2)}
                  </pre>
                </details>
              </li>
            ))}
          </ul>
        )}
      </SectionCard>

      <SectionCard title={`Cost ledger (${costs.length})`}>
        {costs.length === 0 ? (
          <p className="text-sm text-ink-faint">
            No cost rows this article — legacy runs predate the ledger, or nothing billable happened yet.
          </p>
        ) : (
          <ul className="space-y-1.5">
            {costs.map((c) => (
              <li key={c.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-line/60 bg-page/40 px-3 py-2 text-xs">
                <span className="whitespace-nowrap font-mono text-[11px] text-ink-faint">
                  {c.created_at ? c.created_at.slice(0, 19).replace("T", " ") : "—"}
                </span>
                <span className="rounded-full border border-line px-2 py-0.5 text-[11px] text-ink-dim">{c.kind}</span>
                <span className="font-mono text-gold">{fmtCost(c.amount_usd)}</span>
                <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-ink-faint/80" title={JSON.stringify(c.detail)}>
                  {JSON.stringify(c.detail)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </SectionCard>
    </div>
  );
}

/* ── page ──────────────────────────────────────────────────────────────── */

export default async function ArticlePage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ err?: string; ok?: string; tab?: string }>;
}) {
  const { id } = await params;
  const { err = "", ok = "", tab = "content" } = await searchParams;
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
        <Link href="/articles" className="text-xs text-accent">
          ← articles
        </Link>
        <Alert tone="error">{error || "Article not found."}</Alert>
      </div>
    );
  }

  const meta = (article.meta || {}) as Record<string, unknown>;
  const brief = (meta.brief && typeof meta.brief === "object" ? meta.brief : {}) as Record<string, unknown>;
  const faqs = Array.isArray(meta.faqs)
    ? (meta.faqs as unknown[]).filter(
        (f): f is { question: string; answer: string } =>
          !!f &&
          typeof f === "object" &&
          typeof (f as { question?: unknown }).question === "string" &&
          typeof (f as { answer?: unknown }).answer === "string",
      )
    : [];
  const images = Array.isArray(meta.images) ? meta.images : [];
  const editLog = Array.isArray(meta.edit_log) ? (meta.edit_log as Record<string, unknown>[]) : [];
  const summary = typeof meta.summary === "string" ? meta.summary : "";
  const keyword = str(meta.keyword) || str(brief.keyword);
  const metaDesc = str(brief.description) || str(meta.summary);
  const tldr = str(article.seo?.tldr);
  const focus = str(article.seo?.focus_keyword);
  const markdown = article.markdown || "";
  const words = markdown.trim() ? markdown.trim().split(/\s+/).length : 0;
  const wpPostId = typeof meta.wp_post_id === "number" ? meta.wp_post_id : null;
  const wpUrl = str(meta.wp_url);
  const lastEditAt = str(editLog.length ? editLog[editLog.length - 1]?.at : "").slice(0, 19).replace("T", " ");

  const [sitesRes, logsRes] = await Promise.allSettled([
    engine<SiteList>(`/sites`),
    engine<LogsView>(`/logs?limit=200`),
  ]);
  const siteSlug =
    sitesRes.status === "fulfilled"
      ? (sitesRes.value.sites.find((s) => s.id === article!.site_id)?.slug ?? "")
      : "";
  const logs = logsRes.status === "fulfilled" ? logsRes.value : null;
  const articleAudit = logs ? logs.audit.filter((a) => a.article_id === article!.id) : [];
  const articleCosts = logs ? logs.costs.filter((c) => c.article_id === article!.id) : [];

  const activeTab = ["content", "seo", "media", "activity"].includes(tab) ? tab : "content";

  // Live readback only matters on the Content tab, only for published WP posts.
  let livePost: WpPostReadback | null = null;
  let liveError = "";
  if (activeTab === "content" && article.status === "published" && wpPostId) {
    try {
      livePost = await engine<WpPostReadback>(`/wp/posts/${wpPostId}`);
    } catch (e) {
      liveError = e instanceof Error ? e.message : String(e);
    }
  }

  /* checklist — same rule as lib/eval_gate.check_gate, honest about
     legacy runs whose scores only carry {overall}. */
  const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
  const overall = num(article.scores?.overall);
  const subs = SUB_SCORES.map((k) => ({ k, v: num(article.scores?.[k]) }));
  const subsPresent = subs.every((s) => s.v !== null);
  const gateFailures = [
    ...(overall !== null && overall < PUBLISH_THRESHOLD ? [`overall ${overall} < ${PUBLISH_THRESHOLD}`] : []),
    ...subs.filter((s) => s.v !== null && s.v < SUB_SCORE_FLOOR).map((s) => `${s.k} ${s.v} < floor ${SUB_SCORE_FLOOR}`),
  ];
  const gatePass = overall !== null && subsPresent && gateFailures.length === 0;

  let qualityValue: string;
  if (overall === null) qualityValue = "No eval recorded — run Generate first.";
  else if (gatePass) qualityValue = `overall ${overall} · all six sub-scores clear the ${SUB_SCORE_FLOOR} floor`;
  else if (!subsPresent && overall >= PUBLISH_THRESHOLD)
    qualityValue = `overall ${overall} · six sub-scores not recorded (pre-gate run)`;
  else if (!subsPresent) qualityValue = `overall ${overall} < ${PUBLISH_THRESHOLD} · sub-scores not recorded`;
  else qualityValue = gateFailures.join(" · ");

  const slugOk = SLUG_RE.test(article.slug) && article.slug.length <= 80;
  const checklist: ChecklistRow[] = [
    {
      key: "quality",
      label: "Quality gate",
      tier: overall === null ? "info" : gatePass ? "pass" : "warn",
      value: qualityValue,
      href: overall !== null ? "#scores" : undefined,
    },
    {
      key: "images",
      label: "Images staged",
      tier: images.length > 0 ? "pass" : article.status === "published" ? "info" : "warn",
      value:
        images.length > 0
          ? `${images.length} staged — featured + inline art ready`
          : article.status === "published"
            ? "None — published without staged inline art."
            : "None staged — Stage images before publishing (WP publish also auto-stages).",
      href: images.length > 0 ? "?tab=media" : undefined,
    },
    {
      key: "faqs",
      label: "FAQs",
      tier: faqs.length > 0 ? "pass" : "warn",
      value:
        faqs.length > 0
          ? `${faqs.length} Q/A pairs — FAQ JSON-LD rides along on delivery`
          : "None — no FAQ schema / AEO answer block on this article.",
      href: "?tab=seo#faqs",
    },
    {
      key: "slug",
      label: "Slug",
      tier: slugOk ? "pass" : "warn",
      value: slugOk ? `/${article.slug}` : `“${article.slug || "untitled"}” — invalid or missing; delivery falls back to a title-derived slug.`,
      href: "?tab=seo",
    },
  ];

  const canApprove = article.status !== "approved" && article.status !== "published";
  const canSendReview = ["generated", "approved", "needs_review"].includes(article.status);
  const canPublish = article.status === "approved";

  return (
    <div className="space-y-5">
      <PageHeaderLike
        article={article}
        siteSlug={siteSlug}
        keyword={keyword}
        words={words}
        editCount={editLog.length}
        headerActions={
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

      {err ? <Alert tone="error">{err}</Alert> : null}
      {ok ? <Alert tone="success">{ok}</Alert> : null}

      {/* tabs — plan §5: Content · SEO & meta · Media · Activity */}
      <nav aria-label="Article sections" className="flex flex-wrap items-center gap-1 border-b border-line">
        {[
          { key: "content", label: "Content" },
          { key: "seo", label: "SEO & meta" },
          { key: "media", label: "Media" },
          { key: "activity", label: "Activity", count: articleAudit.length },
        ].map((t) => (
          <Link
            key={t.key}
            href={`/articles/${article!.id}${t.key === "content" ? "" : `?tab=${t.key}`}`}
            aria-current={activeTab === t.key ? "page" : undefined}
            className={`flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm transition-colors ${
              activeTab === t.key
                ? "border-accent font-medium text-ink"
                : "border-transparent text-ink-faint hover:text-ink-dim"
            }`}
          >
            {t.label}
            {t.count ? (
              <span className="rounded-full bg-surface px-1.5 py-0.5 font-mono text-[10px] leading-none text-ink-faint">
                {t.count}
              </span>
            ) : null}
          </Link>
        ))}
      </nav>

      {activeTab === "content" ? (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="min-w-0 space-y-4">
            <ContentWorkspace articleId={article.id} markdown={markdown} editCount={editLog.length} />
            <ScoresCard overall={overall} subs={subs} subsPresent={subsPresent} raw={article.scores || {}} />
            {article.status === "published" && wpPostId ? (
              <LivePostCard
                wpPostId={wpPostId}
                wpUrl={wpUrl}
                markdown={markdown}
                words={words}
                lastEditAt={lastEditAt}
                livePost={livePost}
                liveError={liveError}
              />
            ) : null}
            {article.status === "published" && !wpPostId ? (
              <SectionCard title="Live delivery">
                <Alert tone="info">
                  Custom site — no remote post to read back and diff. After edits, re-pull{" "}
                  <code className="font-mono text-[11px]">GET /articles/{article.id}/content</code> at the site or
                  re-deliver the payload (&quot;Refresh live post&quot; re-renders it for pull).
                </Alert>
              </SectionCard>
            ) : null}
          </div>

          <div className="space-y-4">
            <Checklist rows={checklist} />
            <SectionCard title="Decision">
              <div className="space-y-3">
                {overall !== null && !gatePass && canApprove ? (
                  <Alert tone="warn">
                    {subsPresent
                      ? `Engine gate not clear: ${gateFailures.join("; ")}. Approve only as an explicit override.`
                      : "Six sub-scores weren't recorded for this run — the gate can't be fully re-verified from stored scores."}
                  </Alert>
                ) : null}
                {canApprove ? (
                  <form action={approveArticleAction} className="space-y-2">
                    <input type="hidden" name="id" value={article.id} />
                    <input type="hidden" name="approved" value="1" />
                    <input
                      name="note"
                      placeholder="Approval note - why it passes (optional)"
                      className="w-full rounded-md border border-line bg-page px-3 py-1.5 text-xs text-ink placeholder:text-ink-faint/70 focus:border-accent"
                    />
                    <PendingButton className={`${BTN_GOLD} w-full`} pendingLabel="Approving…">
                      Approve
                    </PendingButton>
                  </form>
                ) : null}
                {canSendReview ? (
                  <form action={approveArticleAction} className={canApprove ? "space-y-2 border-t border-line/60 pt-3" : "space-y-2"}>
                    <input type="hidden" name="id" value={article.id} />
                    <input type="hidden" name="approved" value="0" />
                    <input
                      name="note"
                      placeholder="Review note — why it's not ready / what changed"
                      className="w-full rounded-md border border-line bg-page px-3 py-1.5 text-xs text-ink placeholder:text-ink-faint/70 focus:border-accent"
                    />
                    <PendingButton className={`${BTN_GHOST} w-full`} pendingLabel="Sending…">
                      Send to review
                    </PendingButton>
                  </form>
                ) : null}
                {canPublish ? (
                  <form action={publishArticleAction} className="border-t border-line/60 pt-3">
                    <input type="hidden" name="id" value={article.id} />
                    <input type="hidden" name="mode" value="draft" />
                    <PendingButton
                      className={`${BTN_PRIMARY} w-full`}
                      confirmMessage={CONFIRM.publishDraft}
                      pendingLabel="Publishing…"
                    >
                      Publish (draft)
                    </PendingButton>
                  </form>
                ) : null}
                {article.status === "published" ? (
                  <p className="border-t border-line/60 pt-3 text-[11px] leading-5 text-ink-faint">
                    Published. Header actions: <span className="text-ink-dim">Refresh live post</span> pushes the current
                    markdown to the live post; <span className="text-ink-dim">Stage images</span> fills inline art.
                  </p>
                ) : null}
                {article.status === "briefed" ? (
                  <p className="border-t border-line/60 pt-3 text-[11px] leading-5 text-ink-faint">
                    Briefed — <span className="text-ink-dim">Generate</span> writes, evaluates and scores the draft
                    before this becomes a real approval decision.
                  </p>
                ) : null}
              </div>
            </SectionCard>
          </div>
        </div>
      ) : null}

      {activeTab === "seo" ? (
        <div className="space-y-4">
          <SerpPreview article={article} />

          <SectionCard title="Fields">
            <dl>
              <FieldRow label="Title">{article.title || "—"}</FieldRow>
              <FieldRow label="Slug">
                <span className="inline-flex items-center gap-1.5 font-mono">
                  /{article.slug}
                  {slugOk ? (
                    <CircleCheck className="h-3.5 w-3.5 text-emerald-400" aria-hidden />
                  ) : (
                    <TriangleAlert className="h-3.5 w-3.5 text-amber-400" aria-hidden />
                  )}
                </span>
              </FieldRow>
              <FieldRow label="Focus keyphrase">{focus || keyword || "—"}</FieldRow>
              <FieldRow label="Meta description">{metaDesc || "—"}</FieldRow>
              <FieldRow label="TL;DR (AEO)">{tldr || "—"}</FieldRow>
              <FieldRow label="Summary">{summary || "—"}</FieldRow>
              <FieldRow label="Delivery URL">
                {article.url ? (
                  <a href={article.url} target="_blank" rel="noreferrer" className="text-accent hover:underline">
                    {article.url}
                  </a>
                ) : (
                  "— set the site base_url to get one"
                )}
              </FieldRow>
            </dl>
            <p className="mt-3 border-t border-line/60 pt-3 text-[11px] leading-5 text-ink-faint">
              Title / slug / meta are derived from the brief + generator and travel with the delivery payload.
              They&apos;re operator-editable in the card below — every change lands in the payload immediately; an
              approved article reopens for review, a published one picks the values up on the next refresh.
            </p>
          </SectionCard>

          <SectionCard title="Edit meta fields">
            <form action={patchMetaAction} className="space-y-3">
              <input type="hidden" name="id" value={article.id} />
              <FieldRow label="Title">
                <input type="text" name="title" defaultValue={article.title || ""} className={FIELD_INPUT} />
              </FieldRow>
              <FieldRow label="Slug">
                <input type="text" name="slug" defaultValue={article.slug || ""} className={FIELD_INPUT} />
              </FieldRow>
              <FieldRow label="Focus keyphrase">
                <input
                  type="text"
                  name="focus_keyword"
                  defaultValue={focus || keyword || ""}
                  className={FIELD_INPUT}
                />
              </FieldRow>
              <FieldRow label="Summary">
                <input type="text" name="summary" defaultValue={summary || ""} className={FIELD_INPUT} />
              </FieldRow>
              <FieldRow label="TL;DR (AEO)">
                <input type="text" name="tldr" defaultValue={tldr || ""} className={FIELD_INPUT} />
              </FieldRow>
              <div className="flex flex-wrap items-center gap-3 border-t border-line/60 pt-3">
                <PendingButton className={BTN_PRIMARY} pendingLabel="Saving…">
                  Save meta
                </PendingButton>
                <p className="text-[11px] leading-5 text-ink-faint">
                  Empty fields are left unchanged. Focus keyphrase writes the article&apos;s registered phrase.
                </p>
              </div>
            </form>
          </SectionCard>

            <SectionCard title={`FAQs (${faqs.length})`} id="faqs">
            {faqs.length === 0 ? (
              <p className="text-sm text-ink-faint">No FAQs yet — they arrive with Generate (5–7 per the brief gate).</p>
            ) : (
              <div className="space-y-4">
                <ol className="space-y-3">
                  {faqs.map((f, i) => (
                    <li key={i} className="text-xs">
                      <p className="font-medium text-ink">{f.question}</p>
                      <p className="mt-0.5 leading-5 text-ink-dim">{f.answer}</p>
                    </li>
                  ))}
                </ol>
                <details className="text-xs text-ink-faint">
                  <summary className="cursor-pointer hover:text-ink-dim">Raw FAQ JSON</summary>
                  <pre className="mt-2 max-h-60 overflow-auto rounded-lg border border-line bg-page p-3 text-[11px] text-ink-faint">
                    {JSON.stringify(meta.faqs, null, 2)}
                  </pre>
                </details>
              </div>
            )}
          </SectionCard>

          <SectionCard title="JSON-LD schema">
            {article.schema?.article || article.schema?.faq ? (
              <div className="space-y-2">
                {article.schema?.article ? (
                  <details className="text-xs">
                    <summary className="flex cursor-pointer items-center gap-1.5 text-ink-dim hover:text-ink">
                      <Braces className="h-3.5 w-3.5" aria-hidden /> Article schema
                    </summary>
                    <pre className="mt-2 max-h-72 overflow-auto rounded-lg border border-line bg-page p-3 text-[11px] leading-5 text-ink-faint">
                      {JSON.stringify(article.schema.article, null, 2)}
                    </pre>
                  </details>
                ) : null}
                {article.schema?.faq ? (
                  <details className="text-xs">
                    <summary className="flex cursor-pointer items-center gap-1.5 text-ink-dim hover:text-ink">
                      <Braces className="h-3.5 w-3.5" aria-hidden /> FAQ schema
                    </summary>
                    <pre className="mt-2 max-h-72 overflow-auto rounded-lg border border-line bg-page p-3 text-[11px] leading-5 text-ink-faint">
                      {JSON.stringify(article.schema.faq, null, 2)}
                    </pre>
                  </details>
                ) : null}
              </div>
            ) : (
              <p className="text-sm text-ink-faint">
                No schema yet — Article + FAQ JSON-LD ships with delivery once the article has content.
              </p>
            )}
          </SectionCard>
        </div>
      ) : null}

      {activeTab === "media" ? <MediaPanel articleId={article.id} images={images as MediaImage[]} /> : null}
      {activeTab === "activity" ? <ActivityPanel audit={articleAudit} costs={articleCosts} /> : null}
    </div>
  );
}

/* Header block — title + identity strip + per-status header actions. Kept a
   local component so the page body above stays readable. */
function PageHeaderLike({
  article,
  siteSlug,
  keyword,
  words,
  editCount,
  headerActions,
}: {
  article: ArticleDetail;
  siteSlug: string;
  keyword: string;
  words: number;
  editCount: number;
  headerActions: React.ReactNode;
}) {
  return (
    <>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-tight text-ink">{article.title || `#${article.id}`}</h1>
          <p className="mt-1 text-sm text-ink-dim">
            #{article.id}
            {siteSlug ? ` · ${siteSlug}` : ""}
            {keyword ? ` · “${keyword}”` : ""}
          </p>
        </div>
        {headerActions ? <div className="flex flex-wrap items-center gap-2">{headerActions}</div> : null}
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-line pb-4">
        <Pill status={article.status} />
        <span className="font-mono text-xs text-ink-faint">{words} words</span>
        <span className="font-mono text-xs text-ink-faint">
          {article.scores && Number(article.scores.overall) > 0
            ? `overall ${fmtScore(Number(article.scores.overall))}`
            : "no score"}
        </span>
        <span className="font-mono text-xs text-ink-faint">{fmtCost(article.cost_usd)}</span>
        {editCount > 0 ? (
          <span className="text-xs text-ink-faint">
            {editCount} edit{editCount === 1 ? "" : "s"} logged
          </span>
        ) : null}
        <Link href="/articles" className="ml-auto text-xs text-ink-faint hover:text-ink-dim">
          ← content pipeline
        </Link>
      </div>
    </>
  );
}
