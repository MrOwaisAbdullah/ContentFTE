"use client";

// Converts redirect-based server-action feedback (?ok= / ?err= / ?created= /
// ?deleted= / ?saved= / ?removed= / ?started=) into toasts, and strips the
// param from the URL so a refresh doesn't re-toast. UX-07.
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";
import { toast } from "@/lib/toast";
import { FLASH_PARAMS, resolveFlash } from "@/lib/flash";

export function FlashToaster() {
  const params = useSearchParams();
  const router = useRouter();
  const last = useRef("");

  useEffect(() => {
    let changed = false;
    const url = new URLSearchParams(params.toString());
    for (const key of FLASH_PARAMS) {
      const val = params.get(key);
      if (!val) continue;
      // The param is a short CODE looked up in lib/flash.ts. Free text in a URL is never shown (CON-16).
      // A bare ?created=1 / ?saved=true style value falls back to the key's own code.
      const code = resolveFlash(val) ? val : key;
      const flash = resolveFlash(code);
      url.delete(key);
      changed = true;
      if (!flash || last.current === `${key}:${val}`) continue;
      last.current = `${key}:${val}`;
      toast(flash.text, flash.tone);
    }
    if (changed) {
      const qs = url.toString();
      router.replace(window.location.pathname + (qs ? `?${qs}` : ""), { scroll: false });
    }
  }, [params, router]);

  return null;
}