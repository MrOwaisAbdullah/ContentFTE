// Flash messages carried in the URL (?ok= / ?err= / ...) are AUTHENTICATED, not trusted (CON-16).
//
// The toaster used to render whatever the query string said, so anyone could send an operator a link like
//   /?ok=Article%20published%20successfully
// and the console would show it in its own voice. Messages still travel in the URL (that is what makes them
// work across a server-action redirect with no extra state), but now:
//
//   * the server action's `redirect()` (lib/flash-redirect.ts) appends  fts=<unix>  and  fsig=<HMAC>  over the
//     exact flash parameters, keyed with SESSION_SECRET;
//   * middleware.ts rejects (strips) any flash parameter whose signature is missing, wrong or older than 2
//     minutes, so a crafted or replayed link shows nothing;
//   * only then does the toaster display it, as plain text, length-capped.

export type FlashTone = "success" | "error" | "info" | "warn";

export const FLASH_PARAMS = ["ok", "err", "created", "deleted", "saved", "removed", "started", "updated"] as const;
export const FLASH_TS = "fts";
export const FLASH_SIG = "fsig";
export const FLASH_MAX_AGE_S = 120;
export const FLASH_TEXT_MAX = 300;

/** Default wording for the bare-key forms (?saved=1). */
export const FLASH_MESSAGES: Readonly<Record<string, { text: string; tone: FlashTone }>> = {
  saved: { text: "Saved.", tone: "success" },
  created: { text: "Created.", tone: "success" },
  deleted: { text: "Deleted.", tone: "success" },
  removed: { text: "Removed.", tone: "success" },
  updated: { text: "Updated.", tone: "success" },
  started: { text: "Started.", tone: "info" },
};

/** The text and tone to show for one flash parameter. `ok`/`err` carry their own (server-authored) text. */
export function flashFor(key: string, value: string | null | undefined): { text: string; tone: FlashTone } | null {
  const v = (value ?? "").trim();
  if (!v) return null;
  if (key === "err") return { text: v.slice(0, FLASH_TEXT_MAX), tone: "error" };
  if (key === "ok") return { text: v.slice(0, FLASH_TEXT_MAX), tone: "success" };
  return Object.prototype.hasOwnProperty.call(FLASH_MESSAGES, key) ? FLASH_MESSAGES[key] : null;
}

/** The exact string that is signed: the present flash parameters, sorted, as key=value lines. */
export function canonicalFlash(params: URLSearchParams): string {
  return FLASH_PARAMS.filter((k) => params.has(k))
    .sort()
    .map((k) => `${k}=${params.get(k) ?? ""}`)
    .join("\n");
}

export function hasFlash(params: URLSearchParams): boolean {
  return FLASH_PARAMS.some((k) => params.has(k));
}

/** The URL's query with every flash parameter (and its signature) removed. */
export function withoutFlash(params: URLSearchParams): URLSearchParams {
  const out = new URLSearchParams(params.toString());
  for (const k of FLASH_PARAMS) out.delete(k);
  out.delete(FLASH_TS);
  out.delete(FLASH_SIG);
  return out;
}

export function flashMessageToSign(ts: number | string, canonical: string): string {
  return `flash.v1.${ts}.${canonical}`;
}
