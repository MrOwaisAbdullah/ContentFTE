"use server";

import { redirect } from "next/navigation";
import { clearSessionCookie, passwordMatches, setSessionCookie } from "@/lib/session";

export async function loginAction(_prev: { error?: string } | null, formData: FormData) {
  const password = String(formData.get("password") || "");
  if (!passwordMatches(password)) {
    return { error: "Wrong password. Check OPERATOR_PASSWORD in console/.env.local." };
  }
  await setSessionCookie();
  const next = String(formData.get("next") || "/");
  // Only allow same-origin relative paths.
  const safe = next.startsWith("/") && !next.startsWith("//") ? next : "/";
  redirect(safe);
}

export async function logoutAction() {
  await clearSessionCookie();
  redirect("/login");
}
