import "server-only";
import { createHmac } from "node:crypto";
import { redirect as nextRedirect } from "next/navigation";
import { sessionSecret } from "./env";
import { FLASH_SIG, FLASH_TS, canonicalFlash, flashMessageToSign, hasFlash } from "./flash.ts";

/**
 * Drop-in replacement for `redirect` in server actions: if the target URL carries flash parameters
 * (?ok= / ?err= / ...), sign them so middleware lets them through to the toaster. Everything else is
 * identical to next/navigation's redirect (it throws NEXT_REDIRECT and never returns).
 */
export function redirect(url: string): never {
  const q = url.indexOf("?");
  if (q === -1) return nextRedirect(url);
  const hashAt = url.indexOf("#");
  const base = url.slice(0, q);
  const queryEnd = hashAt === -1 ? url.length : hashAt;
  const params = new URLSearchParams(url.slice(q + 1, queryEnd));
  const hash = hashAt === -1 ? "" : url.slice(hashAt);
  if (!hasFlash(params)) return nextRedirect(url);
  const ts = Math.floor(Date.now() / 1000);
  const sig = createHmac("sha256", sessionSecret()).update(flashMessageToSign(ts, canonicalFlash(params))).digest("hex");
  params.set(FLASH_TS, String(ts));
  params.set(FLASH_SIG, sig);
  return nextRedirect(`${base}?${params.toString()}${hash}`);
}
