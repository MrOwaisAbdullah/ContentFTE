"use client";

import Link from "next/link";
import { useEffect } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

/**
 * Error boundary for every console page (plan CON-07). Without it a thrown
 * render error — most often "the engine is down / timed out" — shows Next's
 * bare default page and drops the sidebar. This keeps the shell and offers a retry.
 */
export default function ConsoleError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Surfaces in the browser console / any client error reporter.
    console.error("[console] page error", error);
  }, [error]);

  return (
    <div className="mx-auto mt-16 max-w-lg rounded-2xl border border-line bg-card p-8 text-center shadow-xs" role="alert">
      <span className="mx-auto mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-rose-500/10 text-rose-400" aria-hidden>
        <AlertTriangle className="h-5 w-5" />
      </span>
      <h1 className="text-lg font-semibold text-ink">This page couldn&apos;t load</h1>
      <p className="mt-2 text-sm leading-relaxed text-ink-dim">
        The console hit an error while talking to the engine. The engine instance may be down, slow, or
        rejecting the request. Your data is unchanged.
      </p>
      {error.digest ? (
        <p className="mt-3 font-mono text-[11px] text-ink-faint">reference: {error.digest}</p>
      ) : null}
      <div className="mt-6 flex items-center justify-center gap-3">
        <button
          type="button"
          onClick={reset}
          className="inline-flex items-center gap-1.5 rounded-lg bg-accent-strong px-4 py-2 text-sm font-medium text-page transition-colors hover:bg-accent"
        >
          <RefreshCw className="h-3.5 w-3.5" aria-hidden />
          Try again
        </button>
        <Link
          href="/instances"
          className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-ink-dim transition-colors hover:bg-surface hover:text-ink"
        >
          Check instances
        </Link>
      </div>
    </div>
  );
}
