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

export async function approveArticleAction(formData: FormData) {
  await requireSession();
  const id = Number(formData.get("id"));
  const approved = formData.get("approved") === "1";
  try {
    await engine(`/articles/${id}/approve`, {
      method: "POST",
      json: { approved, note: "console" },
    });
  } catch (e) {
    redirect(back(id, errorOf(e)));
  }
  revalidatePath("/");
  revalidatePath("/articles");
  revalidatePath(back(id));
  redirect(back(id));
}

export async function publishArticleAction(formData: FormData) {
  await requireSession();
  const id = Number(formData.get("id"));
  const mode = String(formData.get("mode") || "draft");
  try {
    await engine(`/articles/${id}/publish`, { method: "POST", json: { mode } });
  } catch (e) {
    redirect(back(id, errorOf(e)));
  }
  revalidatePath("/");
  revalidatePath("/articles");
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
