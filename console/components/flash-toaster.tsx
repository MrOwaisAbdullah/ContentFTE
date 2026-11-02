"use client";

// Converts redirect-based server-action feedback (?ok= / ?err= / ?created= /
// ?deleted= / ?saved= / ?removed= / ?started=) into toasts, and strips the
// param from the URL so a refresh doesn't re-toast. UX-07.
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";
import { toast } from "@/lib/toast";
import { FLASH_PARAMS, FLASH_SIG, FLASH_TS, flashFor } from "@/lib/flash.ts";

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
      // middleware.ts only lets a flash through when a server action signed it (CON-16), so this text came
      // from the console's own server; it is still rendered as plain text and length-capped (flashFor).
      const flash = flashFor(key, val);
      url.delete(key);
      changed = true;
      if (!flash || last.current === `${key}:${val}`) continue;
      last.current = `${key}:${val}`;
      toast(flash.text, flash.tone);
    }
    if (changed) {
      url.delete(FLASH_TS);
      url.delete(FLASH_SIG);
      const qs = url.toString();
      router.replace(window.location.pathname + (qs ? `?${qs}` : ""), { scroll: false });
    }
  }, [params, router]);

  return null;
}