"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { engine, engineUnredacted, EngineError, type SiteList } from "@/lib/engine";
import { requireOperator } from "@/lib/guard";
import { requireSession, verifySession } from "@/lib/session";
import { removeInstance, saveInstance, setCurrentInstance } from "@/lib/instances";
import { generateInstanceEnv } from "@/lib/provision";
import {
  SECRET_FIELDS,
  formBool,
  formEnum,
  formInt,
  formText,
  mergeGroup,
  type Json,
} from "@/lib/site-secrets";

function errorOf(e: unknown): string {
  return e instanceof EngineError ? e.message : `unexpected error: ${String(e)}`;
}

/**
 * NOTE on redirects: `redirect()` works by throwing NEXT_REDIRECT. Calling it
 * inside a `try` whose `catch` redirects again swallows the success redirect
 * and shows a bogus error (plan CON-01). Every action below computes the
 * destination inside `try`/`catch`, then redirects exactly once afterwards.
 */

const SLUG_RE = /^[a-z0-9][a-z0-9-]{0,62}$/;
const CADENCES = ["daily", "every_2_days", "twice_a_week", "weekly", "biweekly", "monthly", "manual"] as const;
const PUBLISH_MODES = ["draft", "publish", "auto"] as const;
const IMAGE_PREFS = ["stock_first", "ai_first", "stock_only"] as const;

function isHttpUrl(v: string): boolean {
  try {
    const u = new URL(v);
    return u.protocol === "http:" || u.protocol === "https:";
  } catch {
    return false;
  }
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
  let target = `/instances?saved=${encodeURIComponent(name)}`;
  try {
    await saveInstance({
      name,
      baseUrl: String(formData.get("base_url") || ""),
      apiKey: String(formData.get("api_key") || ""),
    });
    revalidatePath("/", "layout");
  } catch (e) {
    target = "/instances?err=" + encodeURIComponent(e instanceof Error ? e.message : String(e));
  }
  redirect(target);
}

export async function removeInstanceAction(formData: FormData) {
  await requireSession();
  const name = String(formData.get("name") || "");
  let target = `/instances?removed=${encodeURIComponent(name)}`;
  try {
    await removeInstance(name);
    revalidatePath("/", "layout");
  } catch (e) {
    target = "/instances?err=" + encodeURIComponent(e instanceof Error ? e.message : String(e));
  }
  redirect(target);
}

export async function createSiteAction(formData: FormData) {
  await requireOperator(formData);
  const slug = String(formData.get("slug") || "").trim();
  const name = String(formData.get("name") || "").trim() || slug;
  const site_type = String(formData.get("site_type") || "wordpress");
  const base_url = String(formData.get("base_url") || "").trim();
  const posting_frequency = formEnum(formData, "posting_frequency", CADENCES) ?? "daily";
  const max_posts_per_cadence = formInt(formData, "max_posts_per_cadence", 1, 50) ?? 1;
  const require_approval = formData.get("require_approval") !== "0";
  const auto_publish = formData.get("auto_publish") === "1" || formData.get("publish_mode") === "auto";
  const publish_mode = formEnum(formData, "publish_mode", PUBLISH_MODES) ?? "draft";

  if (!slug || !base_url) {
    redirect("/sites?err=" + encodeURIComponent("slug and base_url are required"));
  }
  if (!SLUG_RE.test(slug)) {
    redirect("/sites?err=" + encodeURIComponent("slug must be lowercase letters, digits and dashes (max 63)"));
  }
  if (!isHttpUrl(base_url)) {
    redirect("/sites?err=" + encodeURIComponent("base_url must be an http(s) URL"));
  }

  let target: string;
  try {
    const res = await engine<{ created?: boolean }>("/sites", {
      method: "POST",
      json: {
        slug,
        name,
        site_type,
        base_url,
        settings: { posting_frequency, max_posts_per_cadence, require_approval, auto_publish, publish_mode },
      },
    });
    revalidatePath("/sites");
    target =
      res?.created === false
        ? `/sites?updated=${encodeURIComponent(slug)}`
        : `/sites?created=${encodeURIComponent(slug)}`;
  } catch (e) {
    target = "/sites?err=" + encodeURIComponent(errorOf(e));
  }
  redirect(target);
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
  /** "typed" = tested the values in the form; "saved" = tested the stored credentials. */
  tested?: "typed" | "saved";
}

