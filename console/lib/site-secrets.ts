// Pure helpers (no React, no `server-only`) for keeping per-site secrets out of
// the browser and for saving settings without clobbering stored values.
//
// Why this exists (docs/improvement-plan-2026-11.md SEC-04 / CON-02 / CON-04):
//  * the engine's GET /sites returns the raw `Site.settings` JSON, which holds
//    the WordPress application password, IndexNow/Bing keys and the Discord
//    webhook in plaintext;
//  * the engine merges `settings` only at the top level, so a group sent from
//    the console REPLACES the stored group — saving with a blank secret field
//    used to wipe the stored secret.

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Json = Record<string, any>;

export interface SecretField {
  /** settings group, e.g. "wp" */
  group: string;
  /** key inside the group, e.g. "app_password" */
  key: string;
  /** flag name exposed to the UI, e.g. "wp_app_password" */
  flag: string;
}

/** The secrets the console knows how to edit. */
export const SECRET_FIELDS: readonly SecretField[] = [
  { group: "wp", key: "app_password", flag: "wp_app_password" },
  { group: "indexing", key: "indexnow_key", flag: "indexnow_key" },
  { group: "indexing", key: "bing_wmt_key", flag: "bing_wmt_key" },
  { group: "notifications", key: "discord_webhook_url", flag: "discord_webhook_url" },
];

export type SecretFlags = Record<string, boolean>;

// Safety net for secret-looking keys we don't know about yet. Only applied to
// non-empty *string* values, so numeric config such as `max_tokens` survives.
const SECRET_KEY_RE =
  /(password|passwd|passphrase|secret|token|api[_-]?key|private[_-]?key|credential|webhook)|_key$/i;

function isPlainObject(v: unknown): v is Json {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function nonEmpty(v: unknown): boolean {
  return typeof v === "string" && v.trim() !== "";
}

function scrub(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(scrub);
  if (isPlainObject(value)) {
    const out: Json = {};
    for (const [k, v] of Object.entries(value)) {
      if (typeof v === "string" && v !== "" && SECRET_KEY_RE.test(k)) continue; // drop
      out[k] = scrub(v);
    }
    return out;
  }
  return value;
}

/**
 * Remove every secret from a site's settings and report which known secrets
 * are set. The returned `settings` is safe to serialise to the browser.
 */
export function redactSettings(settings: Json | null | undefined): {
  settings: Json;
  secretsSet: SecretFlags;
} {
  const src = isPlainObject(settings) ? settings : {};
  const secretsSet: SecretFlags = {};
  for (const f of SECRET_FIELDS) {
    const group = src[f.group];
    secretsSet[f.flag] = isPlainObject(group) && nonEmpty(group[f.key]);
  }
  return { settings: scrub(src) as Json, secretsSet };
}

/** Redact every site in an engine `{sites:[...]}` response; passes other shapes through. */
export function redactSiteList<T>(data: T): T {
  if (!isPlainObject(data) || !Array.isArray((data as Json).sites)) return data;
  const sites = ((data as Json).sites as Json[]).map((s) => {
    if (!isPlainObject(s)) return s;
    const { settings, secretsSet } = redactSettings(s.settings as Json | undefined);
    // Once the engine redacts (lib/secrets_redact.py), the values are already gone and
    // our own scan finds nothing — so the engine's flags must win, never be overwritten.
    const fromEngine = isPlainObject(s.secrets_set) ? (s.secrets_set as Json) : {};
    const merged: SecretFlags = { ...secretsSet };
    for (const [k, v] of Object.entries(fromEngine)) merged[k] = Boolean(v) || Boolean(secretsSet[k]);
    return { ...s, settings, secrets_set: merged };
  });
  return { ...(data as Json), sites } as T;
}

/**
 * Merge submitted fields into the stored group.
 *  - `undefined` incoming value  → field wasn't in the form: keep stored value
 *  - blank secret                → "leave empty to keep": keep stored value
 *  - key listed in `clear`       → explicitly removed (sent as `null`: the engine
 *                                  deep-merges groups, so merely omitting the key would keep it)
 */
export function mergeGroup(
  current: Json | null | undefined,
  incoming: Json,
  opts: { secrets?: readonly string[]; clear?: readonly string[] } = {},
): Json {
  const secrets = new Set(opts.secrets ?? []);
  const out: Json = { ...(isPlainObject(current) ? current : {}) };
  for (const [k, v] of Object.entries(incoming)) {
    if (v === undefined) continue;
    if (secrets.has(k) && (v === "" || v === null)) continue;
    out[k] = v;
  }
  for (const k of opts.clear ?? []) out[k] = null;
  return out;
}

// ---- form parsing helpers (FormData → typed values) ------------------------

type FormLike = { has(name: string): boolean; get(name: string): FormDataEntryValue | null };

/** Trimmed string, or undefined when the field wasn't submitted at all. */
export function formText(fd: FormLike, name: string): string | undefined {
  if (!fd.has(name)) return undefined;
  return String(fd.get(name) ?? "").trim();
}

/** Clamped integer, or undefined when absent / not a number. */
export function formInt(
  fd: FormLike,
  name: string,
  min: number,
  max: number,
): number | undefined {
  const raw = formText(fd, name);
  if (raw === undefined || raw === "") return undefined;
  const n = Number(raw);
  if (!Number.isFinite(n)) return undefined;
  return Math.min(max, Math.max(min, Math.trunc(n)));
}

/** One of `allowed`, else undefined (never an arbitrary string). */
export function formEnum<T extends string>(
  fd: FormLike,
  name: string,
  allowed: readonly T[],
): T | undefined {
  const raw = formText(fd, name);
  return raw !== undefined && (allowed as readonly string[]).includes(raw) ? (raw as T) : undefined;
}

/**
 * Checkbox: only meaningful when its group was submitted (unchecked boxes are
 * absent from FormData, so absence alone can't mean "false").
 */
export function formBool(fd: FormLike, name: string, groupSubmitted: boolean): boolean | undefined {
  if (!groupSubmitted) return undefined;
  const v = formText(fd, name);
  return v === "1" || v === "true" || v === "on";
}
