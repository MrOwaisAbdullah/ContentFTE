"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { engine, EngineError } from "@/lib/engine";
import { requireSession } from "@/lib/session";
import { setCurrentInstance } from "@/lib/instances";
import { generateInstanceEnv } from "@/lib/provision";

function errorOf(e: unknown): string {
  return e instanceof EngineError ? e.message : `unexpected error: ${String(e)}`;
}

export async function switchInstanceAction(formData: FormData) {
  await requireSession();
  const name = String(formData.get("instance") || "");
  const ok = await setCurrentInstance(name);
  if (!ok) redirect("/?err=" + encodeURIComponent(`unknown instance: ${name}`));
  revalidatePath("/", "layout");
  redirect("/");
}

export async function createSiteAction(formData: FormData) {
  await requireSession();
  const slug = String(formData.get("slug") || "").trim();
  const name = String(formData.get("name") || "").trim() || slug;
  const site_type = String(formData.get("site_type") || "wordpress");
  const base_url = String(formData.get("base_url") || "").trim();
  if (!slug || !base_url) {
    redirect("/sites?err=" + encodeURIComponent("slug and base_url are required"));
  }
  try {
    await engine("/sites", { method: "POST", json: { slug, name, site_type, base_url } });
  } catch (e) {
    redirect("/sites?err=" + encodeURIComponent(errorOf(e)));
  }
  revalidatePath("/sites");
  redirect(`/sites?created=${encodeURIComponent(slug)}`);
}

export interface EnvResult {
  env?: string;
  slug?: string;
  sdkKey?: string;
  err?: string;
  siteCreated?: string;
}

export async function generateEnvAction(
  _prev: EnvResult,
  formData: FormData,
): Promise<EnvResult> {
  try {
    await requireSession();
  } catch {
    return { err: "not signed in" };
  }
  const slug = String(formData.get("slug") || "").trim();
  const baseUrl = String(formData.get("base_url") || "").trim();
  if (!slug) return { err: "slug is required" };
  if (formData.get("also_create_site") === "1") {
    if (!baseUrl) return { err: "base_url is required to also create the site row" };
    try {
      await engine("/sites", {
        method: "POST",
        json: {
          slug,
          name: String(formData.get("name") || "").trim() || slug,
          site_type: String(formData.get("site_type") || "wordpress"),
          base_url: baseUrl,
        },
      });
    } catch (e) {
      return { err: `site row not created: ${errorOf(e)}` };
    }
  }
  const { env, sdkKey } = generateInstanceEnv({
    slug,
    name: String(formData.get("name") || ""),
    siteType: String(formData.get("site_type") || "wordpress"),
    baseUrl,
    wpUser: String(formData.get("wp_user") || ""),
    wpPassword: String(formData.get("wp_password") || ""),
    sdkKey: String(formData.get("sdk_key") || ""),
  });
  revalidatePath("/sites");
  return { env, slug, sdkKey, siteCreated: formData.get("also_create_site") === "1" ? slug : undefined };
}
