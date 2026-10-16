"use client";

// Console shell (docs/console-dashboard-plan.md §4, Wave 1): fixed sidebar IA
// + topbar (breadcrumb, global site switcher, ⌘K placeholder, engine health
// dot, instance switcher, sign out). The `?site=` URL param is the single
// site-context contract: the topbar switcher sets it on the current path and
// sidebar links carry it along, so the selection is sticky across pages.
// Not-yet-built destinations (Approvals, Publish queue, Media, Insights land
// in Waves 2–4) render disabled with a "soon" chip — the IA stays stable.

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  BarChart3,
  Bot,
  Boxes,
  ClipboardCheck,
  FileClock,
  FileText,
  Globe,
  Images,
  LayoutDashboard,
  ListOrdered,
  Menu,
  Rocket,
  ScrollText,
  Search,
  Send,
  Workflow,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { logoutAction } from "@/actions/auth";
import { switchInstanceAction } from "@/actions/instances";
import { PendingButton } from "./interactive";

/* ── nav model ─────────────────────────────────────────────────────────── */

type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Route lands in a later wave — rendered disabled, not a link. */
  soon?: boolean;
  /** Renders the approvals work-queue count. */
  badge?: boolean;
};

const SECTIONS: { title?: string; items: NavItem[] }[] = [
  {
    items: [
      { href: "/", label: "Overview", icon: LayoutDashboard },
      { href: "/approvals", label: "Approvals", icon: ClipboardCheck, soon: true, badge: true },
      { href: "/publish", label: "Publish queue", icon: Send, soon: true },
    ],
  },
  {
    title: "Content",
    items: [
      { href: "/articles", label: "Content pipeline", icon: FileText },
      { href: "/articles/keywords", label: "Keyword ledger", icon: ListOrdered },
      { href: "/articles/research", label: "Research", icon: Search },
      { href: "/articles/briefs", label: "Briefs", icon: ScrollText },
      { href: "/media", label: "Media", icon: Images, soon: true },
    ],
  },
  {
    title: "Ops",
    items: [
      { href: "/logs", label: "Logs", icon: FileClock },
      { href: "/insights", label: "Insights", icon: BarChart3, soon: true },
      { href: "/stages", label: "Stages", icon: Workflow },
    ],
  },
  {
    title: "Admin",
    items: [
      { href: "/sites", label: "Sites", icon: Globe },
      { href: "/instances", label: "Instances", icon: Boxes },
      { href: "/provision", label: "Provision", icon: Rocket },
    ],
  },
];

/** Longest matching href wins, so /articles/keywords ≠ /articles. */
function activeHref(pathname: string): string {
  let best = "";
  for (const s of SECTIONS) {
    for (const i of s.items) {
      if (i.soon) continue;
      const hit = i.href === "/" ? pathname === "/" : pathname === i.href || pathname.startsWith(`${i.href}/`);
      if (hit && i.href.length > best.length) best = i.href;
    }
  }
  return best;
}

const BREADCRUMB_TOP: Record<string, string> = {
  articles: "Content pipeline",
  logs: "Logs",
  sites: "Sites",
  instances: "Instances",
  stages: "Stages",
  provision: "Provision",
  approvals: "Approvals",
  publish: "Publish queue",
  media: "Media",
  insights: "Insights",
};

const BREADCRUMB_ARTICLE_TAB: Record<string, string> = {
  keywords: "Keyword ledger",
  research: "Research",
  briefs: "Briefs",
};

function breadcrumb(pathname: string): { parent?: string; label: string } {
  if (pathname === "/") return { label: "Overview" };
  if (pathname.startsWith("/articles/")) {
    const seg = pathname.slice("/articles/".length);
    const first = seg.split("/")[0];
    if (/^\d+$/.test(first)) return { parent: "Content pipeline", label: `Article #${first}` };
    return { parent: "Content", label: BREADCRUMB_ARTICLE_TAB[first] ?? "Content" };
  }
  const first = pathname.split("/")[1] ?? "";
  return { label: BREADCRUMB_TOP[first] ?? first };
}

/* ── sidebar ───────────────────────────────────────────────────────────── */

