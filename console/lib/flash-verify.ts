// Edge-safe verification of a flash signature (Web Crypto only: runs in middleware and under node:test).
// Must stay in lock-step with lib/flash-redirect.ts, which signs.
import { FLASH_MAX_AGE_S, flashMessageToSign } from "./flash.ts";

function toHex(buf: ArrayBuffer): string {
  return Array.from(new Uint8Array(buf), (b) => b.toString(16).padStart(2, "0")).join("");
}

function equalConstTime(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export async function flashSignature(secret: string, ts: number | string, canonical: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(flashMessageToSign(ts, canonical)));
  return toHex(sig);
}

export async function validFlash(
  canonical: string,
  ts: string | null | undefined,
  sig: string | null | undefined,
  secret: string | undefined,
  nowMs: number = Date.now(),
): Promise<boolean> {
  if (!canonical || !ts || !sig || !secret) return false;
  const t = Number(ts);
  if (!Number.isFinite(t)) return false;
  if (Math.abs(nowMs / 1000 - t) > FLASH_MAX_AGE_S) return false;
  return equalConstTime(await flashSignature(secret, ts, canonical), sig);
}