export async function testSiteConnectionAction(
  slug: string,
  wpConfig?: { base_url?: string; username?: string; app_password?: string },
): Promise<WpTestResult> {
  if (!(await verifySession())) return { ok: false, error: "not signed in" };
  // The stored password never reaches the browser, so a blank password field
  // means "test what is saved" — send no overrides and let the engine resolve
  // the site's own credentials.
  const typed = Boolean(wpConfig?.app_password && wpConfig.app_password.trim());
  try {
    const res = await engine<WpTestResult>(`/sites/${encodeURIComponent(slug)}/test-connection`, {
      method: "POST",
      json: typed ? wpConfig : {},
      timeoutMs: 20_000,
    });
    return { ...res, tested: typed ? "typed" : "saved" };
  } catch (e) {
    return { ok: false, error: errorOf(e), tested: typed ? "typed" : "saved" };
  }
}

export async function updateSiteSettingsAction(formData: FormData) {
  await requireOperator(formData);
  const slug = String(formData.get("slug") || "").trim();
  const back = (kind: "ok" | "err", msg: string) =>
    `/sites/${encodeURIComponent(slug)}?${kind}=${encodeURIComponent(msg)}`;
  if (!slug) {
    redirect("/sites?err=" + encodeURIComponent("slug is required"));
  }

  // Only the groups the form actually submitted are touched (the form lists
  // them in `_groups`). Anything else keeps its stored value — previously a
  // save from one tab overwrote every other tab with defaults/blanks.
  const groups = new Set(String(formData.get("_groups") || "").split(/\s+/).filter(Boolean));
  const clearFlags = new Set(formData.getAll("clear_secret").map(String));

  const name = formText(formData, "name");
  const site_type = formText(formData, "site_type");
  const base_url = formText(formData, "base_url");
  if (base_url && !isHttpUrl(base_url)) redirect(back("err", "base_url must be an http(s) URL"));
  const wpBase = formText(formData, "wp_base_url");
  if (wpBase && !isHttpUrl(wpBase)) redirect(back("err", "WordPress base URL must be an http(s) URL"));
  const webhook = formText(formData, "discord_webhook_url");
  if (webhook && !isHttpUrl(webhook)) redirect(back("err", "Discord webhook must be an https URL"));

  let target: string;
  try {
    // Unredacted read, used only to merge — never returned to the client.
    const list = await engineUnredacted<SiteList>("/sites");
    const current = (list.sites ?? []).find((s) => s.slug === slug);
    if (!current) {
      redirect(back("err", `site '${slug}' not found on this instance`));
    }
    const cur = (current.settings ?? {}) as Json;
    const clearOf = (group: string) =>
      SECRET_FIELDS.filter((f) => f.group === group && clearFlags.has(f.flag)).map((f) => f.key);
    const secretsOf = (group: string) => SECRET_FIELDS.filter((f) => f.group === group).map((f) => f.key);

    const settings: Json = {};

    if (groups.has("cadence")) {
      const set = (k: string, v: unknown) => {
        if (v !== undefined) settings[k] = v;
      };
      set("posting_frequency", formEnum(formData, "posting_frequency", CADENCES));
      set("max_posts_per_cadence", formInt(formData, "max_posts_per_cadence", 1, 50));
      set("require_approval", formBool(formData, "require_approval", true));
      set("auto_publish", formBool(formData, "auto_publish", true));
      set("enforce_cadence", formBool(formData, "enforce_cadence", true));
      set("publish_mode", formEnum(formData, "publish_mode", PUBLISH_MODES));
    }

    if (groups.has("wp")) {
      const wpIn = {
        base_url: wpBase || undefined,
        username: formText(formData, "wp_username"),
        app_password: formText(formData, "wp_app_password"),
      };
      // The engine uses settings.wp INSTEAD of the process WP_* env as soon as
      // it has a base_url, so never create the group from a pre-filled base URL
      // alone — that would silently disable env credentials on isolated
      // instances. Write it only once real credentials exist or are submitted.
      const curWp = (cur.wp ?? {}) as Json;
      const hasCreds = Boolean(
        wpIn.username ||
          wpIn.app_password ||
          curWp.username ||
          curWp.app_password ||
          current.secrets_set?.wp_app_password, // the engine redacts: the flag is all we can see
      );
      if (hasCreds) {
        settings.wp = mergeGroup(cur.wp, wpIn, {
          // blank username/password = "keep what is stored"
          secrets: [...secretsOf("wp"), "username"],
          clear: clearOf("wp"),
        });
      }
    }

    if (groups.has("image")) {
      settings.image = mergeGroup(cur.image, {
        image_preference: formEnum(formData, "image_preference", IMAGE_PREFS),
        stock_relevancy_threshold: formInt(formData, "stock_relevancy_threshold", 0, 100),
        vlm_model: formText(formData, "vlm_model")?.slice(0, 200) || undefined,
        max_revisions: formInt(formData, "max_revisions", 0, 10),
      });
    }

    if (groups.has("content")) {
      settings.content = mergeGroup(cur.content, {
        min_words: formInt(formData, "min_words", 300, 10_000),
        brand_voice_prompt: formText(formData, "brand_voice_prompt")?.slice(0, 4000),
        generate_faqs: formBool(formData, "generate_faqs", true),
      });
    }

    if (groups.has("indexing")) {
      settings.indexing = mergeGroup(
        cur.indexing,
        {
          auto_index_on_publish: formBool(formData, "auto_index_on_publish", true),
          indexnow_key: formText(formData, "indexnow_key"),
          bing_wmt_key: formText(formData, "bing_wmt_key"),
          search_console_property: formText(formData, "search_console_property"),
        },
        { secrets: secretsOf("indexing"), clear: clearOf("indexing") },
      );
      const gsc = formText(formData, "search_console_property");
      if (gsc) settings.search_console_site_url = gsc;
    }

    if (groups.has("notifications")) {
      settings.notifications = mergeGroup(
        cur.notifications,
        {
          discord_webhook_url: webhook,
          notify_on_draft: formBool(formData, "notify_on_draft", true),
          notify_on_approval_needed: formBool(formData, "notify_on_approval_needed", true),
          notify_on_publish: formBool(formData, "notify_on_publish", true),
        },
        { secrets: secretsOf("notifications"), clear: clearOf("notifications") },
      );
    }

    await engine("/sites", {
      method: "POST",
      json: {
        slug,
        name: name || undefined,
        site_type: site_type || undefined,
        base_url: base_url || undefined,
        settings,
      },
    });
    revalidatePath("/");
    revalidatePath("/sites");
    revalidatePath(`/sites/${encodeURIComponent(slug)}`);
    target = back("ok", "Site settings saved.");
  } catch (e) {
    // redirect() above throws NEXT_REDIRECT — let it through untouched.
    if (isRedirect(e)) throw e;
    target = back("err", errorOf(e));
  }
  redirect(target);
}

