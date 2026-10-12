"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { engine, EngineError } from "@/lib/engine";
import { requireSession } from "@/lib/session";
import { removeInstance, saveInstance, setCurrentInstance } from "@/lib/instances";
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

export async function saveInstanceAction(formData: FormData) {
  await requireSession();
  const name = String(formData.get("name") || "").trim();
  try {
    await saveInstance({
      name,
      baseUrl: String(formData.get("base_url") || ""),
      apiKey: String(formData.get("api_key") || ""),
    });
  } catch (e) {
    redirect("/instances?err=" + encodeURIComponent(e instanceof Error ? e.message : String(e)));
  }
  revalidatePath("/", "layout");
  redirect(`/instances?saved=${encodeURIComponent(name)}`);
}

export async function removeInstanceAction(formData: FormData) {
  await requireSession();
  const name = String(formData.get("name") || "");
  try {
    await removeInstance(name);
  } catch (e) {
    redirect("/instances?err=" + encodeURIComponent(e instanceof Error ? e.message : String(e)));
  }
  revalidatePath("/", "layout");
  redirect(`/instances?removed=${encodeURIComponent(name)}`);
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
    const res = await engine<{ created?: boolean }>("/sites", {
      method: "POST",
      json: { slug, name, site_type, base_url },
    });
    revalidatePath("/sites");
    redirect(
      res?.created === false
        ? `/sites?updated=${encodeURIComponent(slug)}`
        : `/sites?created=${encodeURIComponent(slug)}`,
    );
  } catch (e) {
    redirect("/sites?err=" + encodeURIComponent(errorOf(e)));
  }
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
