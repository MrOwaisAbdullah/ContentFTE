"use client";

// Shows a live "updated Ns ago" stamp from a server-provided ISO timestamp,
// plus a small engine health indicator. UX-23.
import { useEffect, useState } from "react";

export function Freshness({ at, ok }: { at: string; ok: boolean }) {
  // Render a stable value on the server and only start the clock after mount;
  // using Date.now() in the initial render causes a hydration mismatch (and
  // React's recovery pass can drop classes added by the theme bootstrap script).
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 10000);
    return () => clearInterval(id);
  }, []);
  const age = (() => {
    if (now == null) return "just now";
    const t = Date.parse(at);
    if (!Number.isFinite(t)) return "just now";
    const s = Math.floor((now - t) / 1000);
    if (s < 5) return "just now";
    if (s < 60) return `${s}s ago`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 48) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  })();
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] font-mono text-ink-faint">
      <span className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-tertiary" : "bg-danger"}`} aria-hidden />
      {ok ? `synced ${age}` : "engine offline"}
    </span>
  );
}