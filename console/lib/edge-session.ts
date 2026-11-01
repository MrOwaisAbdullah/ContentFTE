// Session-token verification for the edge runtime (middleware). Pure Web Crypto —
// no Node `crypto`, no next/* imports — so it runs at the edge and under node:test.
//
// Must stay in lock-step with lib/session.ts, which issues the token:
//   v1.<expiresAtSeconds>.<hex HMAC-SHA256 of "v1.<expiresAtSeconds>.console-session">

function toHex(buf: ArrayBuffer): string {
  return Array.from(new Uint8Array(buf), (b) => b.toString(16).padStart(2, "0")).join("");
}

function equalConstTime(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export async function validSessionToken(
  token: string | undefined,
  secret: string | undefined,
  nowMs: number = Date.now(),
): Promise<boolean> {
  if (!token || !secret) return false;
  const parts = token.split(".");
  if (parts.length !== 3 || parts[0] !== "v1") return false;
  const exp = Number(parts[1]);
  if (!Number.isFinite(exp) || exp * 1000 <= nowMs) return false;
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(`v1.${exp}.console-session`));
  return equalConstTime(toHex(sig), parts[2]);
}
