"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { engine, EngineError } from "@/lib/engine";
import { requireOperator } from "@/lib/guard";

function back(articlesId?: number, err?: string): string {
  const base = articlesId ? `/articles/${articlesId}` : "/articles";
  return err ? `${base}?err=${encodeURIComponent(err)}` : base;
}

function errorOf(e: unknown): string {
  return e instanceof EngineError ? e.message : `unexpected error: ${String(e)}`;
}

/** Positive integer id from the form, else bounce back — never `/articles/NaN/...` (plan CON-10). */
function idOf(formData: FormData, fallback = "/articles"): number {
  const n = Number(formData.get("id"));
  if (!Number.isInteger(n) || n <= 0) {
    redirect(`${fallback}?err=${encodeURIComponent("invalid id")}`);
  }
  return n;
}

const PUBLISH_MODES = new Set(["draft", "publish", "auto"]);

/* Publishing from the Publish queue returns to the queue; anything else
   lands back on the article detail. Allowlist — never an open redirect. */
const PUBLISH_RETURN = new Set(["/", "/approvals", "/publish"]);

// "Add keyword" on the Keywords (ledger) tab — mirrors adding a row in the
// sheet: POST /articles binds/creates the ledger row (§5.16 lineage) and the
// article lands `briefed`, then we open its detail to continue Generate →
// Approve → Publish.
export async function createArticleAction(formData: FormData) {
  await requireOperator(formData);
  const kwBase = "/articles/keywords";
  const keyword = String(formData.get("keyword") || "").trim();
  const title = String(formData.get("title") || "").trim();
  const site = String(formData.get("site") || "").trim();
  const transcript = String(formData.get("transcript") || "").trim();
  const instant = formData.get("instant") === "1" || formData.get("instant") === "true";

  if (!keyword) redirect(`${kwBase}?err=${encodeURIComponent("keyword is required")}`);
  if (!site) {
    redirect(
      `${kwBase}?err=${encodeURIComponent("no site — create one on the Sites screen first")}`,
    );
  }
  // redirect() throws NEXT_REDIRECT, so it must not run inside the try (CON-01):
  // pick the destination in try/catch, redirect once after.
  let target: string;
  try {
    const briefPayload: Record<string, unknown> = {};
    if (title) briefPayload.title = title;
    if (transcript) {
      briefPayload.source_transcript = transcript;
      briefPayload.notes = `Generated from transcript:\n\n${transcript.slice(0, 1000)}...`;
    }

    const res = await engine<{ id: number; status: string; instant_triggered?: boolean }>(`/articles`, {
      method: "POST",
      json: {
        site_slug: site,
        keyword,
        brief: briefPayload,
        instant,
      },
    });
    revalidatePath("/");
    revalidatePath("/articles");
    revalidatePath(kwBase);
    const msg = instant
      ? "Topic queued with Instant Generation! Drafting and image staging started in background."
      : "Topic added to the ledger.";
    target = `/articles/${res.id}?ok=${encodeURIComponent(msg)}`;
  } catch (e) {
    target = `${kwBase}?err=${encodeURIComponent(errorOf(e))}`;
  }
  redirect(target);
}

export async function approveArticleAction(formData: FormData) {
  await requireOperator(formData);
  const id = idOf(formData);
  const approved = formData.get("approved") === "1";
  const from = String(formData.get("from") || "");
  const note = String(formData.get("note") || "");
  const returnTo = from && PUBLISH_RETURN.has(from) ? from : back(id);
  try {
    await engine(`/articles/${id}/approve`, {
      method: "POST",
      json: { approved, note },
    });
  } catch (e) {
    redirect(from && PUBLISH_RETURN.has(from) ? `${from}?err=${encodeURIComponent(errorOf(e))}` : back(id, errorOf(e)));
  }
  revalidatePath("/");
  revalidatePath("/articles");
  revalidatePath("/approvals");
  revalidatePath("/publish");
  const msg = approved ? `Article #${id} approved.` : `Article #${id} sent to review.`;
  if (returnTo.includes("?")) {
    redirect(`${returnTo}&ok=${encodeURIComponent(msg)}`);
  } else {
    redirect(`${returnTo}?ok=${encodeURIComponent(msg)}`);
  }
}

