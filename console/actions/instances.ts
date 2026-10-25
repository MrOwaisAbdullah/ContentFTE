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
  const posting_frequency = String(formData.get("posting_frequency") || "daily").trim();
  const max_posts_per_cadence = Number(formData.get("max_posts_per_cadence") || 1);
  const require_approval = formData.get("require_approval") !== "0";
  const auto_publish = formData.get("auto_publish") === "1" || formData.get("publish_mode") === "auto";
  const publish_mode = String(formData.get("publish_mode") || "draft");

  if (!slug || !base_url) {
    redirect("/sites?err=" + encodeURIComponent("slug and base_url are required"));
  }
  try {
    const res = await engine<{ created?: boolean }>("/sites", {
      method: "POST",
      json: {
        slug,
        name,
        site_type,
        base_url,
        settings: {
          posting_frequency,
          max_posts_per_cadence: isNaN(max_posts_per_cadence) ? 1 : max_posts_per_cadence,
          require_approval,
          auto_publish,
          publish_mode,
        },
      },
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

export interface WpTestResult {
  ok: boolean;
  user_id?: number;
  username?: string;
  roles?: string[];
  base_url?: string;
  message?: string;
  error?: string;
  status_code?: number;
}

export async function testSiteConnectionAction(
  slug: string,
  wpConfig?: { base_url?: string; username?: string; app_password?: string },
): Promise<WpTestResult> {
  await requireSession();
  try {
    const res = await engine<WpTestResult>(`/sites/${encodeURIComponent(slug)}/test-connection`, {
      method: "POST",
      json: wpConfig || {},
    });
    return res;
  } catch (e) {
    return { ok: false, error: errorOf(e) };
  }
}

export async function updateSiteSettingsAction(formData: FormData) {
  await requireSession();
  const slug = String(formData.get("slug") || "").trim();
  if (!slug) {
    redirect("/sites?err=" + encodeURIComponent("slug is required"));
  }

  const name = String(formData.get("name") || "").trim();
  const site_type = String(formData.get("site_type") || "").trim();
  const base_url = String(formData.get("base_url") || "").trim();

  // 1. Cadence & Approval
  const posting_frequency = String(formData.get("posting_frequency") || "daily").trim();
  const max_posts = Number(formData.get("max_posts_per_cadence") || 1);
  const require_approval = formData.get("require_approval") === "1" || formData.get("require_approval") === "true";
  const auto_publish = formData.get("auto_publish") === "1" || formData.get("auto_publish") === "true";
  const publish_mode = String(formData.get("publish_mode") || "draft").trim();

  // 2. WordPress Auth
  const wp_username = String(formData.get("wp_username") || "").trim();
  const wp_app_password = String(formData.get("wp_app_password") || "").trim();
  const wp_base_url = String(formData.get("wp_base_url") || "").trim();

  // 3. AI Image Pipeline
  const image_preference = String(formData.get("image_preference") || "stock_first").trim();
  const stock_threshold = Number(formData.get("stock_relevancy_threshold") || 30);
  const vlm_model = String(formData.get("vlm_model") || "qwen/qwen3-vl-30b-a3b-instruct").trim();
  const max_revisions = Number(formData.get("max_revisions") || 2);

  // 4. Content & Brand Voice
  const min_words = Number(formData.get("min_words") || 1500);
  const brand_voice_prompt = String(formData.get("brand_voice_prompt") || "").trim();
  const generate_faqs = formData.get("generate_faqs") === "1" || formData.get("generate_faqs") === "true";

  // 5. Indexing & SEO
  const auto_index_on_publish = formData.get("auto_index_on_publish") === "1" || formData.get("auto_index_on_publish") === "true";
  const indexnow_key = String(formData.get("indexnow_key") || "").trim();
  const bing_wmt_key = String(formData.get("bing_wmt_key") || "").trim();
  const search_console_property = String(formData.get("search_console_property") || "").trim();

  // 6. Notifications & Webhooks
  const discord_webhook_url = String(formData.get("discord_webhook_url") || "").trim();
  const notify_on_draft = formData.get("notify_on_draft") === "1" || formData.get("notify_on_draft") === "true";
  const notify_on_approval_needed = formData.get("notify_on_approval_needed") === "1" || formData.get("notify_on_approval_needed") === "true";
  const notify_on_publish = formData.get("notify_on_publish") === "1" || formData.get("notify_on_publish") === "true";

  const settingsPayload: Record<string, any> = {
    posting_frequency,
    max_posts_per_cadence: isNaN(max_posts) ? 1 : max_posts,
    require_approval,
    auto_publish,
    publish_mode,
    wp: {
      username: wp_username,
      app_password: wp_app_password,
      base_url: wp_base_url || base_url,
    },
    image: {
      image_preference,
      stock_relevancy_threshold: isNaN(stock_threshold) ? 30 : stock_threshold,
      vlm_model,
      max_revisions: isNaN(max_revisions) ? 2 : max_revisions,
    },
    content: {
      min_words: isNaN(min_words) ? 1500 : min_words,
      brand_voice_prompt,
      generate_faqs,
    },
    indexing: {
      auto_index_on_publish,
      indexnow_key,
      bing_wmt_key,
      search_console_property,
    },
    notifications: {
      discord_webhook_url,
      notify_on_draft,
      notify_on_approval_needed,
      notify_on_publish,
    },
  };

  if (search_console_property) {
    settingsPayload.search_console_site_url = search_console_property;
  }

  try {
    await engine("/sites", {
      method: "POST",
      json: {
        slug,
        name: name || undefined,
        site_type: site_type || undefined,
        base_url: base_url || undefined,
        settings: settingsPayload,
      },
    });
    revalidatePath("/");
    revalidatePath("/sites");
    revalidatePath(`/sites/${encodeURIComponent(slug)}`);
    redirect(`/sites/${encodeURIComponent(slug)}?ok=${encodeURIComponent("Site settings and features successfully updated.")}`);
  } catch (e) {
    redirect(`/sites/${encodeURIComponent(slug)}?err=${encodeURIComponent(errorOf(e))}`);
  }
}

export async function deleteSiteAction(formData: FormData) {
  await requireSession();
  const slug = String(formData.get("slug") || "").trim();
  if (!slug) {
    redirect("/sites?err=" + encodeURIComponent("slug is required to delete"));
  }
  try {
    await engine(`/sites/${encodeURIComponent(slug)}`, { method: "DELETE" });
    revalidatePath("/sites");
    redirect(`/sites?deleted=${encodeURIComponent(slug)}`);
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
