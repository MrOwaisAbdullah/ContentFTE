"use client";

// Converts redirect-based server-action feedback (?ok= / ?err= / ?created= /
// ?deleted= / ?saved= / ?removed= / ?started=) into toasts, and strips the
// param from the URL so a refresh doesn't re-toast. UX-07.
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";
import { toast } from "@/lib/toast";

const TONES = {
  ok: "success",
  created: "success",
  deleted: "success",
  saved: "success",
  removed: "success",
  started: "info",
  updated: "success",
  err: "error",
} as const;

export function FlashToaster() {
  const params = useSearchParams();
  const router = useRouter();
  const last = useRef("");

  useEffect(() => {
    let changed = false;
    const url = new URLSearchParams(params.toString());
    for (const [key, tone] of Object.entries(TONES)) {
      const val = params.get(key);
      if (!val) continue;
      if (last.current === `${key}:${val}`) continue;
      last.current = `${key}:${val}`;
      toast(val, tone as "success" | "error" | "info" | "warn");
      url.delete(key);
      changed = true;
    }
    if (changed) {
      const qs = url.toString();
      router.replace(window.location.pathname + (qs ? `?${qs}` : ""), { scroll: false });
    }
  }, [params, router]);

  return null;
}