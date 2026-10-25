"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { engine, EngineError } from "@/lib/engine";
import { requireSession } from "@/lib/session";

export async function runStageAction(formData: FormData) {
  await requireSession();
  const stage = String(formData.get("stage") || "");
  const site = String(formData.get("site") || formData.get("site_slug") || "").trim();
  try {
    await engine(`/run/${encodeURIComponent(stage)}`, {
      method: "POST",
      json: site ? { site_slug: site } : {},
    });
  } catch (e) {
    const msg = e instanceof EngineError ? e.message : String(e);
    redirect(`/stages?err=${encodeURIComponent(msg)}`);
  }
  revalidatePath("/");
  redirect(`/stages?started=${encodeURIComponent(stage)}`);
}
