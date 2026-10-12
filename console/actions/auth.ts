"use server";

import { redirect } from "next/navigation";
import { clearSessionCookie, passwordMatches, setSessionCookie } from "@/lib/session";

export async function loginAction(_prev: { error?: string } | null, formData: FormData) {
  const password = String(formData.get("password") || "");
  if (!passwordMatches(password)) {
    return { error: "Wrong password." };
  }
  await setSessionCookie();
  redirect("/");
}

export async function logoutAction() {
  await clearSessionCookie();
  redirect("/login");
}
