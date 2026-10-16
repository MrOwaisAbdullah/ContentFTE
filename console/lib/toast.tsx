"use client";

// Toast groundwork (docs/console-dashboard-plan.md §3, Wave 0): a dependency-
// free toast region with an aria-live polite announcer. Client code fires
// `toast("…", "error")`; Wave 1 wires server-action results into it and the
// old `?err=`/`?created=` banners retire. Mounted once in the console layout.

import { CircleCheck, CircleX, Info, TriangleAlert, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

export type ToastTone = "success" | "error" | "info" | "warn";

type ToastItem = { id: number; message: string; tone: ToastTone };

const EVENT = "console:toast";
const DISMISS_MS = 6000;

/** Fire a toast from any client component (no-op during SSR). */
export function toast(message: string, tone: ToastTone = "info") {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(EVENT, { detail: { message, tone } }));
}

const TONES: Record<ToastTone, { box: string; text: string; icon: typeof Info }> = {
  success: { box: "border-emerald-900/70 bg-emerald-950/90", text: "text-emerald-200", icon: CircleCheck },
  error: { box: "border-rose-900/70 bg-rose-950/90", text: "text-rose-200", icon: CircleX },
  warn: { box: "border-amber-900/70 bg-amber-950/90", text: "text-amber-200", icon: TriangleAlert },
  info: { box: "border-line bg-surface/95", text: "text-ink-dim", icon: Info },
};

let nextId = 1;

export function Toaster() {
  const [items, setItems] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: number) => {
    setItems((cur) => cur.filter((t) => t.id !== id));
  }, []);

  useEffect(() => {
    const onToast = (e: Event) => {
      const detail = (e as CustomEvent).detail as { message?: string; tone?: ToastTone };
      const message = detail?.message;
      if (!message) return;
      const id = nextId++;
      setItems((cur) => [...cur.slice(-3), { id, message, tone: detail.tone ?? "info" }]);
      window.setTimeout(() => dismiss(id), DISMISS_MS);
    };
    window.addEventListener(EVENT, onToast);
    return () => window.removeEventListener(EVENT, onToast);
  }, [dismiss]);

  return (
    <div
      aria-live="polite"
      aria-atomic="false"
      className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-80 flex-col gap-2"
    >
      {items.map((t) => {
        const tone = TONES[t.tone];
        const Icon = tone.icon;
        return (
          <div
            key={t.id}
            className={`pointer-events-auto flex items-start gap-2 rounded-lg border px-3.5 py-2.5 text-sm shadow-lg shadow-black/40 backdrop-blur ${tone.box} ${tone.text}`}
          >
            <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            <p className="min-w-0 flex-1 break-words">{t.message}</p>
            <button
              type="button"
              onClick={() => dismiss(t.id)}
              aria-label="Dismiss notification"
              className="shrink-0 rounded p-0.5 text-ink-faint transition-colors hover:text-ink"
            >
              <X className="h-3.5 w-3.5" aria-hidden />
            </button>
          </div>
        );
      })}
    </div>
  );
}
