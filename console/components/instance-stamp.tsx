"use client";

import { useEffect } from "react";
import { INSTANCE_FIELD } from "@/lib/instance-guard";

/**
 * Stamps every form submitted from this page with the instance it was rendered
 * for, so a stale tab can't act on whichever instance another tab selected since
 * (plan CON-03). One listener instead of editing 30+ forms: a capture-phase
 * `submit` handler runs before React builds the FormData for a server action, so
 * the hidden field is included. The server side is `requireOperator()`.
 */
export function InstanceStamp({ instance }: { instance: string }) {
  useEffect(() => {
    const stamp = (e: Event) => {
      const form = e.target as HTMLFormElement | null;
      if (!form || form.tagName !== "FORM") return;
      let input = form.querySelector<HTMLInputElement>(`input[name="${INSTANCE_FIELD}"]`);
      if (!input) {
        input = document.createElement("input");
        input.type = "hidden";
        input.name = INSTANCE_FIELD;
        form.appendChild(input);
      }
      input.value = instance;
    };
    document.addEventListener("submit", stamp, true);
    return () => document.removeEventListener("submit", stamp, true);
  }, [instance]);
  return null;
}
