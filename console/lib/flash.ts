// Flash messages carried in the URL (?ok= / ?err= / ...) are SHORT CODES, never display text.
//
// The toaster used to render whatever the query string said, so anyone could send an operator a link
// like  /?ok=Article%20published%20successfully  (or an error pointing at a phishing instruction) and the
// console would show it in its own voice (plan CON-16). A code is looked up here; an unknown code, or free
// text, shows nothing.

export type FlashTone = "success" | "error" | "info" | "warn";

export const FLASH_MESSAGES: Readonly<Record<string, { text: string; tone: FlashTone }>> = {
  instance_changed: {
    text: "The console is now on a different instance (you switched in another tab). Nothing was changed - reload and try again.",
    tone: "error",
  },
  saved: { text: "Saved.", tone: "success" },
  created: { text: "Created.", tone: "success" },
  deleted: { text: "Deleted.", tone: "success" },
  removed: { text: "Removed.", tone: "success" },
  updated: { text: "Updated.", tone: "success" },
  started: { text: "Started.", tone: "info" },
};

const CODE = /^[a-z][a-z0-9_]{0,39}$/;

/** The message for a flash code from the URL, or null if it is not a known code. */
export function resolveFlash(value: string | null | undefined): { text: string; tone: FlashTone } | null {
  const v = (value ?? "").trim();
  if (!CODE.test(v)) return null;
  return Object.prototype.hasOwnProperty.call(FLASH_MESSAGES, v) ? FLASH_MESSAGES[v] : null;
}

export const FLASH_PARAMS = ["ok", "err", "created", "deleted", "saved", "removed", "started", "updated"] as const;
