"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { engine, EngineError } from "@/lib/engine";
import { requireSession } from "@/lib/session";

function back(articlesId?: number, err?: string): string {
  const base = articlesId ? `/articles/${articlesId}` : "/articles";
  return err ? `${base}?err=${encodeURIComponent(err)}` : base;
}

function errorOf(e: unknown): string {
  return e instanceof EngineError ? e.message : `unexpected error: ${String(e)}`;
}

// "Add keyword" on the Keywords (ledger) tab — mirrors adding a row in the
// sheet: POST /articles binds/creates the ledger row (§5.16 lineage) and the
// article lands `briefed`, then we open its detail to continue Generate →
// Approve → Publish.
export async function createArticleAction(formData: FormData) {
  await requireSession();
  const kwBase = "/articles/keywords";
  const keyword = String(formData.get("keyword") || "").trim();
  const title = String(formData.get("title") || "").trim();
  const site = String(formData.get("site") || "").trim();
  if (!keyword) redirect(`${kwBase}?err=${encodeURIComponent("keyword is required")}`);
  if (!site) {
    redirect(
      `${kwBase}?err=${encodeURIComponent("no site — create one on the Sites screen first")}`,
    );
  }
  try {
    const res = await engine<{ id: number; status: string }>(`/articles`, {
      method: "POST",
      json: { site_slug: site, keyword, brief: title ? { title } : {} },
    });
    revalidatePath("/");
    revalidatePath("/articles");
    revalidatePath(kwBase);
    redirect(`/articles/${res.id}`);
  } catch (e) {
    redirect(`${kwBase}?err=${encodeURIComponent(errorOf(e))}`);
  }
}

export async function approveArticleAction(formData: FormData) {
  await requireSession();
  const id = Number(formData.get("id"));
  const approved = formData.get("approved") === "1";
  // The detail screen's "Send to review" carries a note; audit rows keep it.
  const note = String(formData.get("note") || "").trim() || "console";
  try {
    await engine(`/articles/${id}/approve`, {
      method: "POST",
      json: { approved, note },
    });
  } catch (e) {
    redirect(back(id, errorOf(e)));
  }
  revalidatePath("/");
  revalidatePath("/articles");
  revalidatePath("/approvals");
  revalidatePath(back(id));
  redirect(back(id));
}

/* Publishing from the Publish queue returns to the queue; anything else
   lands back on the article detail. Allowlist — never an open redirect. */
const PUBLISH_RETURN = new Set(["/approvals", "/publish"]);

export async function publishArticleAction(formData: FormData) {
  await requireSession();
  const id = Number(formData.get("id"));
  const mode = String(formData.get("mode") || "draft");
  const from = String(formData.get("from") || "");
  const queued = PUBLISH_RETURN.has(from);
  try {
    await engine(`/articles/${id}/publish`, { method: "POST", json: { mode } });
  } catch (e) {
    redirect(queued ? `${from}?err=${encodeURIComponent(errorOf(e))}` : back(id, errorOf(e)));
  }
  revalidatePath("/");
  revalidatePath("/articles");
  revalidatePath("/publish");
  if (queued) redirect(from);
  redirect(back(id));
}

export async function generateArticleAction(formData: FormData) {
  await requireSession();
  const id = Number(formData.get("id"));
  try {
    await engine(`/articles/${id}/generate`, { method: "POST", json: {} });
  } catch (e) {
    redirect(back(id, errorOf(e)));
  }
  revalidatePath("/articles");
  redirect(back(id));
}

export async function refreshArticleAction(formData: FormData) {
  await requireSession();
  const id = Number(formData.get("id"));
  try {
    await engine(`/articles/${id}/refresh`, { method: "POST" });
  } catch (e) {
    redirect(back(id, errorOf(e)));
  }
  redirect(back(id));
}

export async function stageImagesAction(formData: FormData) {
  await requireSession();
  const id = Number(formData.get("id"));
  try {
    await engine(`/articles/${id}/stage-images`, { method: "POST" });
  } catch (e) {
    redirect(back(id, errorOf(e)));
  }
  redirect(back(id));
}

/* Per-image regenerate (Media tab): re-runs one staged slot through the same
   generation path as stage-images and redirects back with the cost detail in
   ?ok. Spends image credits — the button that calls this is confirm-gated. */
export async function regenerateImageAction(formData: FormData) {
  await requireSession();
  const id = Number(formData.get("id"));
  const name = String(formData.get("name") || "").trim();
  if (!name) redirect(back(id, "image name missing"));
  let detail = "";
  let skipped = "";
  try {
    const res = await engine<{ detail?: string; skipped?: string }>(
      `/articles/${id}/images/${encodeURIComponent(name)}/regenerate`,
      { method: "POST" },
    );
    detail = res?.detail || "";
    skipped = res?.skipped || "";
  } catch (e) {
    redirect(back(id, errorOf(e)));
  }
  revalidatePath(back(id));
  if (skipped) redirect(back(id, `image not regenerated — ${skipped}`));
  redirect(detail ? `${back(id)}?ok=${encodeURIComponent(detail)}` : back(id));
}

export async function patchMetaAction(formData: FormData) {
  await requireSession();
  const id = Number(formData.get("id"));
  const title = String(formData.get("title") || "");
  const slug = String(formData.get("slug") || "");
  const focus_keyword = String(formData.get("focus_keyword") || "");
  const summary = String(formData.get("summary") || "");
  const tldr = String(formData.get("tldr") || "");
  const fields: Record<string, string> = {};
  if (title) fields.title = title;
  if (slug) fields.slug = slug;
  if (focus_keyword) fields.focus_keyword = focus_keyword;
  if (summary) fields.summary = summary;
  if (tldr) fields.tldr = tldr;
  if (Object.keys(fields).length === 0) {
    redirect(back(id, "no fields supplied"));
  }
  try {
    await engine(`/articles/${id}/meta`, { method: "PATCH", json: fields });
  } catch (e) {
    redirect(back(id, errorOf(e)));
  }
  revalidatePath("/");
  revalidatePath("/articles");
  redirect(back(id));
}

export async function patchContentAction(formData: FormData) {
  await requireSession();
  const id = Number(formData.get("id"));
  const content_md = String(formData.get("content_md") || "");
  const note = String(formData.get("note") || "");
  try {
    await engine(`/articles/${id}/content`, {
      method: "PATCH",
      json: { content_md, note },
    });
  } catch (e) {
    redirect(back(id, errorOf(e)));
  }
  revalidatePath(back(id));
  revalidatePath("/articles");
  redirect(back(id));
}