export async function deleteSiteAction(formData: FormData) {
  await requireOperator(formData);
  const slug = String(formData.get("slug") || "").trim();
  if (!slug) {
    redirect("/sites?err=" + encodeURIComponent("slug is required to delete"));
  }
  let target = `/sites?deleted=${encodeURIComponent(slug)}`;
  try {
    await engine(`/sites/${encodeURIComponent(slug)}`, { method: "DELETE" });
    revalidatePath("/sites");
  } catch (e) {
    target = "/sites?err=" + encodeURIComponent(errorOf(e));
  }
  redirect(target);
}

function isRedirect(e: unknown): boolean {
  const digest = (e as { digest?: unknown } | null)?.digest;
  return typeof digest === "string" && digest.startsWith("NEXT_REDIRECT");
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
  if (!(await verifySession())) return { err: "not signed in" };
  const slug = String(formData.get("slug") || "").trim();
  const baseUrl = String(formData.get("base_url") || "").trim();
  if (!slug) return { err: "slug is required" };
  if (!SLUG_RE.test(slug)) return { err: "slug must be lowercase letters, digits and dashes (max 63)" };
  if (formData.get("also_create_site") === "1") {
    if (!baseUrl) return { err: "base_url is required to also create the site row" };
    if (!isHttpUrl(baseUrl)) return { err: "base_url must be an http(s) URL" };
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
