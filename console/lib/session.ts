import "server-only";
import { createHash, createHmac, timingSafeEqual } from "node:crypto";
import { cookies } from "next/headers";
import { operatorPassword, sessionSecret } from "./env";

const COOKIE = "console_session";
const MAX_AGE_S = 60 * 60 * 24 * 7; // 7 days

function sign(expiresAt: number): string {
  return createHmac("sha256", sessionSecret())
    .update(`v1.${expiresAt}.console-session`)
    .digest("hex");
}

export function createSessionToken(now = Date.now()): string {
  const expiresAt = Math.floor(now / 1000) + MAX_AGE_S;
  return `v1.${expiresAt}.${sign(expiresAt)}`;
}

export function verifySessionToken(token: string | undefined): boolean {
  if (!token) return false;
  const parts = (token || "").split(".");
  if (parts.length !== 3 || parts[0] !== "v1") return false;
  const expiresAt = Number(parts[1]);
  if (!Number.isFinite(expiresAt) || expiresAt * 1000 <= Date.now()) return false;
  const expected = Buffer.from(sign(expiresAt));
  const got = Buffer.from(parts[2]);
  return expected.length === got.length && timingSafeEqual(expected, got);
}

export function passwordMatches(input: string): boolean {
  const a = createHash("sha256").update(input).digest();
  const b = createHash("sha256").update(operatorPassword()).digest();
  return timingSafeEqual(a, b);
}

export async function verifySession(): Promise<boolean> {
  const store = await cookies();
  return verifySessionToken(store.get(COOKIE)?.value);
}

export async function requireSession(): Promise<void> {
  const { redirect } = await import("next/navigation");
  if (!(await verifySession())) redirect("/login");
}

export async function setSessionCookie(): Promise<void> {
  const store = await cookies();
  store.set(COOKIE, createSessionToken(), {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: MAX_AGE_S,
  });
}

export async function clearSessionCookie(): Promise<void> {
  const store = await cookies();
  store.delete(COOKIE);
}
