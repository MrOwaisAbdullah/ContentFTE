"use client";

// Client-side interaction primitives (docs/console-dashboard-plan.md §3):
// pending states on every server-action button, confirm-before-destructive,
// per-site switchers, and active nav highlighting. Server pages embed these
// inside their server-action <form>s — useFormStatus binds to that form.

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useFormStatus } from "react-dom";
import {
  Boxes,
  FileClock,
  FileText,
  LayoutDashboard,
  Loader2,
  Rocket,
  Globe,
  Workflow,
} from "lucide-react";
import type { MouseEventHandler, ReactNode } from "react";

export function PendingButton({
  children,
  className = "",
  confirmMessage,
  pendingLabel,
  disabled,
}: {
  children: ReactNode;
  className?: string;
  confirmMessage?: string;
  pendingLabel?: string;
  disabled?: boolean;
}) {
  const { pending } = useFormStatus();
  const handleClick: MouseEventHandler<HTMLButtonElement> = (e) => {
    if (confirmMessage && !window.confirm(confirmMessage)) e.preventDefault();
  };
  return (
    <button
      type="submit"
      disabled={pending || disabled}
      aria-busy={pending}
      onClick={handleClick}
      className={className}
    >
      {pending ? (
        <>
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
          <span>{pendingLabel ?? children}</span>
        </>
      ) : (
        children
      )}
    </button>
  );
}

/** Site selector that navigates the shared `?site=` param in place. */
export function SiteSwitcher({
  sites,
  current,
  basePath,
  param = "site",
  keep = {},
}: {
  sites: { slug: string; name?: string | null }[];
  current: string;
  basePath: string;
  param?: string;
  keep?: Record<string, string>;
}) {
  const router = useRouter();
  return (
    <label className="flex items-center gap-2 text-xs text-ink-faint">
      <span>Site</span>
      <select
        value={current}
        onChange={(e) => {
          const v = e.target.value;
          const qs = new URLSearchParams(keep);
          if (v) qs.set(param, v);
          router.push(qs.size ? `${basePath}?${qs}` : basePath);
        }}
        className="rounded-md border border-line bg-surface px-2 py-1 text-xs text-ink hover:border-ink-faint"
      >
        {sites.map((s) => (
          <option key={s.slug} value={s.slug}>
            {s.name || s.slug}
          </option>
        ))}
      </select>
    </label>
  );
}

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/articles", label: "Articles", icon: FileText },
  { href: "/logs", label: "Logs", icon: FileClock },
  { href: "/sites", label: "Sites", icon: Globe },
  { href: "/instances", label: "Instances", icon: Boxes },
  { href: "/stages", label: "Stages", icon: Workflow },
  { href: "/provision", label: "Provision", icon: Rocket },
];

export function NavLinks() {
  const pathname = usePathname();
  return (
    <nav aria-label="Primary" className="flex flex-wrap items-center gap-1 text-sm">
      {NAV.map((n) => {
        const active =
          n.href === "/" ? pathname === "/" : pathname === n.href || pathname.startsWith(`${n.href}/`);
        const Icon = n.icon;
        return (
          <Link
            key={n.href}
            href={n.href}
            aria-current={active ? "page" : undefined}
            className={`flex items-center gap-1.5 rounded-md px-2.5 py-1.5 transition-colors ${
              active
                ? "bg-surface font-medium text-ink"
                : "text-ink-dim hover:bg-surface/60 hover:text-ink"
            }`}
          >
            <Icon className="h-3.5 w-3.5" aria-hidden />
            <span>{n.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