function SidebarNav({ approvalsCount, onNavigate }: { approvalsCount: number; onNavigate?: () => void }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const site = searchParams.get("site");
  const active = activeHref(pathname);
  const withSite = (href: string) =>
    site ? `${href}${href.includes("?") ? "&" : "?"}site=${encodeURIComponent(site)}` : href;

  return (
    <nav aria-label="Console" className="flex-1 space-y-6 overflow-y-auto px-3 py-4">
      {SECTIONS.map((section, si) => (
        <div key={section.title ?? si}>
          {section.title ? (
            <p className="mb-1.5 px-2 text-[10px] font-semibold uppercase tracking-widest text-ink-faint/80">
              {section.title}
            </p>
          ) : null}
          <ul className="space-y-0.5">
            {section.items.map((item) => {
              const Icon = item.icon;
              if (item.soon) {
                return (
                  <li key={item.href}>
                    <span
                      aria-disabled="true"
                      title="Lands in a later console wave"
                      className="flex cursor-default items-center gap-2.5 rounded-md px-2 py-1.5 text-sm text-ink-faint/60"
                    >
                      <Icon className="h-4 w-4 shrink-0" aria-hidden />
                      {item.label}
                      {item.badge && approvalsCount > 0 ? (
                        <span className="ml-auto rounded-full bg-amber-500/15 px-1.5 py-0.5 font-mono text-[10px] leading-none text-gold">
                          {approvalsCount}
                        </span>
                      ) : (
                        <span className="ml-auto rounded-full border border-line px-1.5 py-0.5 text-[9px] uppercase leading-none tracking-wide">
                          soon
                        </span>
                      )}
                    </span>
                  </li>
                );
              }
              const isActive = item.href === active;
              return (
                <li key={item.href}>
                  <Link
                    href={withSite(item.href)}
                    onClick={onNavigate}
                    aria-current={isActive ? "page" : undefined}
                    className={`flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm transition-colors ${
                      isActive
                        ? "bg-surface font-medium text-ink"
                        : "text-ink-dim hover:bg-surface/50 hover:text-ink"
                    }`}
                  >
                    <Icon className={`h-4 w-4 shrink-0 ${isActive ? "text-accent" : ""}`} aria-hidden />
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}

function Brand({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <Link
      href="/"
      onClick={onNavigate}
      className="flex items-center gap-2.5 border-b border-line px-4 py-4 text-sm font-semibold tracking-wide text-accent"
    >
      <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent/10" aria-hidden>
        <Bot className="h-4 w-4" />
      </span>
      ContentFTE
    </Link>
  );
}

/* ── topbar ────────────────────────────────────────────────────────────── */

function Topbar({
  sites,
  instances,
  currentInstance,
  engineOk,
  onMenu,
}: {
  sites: { slug: string; name: string }[];
  instances: string[];
  currentInstance: string;
  engineOk: boolean;
  onMenu: () => void;
}) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const router = useRouter();
  const crumb = breadcrumb(pathname);
  const site = searchParams.get("site") || sites[0]?.slug || "";

  const switchSite = (slug: string) => {
    const params = new URLSearchParams(searchParams);
    if (slug) params.set("site", slug);
    else params.delete("site");
    const qs = params.toString();
    router.push(qs ? `${pathname}?${qs}` : pathname);
  };

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2.5 lg:px-6">
      <button
        type="button"
        onClick={onMenu}
        aria-label="Open navigation"
        className="rounded-md border border-line bg-surface/60 p-1.5 text-ink-dim hover:text-ink lg:hidden"
      >
        <Menu className="h-4 w-4" aria-hidden />
      </button>

      <p className="flex min-w-0 items-center gap-1.5 text-sm">
        {crumb.parent ? (
          <>
            <span className="truncate text-ink-faint">{crumb.parent}</span>
            <span className="text-ink-faint/60" aria-hidden>
              ›
            </span>
          </>
        ) : null}
        <span className="truncate font-medium text-ink">{crumb.label}</span>
      </p>

      <div className="ml-auto flex items-center gap-2.5">
        {sites.length > 0 ? (
          <label className="flex items-center gap-1.5 text-xs text-ink-faint">
            <Globe className="h-3.5 w-3.5" aria-hidden />
            <span className="sr-only sm:not-sr-only">Site</span>
            <select
              value={site}
              onChange={(e) => switchSite(e.target.value)}
              className="rounded-md border border-line bg-surface px-2 py-1 text-xs text-ink hover:border-ink-faint"
            >
              {sites.map((s) => (
                <option key={s.slug} value={s.slug}>
                  {s.name || s.slug}
                </option>
              ))}
            </select>
          </label>
        ) : null}

        <button
          type="button"
          title="Command palette — placeholder"
          className="hidden items-center gap-2 rounded-md border border-line bg-surface/60 px-2.5 py-1 text-xs text-ink-faint hover:border-ink-faint hover:text-ink-dim md:flex"
        >
          <Search className="h-3.5 w-3.5" aria-hidden />
          Search
          <kbd className="rounded border border-line bg-page px-1 py-0.5 font-mono text-[10px] leading-none">⌘K</kbd>
        </button>

        <span
          title={engineOk ? "Engine reachable" : "Engine unreachable"}
          className={`flex items-center gap-1.5 text-xs ${
            engineOk ? "text-emerald-300" : "text-rose-300"
          }`}
        >
          <span
            className={`h-1.5 w-1.5 rounded-full ${engineOk ? "bg-emerald-400" : "bg-danger"}`}
            aria-hidden
          />
          <span className="hidden sm:inline">{engineOk ? "engine ok" : "engine down"}</span>
        </span>

        {instances.length > 1 ? (
          <form action={switchInstanceAction} className="flex items-center gap-1.5">
            <label className="text-xs text-ink-faint" htmlFor="instance-switch">
              <span className="sr-only">Instance</span>
            </label>
            <select
              id="instance-switch"
              name="instance"
              defaultValue={currentInstance}
              className="rounded-md border border-line bg-surface px-2 py-1 text-xs text-ink"
            >
              {instances.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
            <PendingButton className="rounded-md border border-line bg-page px-2 py-1 text-xs text-ink-dim hover:border-ink-faint hover:text-ink">
              Switch
            </PendingButton>
          </form>
        ) : (
          <span className="hidden rounded-md border border-line bg-surface/60 px-2 py-1 text-xs text-ink-faint sm:block">
            {currentInstance}
          </span>
        )}

        <form action={logoutAction}>
          <PendingButton className="rounded-md px-2 py-1 text-xs text-ink-faint hover:text-ink">
            Sign out
          </PendingButton>
        </form>
      </div>
    </div>
  );
}

/* ── shell ─────────────────────────────────────────────────────────────── */

export function ConsoleShell({
  children,
  sites,
  instances,
  currentInstance,
  engineOk,
  approvalsCount,
}: {
  children: ReactNode;
  sites: { slug: string; name: string }[];
  instances: string[];
  currentInstance: string;
  engineOk: boolean;
  approvalsCount: number;
}) {
  const [navOpen, setNavOpen] = useState(false);
  const pathname = usePathname();

  // Close the mobile drawer whenever navigation happens.
  useEffect(() => {
    setNavOpen(false);
  }, [pathname]);

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-line bg-card/50 lg:flex">
        <Brand />
        <SidebarNav approvalsCount={approvalsCount} />
        <p className="border-t border-line px-4 py-3 text-[10px] leading-relaxed text-ink-faint/70">
          Operator console · internal
        </p>
      </aside>

      {navOpen ? (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div
            className="absolute inset-0 bg-black/60"
            onClick={() => setNavOpen(false)}
            aria-hidden
          />
          <div role="dialog" aria-modal="true" aria-label="Navigation" className="absolute left-0 top-0 flex h-full w-64 flex-col border-r border-line bg-card shadow-2xl shadow-black/60">
            <div className="flex items-center justify-between pr-3">
              <Brand onNavigate={() => setNavOpen(false)} />
              <button
                type="button"
                onClick={() => setNavOpen(false)}
                aria-label="Close navigation"
                className="rounded-md p-1.5 text-ink-faint hover:text-ink"
              >
                <X className="h-4 w-4" aria-hidden />
              </button>
            </div>
            <SidebarNav approvalsCount={approvalsCount} onNavigate={() => setNavOpen(false)} />
          </div>
        </div>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 border-b border-line bg-page/90 backdrop-blur">
          <Topbar
            sites={sites}
            instances={instances}
            currentInstance={currentInstance}
            engineOk={engineOk}
            onMenu={() => setNavOpen(true)}
          />
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8 lg:px-6">{children}</main>
      </div>
    </div>
  );
}