export async function publishArticleAction(formData: FormData) {
  await requireOperator(formData);
  const id = idOf(formData);
  const rawMode = String(formData.get("mode") || "draft");
  const mode = PUBLISH_MODES.has(rawMode) ? rawMode : "draft";
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
  const msg = mode === "draft" ? `Article #${id} pushed as a draft.` : `Article #${id} published.`;
  if (queued) {
    redirect(`${from}?ok=${encodeURIComponent(msg)}`);
  }
  redirect(`${back(id)}?ok=${encodeURIComponent(msg)}`);
}

export async function generateArticleAction(formData: FormData) {
  await requireOperator(formData);
  const id = idOf(formData);
  try {
    await engine(`/articles/${id}/generate`, { method: "POST", json: {} });
  } catch (e) {
    redirect(back(id, errorOf(e)));
  }
  revalidatePath("/articles");
  redirect(`${back(id)}?ok=${encodeURIComponent(`Article #${id} generated.`)}`);
}

export async function refreshArticleAction(formData: FormData) {
  await requireOperator(formData);
  const id = idOf(formData);
  try {
    await engine(`/articles/${id}/refresh`, { method: "POST" });
  } catch (e) {
    redirect(back(id, errorOf(e)));
  }
  redirect(`${back(id)}?ok=${encodeURIComponent(`Article #${id} refreshed on the live site.`)}`);
}

export async function stageImagesAction(formData: FormData) {
  await requireOperator(formData);
  const id = idOf(formData);
  try {
    await engine(`/articles/${id}/stage-images`, { method: "POST" });
  } catch (e) {
    redirect(back(id, errorOf(e)));
  }
  redirect(`${back(id)}?ok=${encodeURIComponent(`Images staged for article #${id}.`)}`);
}

/* Per-image regenerate (Media tab): re-runs one staged slot through the same
   generation path as stage-images and redirects back with the cost detail in
   ?ok. Spends image credits — the button that calls this is confirm-gated. */
export async function regenerateImageAction(formData: FormData) {
  await requireOperator(formData);
  const id = idOf(formData);
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
  await requireOperator(formData);
  const id = idOf(formData);
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
  redirect(`${back(id)}?ok=${encodeURIComponent(`Meta saved for article #${id}.`)}`);
}

export async function patchContentAction(formData: FormData) {
  await requireOperator(formData);
  const id = idOf(formData);
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

export async function deleteArticleAction(formData: FormData) {
  await requireOperator(formData);
  const id = idOf(formData);
  try {
    await engine(`/articles/${id}`, { method: "DELETE" });
  } catch (e) {
    redirect(back(id, errorOf(e)));
  }
  revalidatePath("/");
  revalidatePath("/articles");
  redirect("/articles?deleted=" + id);
}

export async function deleteKeywordAction(formData: FormData) {
  await requireOperator(formData);
  const id = idOf(formData, "/articles/keywords");
  const site = String(formData.get("site") || "");
  try {
    await engine(`/keywords/${id}`, { method: "DELETE" });
  } catch (e) {
    redirect(`/articles/keywords?site=${encodeURIComponent(site)}&err=${encodeURIComponent(errorOf(e))}`);
  }
  revalidatePath("/");
  revalidatePath("/articles/keywords");
  redirect(`/articles/keywords?site=${encodeURIComponent(site)}&deleted=${id}`);
}

export async function prioritizeKeywordAction(formData: FormData) {
  await requireOperator(formData);
  const id = idOf(formData, "/articles/keywords");
  const site = String(formData.get("site") || "");
  try {
    await engine(`/keywords/${id}/prioritize`, { method: "POST" });
  } catch (e) {
    redirect(`/articles/keywords?site=${encodeURIComponent(site)}&err=${encodeURIComponent(errorOf(e))}`);
  }
  revalidatePath("/");
  revalidatePath("/articles/keywords");
  redirect(`/articles/keywords?site=${encodeURIComponent(site)}&ok=${encodeURIComponent("Keyword boosted to top priority!")}`);
}
