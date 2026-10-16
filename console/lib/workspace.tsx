"use client";

// Article-detail Content tab workspace (docs/console-dashboard-plan.md §5,
// Wave 2): rendered-markdown preview ⟷ raw textarea edit. Markdown renders
// through react-markdown — no raw HTML, never dangerouslySetInnerHTML — and
// is styled by the .prose-console block in globals.css. Saves post through
// the existing patchContentAction, so the edit-log / audit behavior is
// untouched. The mock's ⟨⟷⟩ toggle lives in the card header.

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Eye, PencilLine } from "lucide-react";
import { patchContentAction } from "@/actions/articles";
import { BTN_GHOST, BTN_PRIMARY, SectionCard } from "./ui";
import { PendingButton } from "./interactive";

export function ContentWorkspace({
  articleId,
  markdown,
  editCount,
}: {
  articleId: number;
  markdown: string;
  editCount: number;
}) {
  // A briefed article has nothing to preview — open in edit (the header
  // Generate button fills it), anything with content opens rendered.
  const [mode, setMode] = useState<"preview" | "edit">(markdown ? "preview" : "edit");

  const seg = (active: boolean) =>
    `flex items-center gap-1.5 rounded px-2.5 py-1 transition-colors ${
      active ? "bg-surface font-medium text-ink" : "text-ink-faint hover:text-ink-dim"
    }`;

  return (
    <SectionCard
      title="Content"
      right={
        <div role="tablist" aria-label="Content mode" className="flex items-center gap-0.5 rounded-md border border-line bg-page p-0.5 text-xs">
          <button
            type="button"
            role="tab"
            aria-selected={mode === "preview"}
            onClick={() => setMode("preview")}
            className={seg(mode === "preview")}
          >
            <Eye className="h-3.5 w-3.5" aria-hidden />
            Preview
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "edit"}
            onClick={() => setMode("edit")}
            className={seg(mode === "edit")}
          >
            <PencilLine className="h-3.5 w-3.5" aria-hidden />
            Edit
          </button>
        </div>
      }
    >
      {mode === "preview" ? (
        markdown ? (
          <article className="prose-console max-h-[44rem] overflow-y-auto pr-1">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
          </article>
        ) : (
          <p className="py-6 text-center text-sm text-ink-faint">
            No content yet — run <span className="font-medium text-ink-dim">Generate</span> above, or switch to
            Edit and write the first version.
          </p>
        )
      ) : (
        <form action={patchContentAction} className="space-y-3">
          <input type="hidden" name="id" value={articleId} />
          <textarea
            name="content_md"
            defaultValue={markdown}
            rows={24}
            placeholder="Content markdown — empty for briefed articles until Generate runs."
            className="w-full rounded-lg border border-line bg-page px-3 py-2 font-mono text-xs leading-5 text-ink-dim outline-none focus:border-accent"
          />
          <div className="flex flex-wrap items-center gap-3">
            <input
              name="note"
              placeholder="Edit note (optional)"
              className="rounded-md border border-line bg-page px-3 py-1.5 text-xs text-ink placeholder:text-ink-faint/70 focus:border-accent"
            />
            <PendingButton className={BTN_PRIMARY} pendingLabel="Saving…">
              Save content
            </PendingButton>
            <button type="button" onClick={() => setMode("preview")} className={BTN_GHOST}>
              Back to preview
            </button>
          </div>
          <p className="text-[11px] text-ink-faint">
            Every save is edit-logged. An <span className="text-gold">approved</span> article reopens to
            <span className="text-violet-300"> generated</span> so the approve gate runs again on the edited text.
          </p>
        </form>
      )}
      {editCount > 0 ? (
        <p className="mt-3 border-t border-line/60 pt-3 text-[11px] text-ink-faint">
          {editCount} edit{editCount === 1 ? "" : "s"} logged · edits don&apos;t re-run the quality eval — regenerate
          for a fresh score, or refresh the live post to push the text out.
        </p>
      ) : null}
    </SectionCard>
  );
}
