// Input handling for server actions, kept pure so it can be unit-tested (CON-10 / CON-15).
//
// A server action is a public POST endpoint: every field arrives as an untrusted string. These helpers turn a raw
// form value into a safe one, or into `null` so the action can bounce back with an error instead of calling the engine
// with `NaN`, an unknown enum value, or an attacker-chosen redirect.

/** A positive integer id, or null (never NaN, 0, a float, an exponent, or a hex string). */
export function parseId(raw: unknown): number | null {
  const s = String(raw ?? "").trim();
  if (!/^[1-9][0-9]{0,9}$/.test(s)) return null;
  const n = Number(s);
  return Number.isSafeInteger(n) && n <= 2_147_483_647 ? n : null;
}

export const PUBLISH_MODES = ["draft", "publish", "auto"] as const;
export type PublishMode = (typeof PUBLISH_MODES)[number];

/** An allow-listed publish mode; anything else is "draft" (the safe default - it never goes live). */
export function parsePublishMode(raw: unknown): PublishMode {
  const s = String(raw ?? "").trim();
  return (PUBLISH_MODES as readonly string[]).includes(s) ? (s as PublishMode) : "draft";
}

/** Where a queue action may send the operator afterwards: only these fixed paths, never a caller-supplied URL. */
export const RETURN_PATHS = ["/", "/approvals", "/publish"] as const;

export function parseReturnPath(raw: unknown): (typeof RETURN_PATHS)[number] | null {
  const s = String(raw ?? "");
  return (RETURN_PATHS as readonly string[]).includes(s) ? (s as (typeof RETURN_PATHS)[number]) : null;
}

/** A site slug as the engine accepts it (lower-case letters, digits, hyphens; 1-63 chars), or null. */
export function parseSlug(raw: unknown): string | null {
  const s = String(raw ?? "").trim();
  return /^[a-z0-9][a-z0-9-]{0,62}$/.test(s) ? s : null;
}

/** Trimmed text capped at `max` characters (empty string if absent). */
export function cleanText(raw: unknown, max: number): string {
  return String(raw ?? "").trim().slice(0, Math.max(0, max));
}
