"use server";

import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { clearSessionCookie, passwordMatches, setSessionCookie } from "@/lib/session";
import { createLimiter } from "@/lib/login-limit";
import { safeNextPath } from "@/lib/safe-next";

// Per-client and global caps on failed sign-ins (plan SEC-10). X-Forwarded-For
// is only trustworthy behind your own proxy, so the global cap also bounds an
// attacker who rotates it.
const perClient = createLimiter({ max: 5, windowMs: 15 * 60_000 });
const fleetwide = createLimiter({ max: 40, windowMs: 15 * 60_000 });

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function clientKey(): Promise<string> {
  const h = await headers();
  return (
    (h.get("x-forwarded-for") || "").split(",")[0].trim() ||
    h.get("x-real-ip") ||
    "unknown"
  );
}

export async function loginAction(_prev: { error?: string } | null, formData: FormData) {
  const key = await clientKey();
  const mine = perClient.status(key);
  const all = fleetwide.status("all");
  if (mine.blocked || all.blocked) {
    const mins = Math.max(1, Math.ceil(Math.max(mine.retryAfterMs, all.retryAfterMs) / 60_000));
    return { error: `Too many failed attempts. Try again in about ${mins} minute${mins === 1 ? "" : "s"}.` };
  }

  const password = String(formData.get("password") || "");
  if (!passwordMatches(password)) {
    perClient.fail(key);
    fleetwide.fail("all");
    await sleep(600); // flat delay on every failure
    // Deliberately generic: don't name config files or env vars to a stranger.
    return { error: "Incorrect password." };
  }

  perClient.reset(key);
  await setSessionCookie();
  redirect(safeNextPath(String(formData.get("next") || "/")));
}

export async function logoutAction() {
  await clearSessionCookie();
  redirect("/login");
}
