"use client";

// Console shell (Autonomous Kinetic Editorial Specification):
// Fixed left sidebar with brand bolt container, Dispatch Run CTA, kinetic active borders,
// system status health pill, operator profile, and topbar with cluster badge, site selector,
// centered search with ⌘K, and live status pill.

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  BarChart3,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ClipboardCheck,
  ExternalLink,
  FileClock,
  FileText,
  Globe,
  HelpCircle,
  Images,
  Layers,
  LayoutDashboard,
  ListOrdered,
  LogOut,
  Menu,
  Play,
  Rocket,
  ScrollText,
  Search,
  Settings,
  Sparkles,
  Workflow,
  X,
  Zap,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { logoutAction } from "@/actions/auth";
import { switchInstanceAction } from "@/actions/instances";
import { PendingButton } from "./interactive";
import { ThemeToggle } from "./theme";
import { CommandPalette } from "./palette";
import { CustomSiteSelect } from "@/components/custom-site-select";
import { SidebarTooltip } from "@/components/sidebar-tooltip";
import { Glyph } from "@/components/glyph";

/* ── nav model ─────────────────────────────────────────────────────────── */

type NavItem = {
  href: string;
  label: string;
  icon: string;
  lucideIcon: LucideIcon;
  badge?: "approvals" | "sites";
};

type NavSection = {
  title?: string;
  items: NavItem[];
};

const NAV_SECTIONS: NavSection[] = [
  {
    items: [
      { href: "/", label: "Overview", icon: "dashboard", lucideIcon: LayoutDashboard },
      { href: "/approvals", label: "Approvals", icon: "fact_check", lucideIcon: ClipboardCheck, badge: "approvals" },
    ],
  },
  {
    title: "Content",
    items: [
      { href: "/articles", label: "Pipeline", icon: "view_kanban", lucideIcon: FileText },
      { href: "/articles/keywords", label: "Keywords", icon: "key", lucideIcon: ListOrdered },
      { href: "/articles/research", label: "Research", icon: "manage_search", lucideIcon: Search },
      { href: "/articles/briefs", label: "Briefs", icon: "description", lucideIcon: ScrollText },
      { href: "/media", label: "Media", icon: "perm_media", lucideIcon: Images },
    ],
  },
  {
    title: "Operations",
    items: [
      { href: "/logs", label: "Logs", icon: "terminal", lucideIcon: FileClock },
      { href: "/insights", label: "Insights", icon: "insights", lucideIcon: BarChart3 },
      { href: "/stages", label: "Stages", icon: "conversion_path", lucideIcon: Workflow },
    ],
  },
  {
    title: "Fleet",
    items: [
      { href: "/sites", label: "Sites", icon: "domain", lucideIcon: Globe, badge: "sites" },
      { href: "/provision", label: "Provision", icon: "rocket_launch", lucideIcon: Rocket },
    ],
  },
];

/** Longest matching href wins, so /articles/keywords ≠ /articles. */
function activeHref(pathname: string): string {
  let best = "";
  for (const section of NAV_SECTIONS) {
    for (const item of section.items) {
      const hit = item.href === "/" ? pathname === "/" : pathname === item.href || pathname.startsWith(`${item.href}/`);
      if (hit && item.href.length > best.length) best = item.href;
    }
  }
  return best;
}

/* ── sidebar ───────────────────────────────────────────────────────────── */

function SidebarNav({
  approvalsCount,
  sitesCount,
  collapsed = false,
  onNavigate,
}: {
  approvalsCount: number;
  sitesCount: number;
  collapsed?: boolean;
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const site = searchParams.get("site");
  const active = activeHref(pathname);
  const withSite = (href: string) =>
    site ? `${href}${href.includes("?") ? "&" : "?"}site=${encodeURIComponent(site)}` : href;

  return (
    <nav
      className={`flex flex-col flex-1 w-full overflow-y-auto overflow-x-hidden custom-sidebar-scroll ${
        collapsed
          ? "gap-1.5 px-0 py-1"
          : "gap-2 px-3 py-1"
      }`}
    >
      {NAV_SECTIONS.map((section, si) => (
        <div key={section.title ?? si} className={collapsed ? "w-full space-y-1" : "space-y-1"}>
          {section.title ? (
            collapsed ? (
              <div className="my-2 border-t border-line/40 mx-3" />
            ) : (
              <p className="px-3 pb-0.5 text-[10px] font-mono font-semibold uppercase tracking-wider text-secondary/60">
                {section.title}
              </p>
            )
          ) : null}
          <div className={`flex flex-col ${collapsed ? "gap-1 items-center w-full" : "gap-1"}`}>
            {section.items.map((item) => {
              const isActive = item.href === active;

              if (collapsed) {
                return (
                  <div key={item.href} className="w-full flex justify-center py-0.5">
                    <SidebarTooltip
                      label={item.label}
                      badge={
                        item.badge === "approvals" && approvalsCount > 0 ? (
                          <span className="px-1.5 py-0.5 rounded text-[10px] bg-primary-container/20 text-primary-container font-bold">
                            {approvalsCount}
                          </span>
                        ) : item.badge === "sites" && sitesCount > 0 ? (
                          <span className="px-1.5 py-0.5 rounded text-[10px] bg-tertiary/20 text-tertiary font-bold">
                            {sitesCount}
                          </span>
                        ) : undefined
                      }
                      enabled={collapsed}
                    >
                      <Link
                        href={withSite(item.href)}
                        onClick={onNavigate}
                        aria-current={isActive ? "page" : undefined}
                        aria-label={item.label}
                        className={`flex items-center justify-center w-10 h-10 rounded-xl transition-all relative ${
                          isActive
                            ? "bg-primary-container/15 text-primary-container font-semibold border border-primary-container/30 shadow-xs"
                            : "text-secondary hover:text-ink hover:bg-surface-container"
                        }`}
                      >
                        <Glyph
                          name={item.icon}
                          className={`text-[20px] ${isActive ? "text-primary-container" : "text-secondary"}`}
                        />
                        {item.badge === "approvals" && approvalsCount > 0 ? (
                          <span className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-primary-container text-white text-[9px] font-mono font-bold flex items-center justify-center shadow-xs">
                            {approvalsCount}
                          </span>
                        ) : item.badge === "sites" && sitesCount > 0 ? (
                          <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-tertiary shadow-[0_0_6px_#4edea3]" />
                        ) : isActive ? (
                          <span className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-4 rounded-r bg-primary-container" />
                        ) : null}
                      </Link>
                    </SidebarTooltip>
                  </div>
                );
              }

              return (
                <Link
                  key={item.href}
                  href={withSite(item.href)}
                  onClick={onNavigate}
                  aria-current={isActive ? "page" : undefined}
                  className={`flex items-center gap-3 px-3 py-1.5 rounded-lg text-[13px] font-medium transition-all ${
                    isActive
                      ? "bg-surface-container text-primary-container font-semibold border-l-2 border-primary-container shadow-xs"
                      : "text-secondary hover:text-ink hover:bg-surface-container/60"
                  }`}
                >
                  <Glyph
                    name={item.icon}
                    className={`text-[17px] shrink-0 ${isActive ? "text-primary-container" : "text-secondary"}`}
                  />
                  <span className="truncate">{item.label}</span>

                  {/* Badges */}
                  {isActive && !item.badge ? (
                    <span className="ml-auto w-1.5 h-1.5 rounded-full bg-primary-container shrink-0" />
                  ) : null}

                  {item.badge === "approvals" && approvalsCount > 0 ? (
                    <span className="ml-auto text-[11px] font-mono bg-primary-container/20 text-primary-container px-1.5 py-0.5 rounded font-bold shrink-0">
                      {approvalsCount}
                    </span>
                  ) : null}

                  {item.badge === "sites" && sitesCount > 0 ? (
                    <span className="ml-auto text-[11px] font-mono bg-surface-container-high border border-outline-variant/40 text-tertiary px-1.5 py-0.5 rounded shrink-0">
                      {sitesCount}
                    </span>
                  ) : null}
                </Link>
              );
            })}
          </div>
        </div>
      ))}
    </nav>
  );
}

function BrandHeader({
  collapsed = false,
  onToggleCollapse,
  onNavigate,
}: {
  collapsed?: boolean;
  onToggleCollapse?: () => void;
  onNavigate?: () => void;
}) {
  if (collapsed) {
    return (
      <div className="flex flex-col items-center gap-2.5 w-full">
        {/* Logo with Tooltip */}
        <SidebarTooltip label="ContentFTE" description="Autonomous Fleet Engine" enabled={collapsed}>
          <Link
            href="/"
            onClick={onNavigate}
            className="w-10 h-10 rounded-xl bg-primary-container flex items-center justify-center text-white shadow-[0_0_16px_rgba(242,100,58,0.35)] hover:brightness-110 transition-all cursor-pointer"
            aria-label="ContentFTE Home"
          >
            <Glyph name="bolt" className="text-white text-[20px]" />
          </Link>
        </SidebarTooltip>


        {/* Expand Toggle Button */}
        {onToggleCollapse && (
          <SidebarTooltip label="Expand Sidebar" description="Show navigation labels" enabled={collapsed}>
            <button
              type="button"
              onClick={onToggleCollapse}
              aria-label="Expand sidebar"
              className="w-10 h-8 rounded-lg flex items-center justify-center text-secondary hover:text-ink hover:bg-surface-container transition-colors cursor-pointer"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </SidebarTooltip>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-y-4">
      <div className="flex items-center justify-between">
        <Link href="/" onClick={onNavigate} className="flex items-center gap-x-3 px-1 py-1 group min-w-0">
          <div className="w-8 h-8 rounded-lg bg-primary-container flex items-center justify-center text-white shadow-[0_0_16px_rgba(242,100,58,0.35)] group-hover:brightness-110 transition-all shrink-0">
            <Glyph name="bolt" className="text-white text-[18px]" />
          </div>
          <div className="flex flex-col min-w-0">
            <span className="text-[16px] font-headline font-bold tracking-tight text-ink leading-tight truncate">
              ContentFTE
            </span>
            <span className="text-[11px] font-mono text-secondary truncate">
              Autonomous Fleet Engine
            </span>
          </div>
        </Link>
        {onToggleCollapse && (
          <button
            type="button"
            onClick={onToggleCollapse}
            aria-label="Collapse sidebar"
            className="p-1.5 rounded-lg text-secondary hover:text-ink hover:bg-surface-container transition-colors cursor-pointer shrink-0"
            title="Collapse sidebar"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
        )}
      </div>

    </div>
  );
}

/* ── topbar ────────────────────────────────────────────────────────────── */

function Topbar({
  sites,
  instances,
  currentInstance,
  engineOk,
  onMenu,
  onOpenPalette,
}: {
  sites: { slug: string; name: string }[];
  instances: string[];
  currentInstance: string;
  engineOk: boolean;
  onMenu: () => void;
  onOpenPalette: () => void;
}) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const router = useRouter();
  const site = searchParams.get("site") ?? "";

  const switchSite = (slug: string) => {
    const params = new URLSearchParams(searchParams);
    if (slug) params.set("site", slug);
    else params.delete("site");
    const qs = params.toString();
    router.push(qs ? `${pathname}?${qs}` : pathname);
  };

  const selectedSiteObj = sites.find((s) => s.slug === site);

  return (
    <header className="sticky top-0 w-full z-30 bg-page/90 backdrop-blur-md border-b border-line flex items-center justify-between h-16 px-4 lg:px-8 select-none gap-4">
      {/* Left: Mobile Toggle & Cluster Badge */}
      <div className="flex items-center gap-2.5 shrink-0 min-w-0">
        <button
          type="button"
          onClick={onMenu}
          aria-label="Open navigation drawer"
          className="p-1.5 rounded-lg border border-line bg-surface-container text-secondary hover:text-ink lg:hidden"
        >
          <Glyph name="menu" className="text-[20px]" />
        </button>

        {instances.length > 1 ? (
          <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-surface-container border border-outline-variant/30 text-[12px] font-mono text-ink shrink-0">
            <form action={switchInstanceAction} className="inline-flex items-center">
              <select
                name="instance"
                defaultValue={currentInstance}
                onChange={(e) => e.target.form?.requestSubmit()}
                className="bg-transparent text-secondary text-[11px] font-mono focus:outline-none cursor-pointer"
              >
                {instances.map((name) => (
                  <option key={name} value={name} className="bg-card text-ink">
                    {name}
                  </option>
                ))}
              </select>
            </form>
          </div>
        ) : null}

        {/* Site Switcher Context (Custom Themed Dropdown) — desktop only; mobile uses the drawer */}
        {sites.length > 0 ? (
          <div className="hidden sm:flex items-center shrink-0">
            <CustomSiteSelect
              sites={sites}
              currentSite={site}
              onSelect={switchSite}
            />
          </div>
        ) : null}
      </div>

      {/* Center: Search Trigger (⌘K) */}
      <div className="flex-1 max-w-xs mx-auto px-2 min-w-0">
        <button
          type="button"
          onClick={onOpenPalette}
          className="relative flex items-center w-full h-8 pl-8 pr-12 bg-surface-lowest text-secondary text-[12px] font-mono rounded-lg border border-line hover:border-outline-variant/60 focus:outline-none focus:border-primary-container focus:ring-1 focus:ring-primary-container transition-all group"
        >
          <Glyph name="search" className="absolute left-2.5 text-secondary/60 text-[15px] pointer-events-none group-hover:text-primary-container transition-colors" />
          <span className="truncate text-left">Search fleet...</span>
          <kbd className="absolute right-2 px-1.5 py-0.5 rounded bg-surface-container border border-line text-[10px] font-mono text-secondary select-none">
            ⌘K
          </kbd>
        </button>
      </div>

      {/* Right: Status Pill & Utility Actions */}
      <div className="flex items-center gap-3 shrink-0 ml-auto">

        {/* Theme Toggle */}
        <ThemeToggle />

        {/* Deploy / Dispatch Run CTA */}
      </div>
    </header>
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
  articles = [],
}: {
  children: ReactNode;
  sites: { slug: string; name: string }[];
  instances: string[];
  currentInstance: string;
  engineOk: boolean;
  approvalsCount: number;
  articles?: { id: number; title: string; slug: string; site: string; status: string }[];
}) {
  const [navOpen, setNavOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const router = useRouter();

  useEffect(() => {
    const saved = localStorage.getItem("console_sidebar_collapsed");
    if (saved === "true") setSidebarCollapsed(true);
  }, []);

  const toggleSidebar = () => {
    setSidebarCollapsed((prev) => {
      const next = !prev;
      localStorage.setItem("console_sidebar_collapsed", String(next));
      return next;
    });
  };

  // Close the mobile drawer whenever navigation happens.
  useEffect(() => {
    setNavOpen(false);
  }, [pathname]);

  return (
    <div className="flex min-h-screen w-full max-w-full overflow-x-hidden bg-page text-ink selection:bg-primary-container selection:text-white">
      {/* Desktop Fixed Left Sidebar */}
      <aside
        className={`fixed left-0 top-0 bottom-0 hidden h-screen shrink-0 flex-col justify-between border-r border-line bg-surface select-none lg:flex transition-all duration-200 z-30 px-0 py-4 overflow-hidden ${
          sidebarCollapsed ? "w-[68px] items-center" : "w-64"
        }`}
      >
        {/* Brand & Dispatch Run & Nav Items */}
        <div className={`flex flex-col flex-1 min-h-0 ${sidebarCollapsed ? "gap-y-3 w-full" : "gap-y-5 w-full"}`}>
          <div className={sidebarCollapsed ? "w-full px-2 shrink-0" : "w-full px-4 shrink-0"}>
            <BrandHeader
              collapsed={sidebarCollapsed}
              onToggleCollapse={toggleSidebar}
            />
          </div>
          <div className="flex-1 min-h-0 overflow-hidden flex flex-col w-full">
            <SidebarNav
              approvalsCount={approvalsCount}
              sitesCount={sites.length}
              collapsed={sidebarCollapsed}
            />
          </div>
        </div>

        {/* Sidebar Footer Controls */}
        {sidebarCollapsed ? (
          <div className="flex flex-col items-center gap-2 pt-3 border-t border-line w-full px-2 shrink-0">
            {/* Health Indicator with Tooltip */}
            <SidebarTooltip
              label={engineOk ? "Autonomous Engine: HEALTHY" : "Autonomous Engine: DOWN"}
              description="Background orchestrator heartbeat"
              enabled={sidebarCollapsed}
            >
              <div className="w-10 h-9 rounded-xl bg-surface-container border border-line flex items-center justify-center cursor-pointer">
                <span
                  className={`w-2 h-2 rounded-full ${
                    engineOk ? "bg-tertiary shadow-[0_0_8px_#4edea3]" : "bg-danger"
                  }`}
                />
              </div>
            </SidebarTooltip>

            {/* Settings Icon with Tooltip */}
            <SidebarTooltip
              label="Engine Settings"
              description="Configure engine instances & keys"
              enabled={sidebarCollapsed}
            >
              <Link
                href="/instances"
                className="w-10 h-9 rounded-xl flex items-center justify-center text-secondary hover:text-ink hover:bg-surface-container transition-colors cursor-pointer"
                aria-label="Engine Settings"
              >
                <Glyph name="settings" className="text-[18px]" />
              </Link>
            </SidebarTooltip>

            {/* Operator Profile with Tooltip */}
            <SidebarTooltip
              label="Operator"
              description="Console Operator (Operator)"
              enabled={sidebarCollapsed}
            >
              <div className="w-8 h-8 rounded-full bg-primary-container/20 border border-primary-container/40 flex items-center justify-center text-primary-container text-xs font-bold cursor-pointer">
                CF
              </div>
            </SidebarTooltip>

            {/* Sign Out with Tooltip */}
            <SidebarTooltip
              label="Sign Out"
              description="Terminate operator session"
              enabled={sidebarCollapsed}
            >
              <form action={logoutAction} className="w-full flex justify-center">
                <PendingButton
                  title="Sign out of Console"
                  aria-label="Sign out"
                  className="w-10 h-8 rounded-lg flex items-center justify-center text-secondary hover:text-danger hover:bg-surface-container transition-colors cursor-pointer"
                  leftIcon={<Glyph name="logout" className="text-[17px]" />}
                >
                  <span className="sr-only">Sign out</span>
                </PendingButton>
              </form>
            </SidebarTooltip>
          </div>
        ) : (
          <div className="flex flex-col gap-3 pt-3 border-t border-line px-4 w-full shrink-0">
            {/* Engine Health Card */}
            <div className="px-2.5 py-1.5 bg-surface-lowest rounded-lg border border-line flex items-center justify-between text-[11px] font-mono">
              <div className="flex items-center gap-2">
                <span
                  className={`w-2 h-2 rounded-full ${
                    engineOk ? "bg-tertiary shadow-[0_0_8px_#4edea3]" : "bg-danger"
                  }`}
                />
                <span className="text-secondary">{engineOk ? "Autonomous Engine" : "Engine Offline"}</span>
              </div>
              <span className={engineOk ? "text-tertiary font-semibold" : "text-danger font-semibold"}>
                {engineOk ? "HEALTHY" : "DOWN"}
              </span>
            </div>

            {/* Quick Support & Settings */}
            <div className="flex flex-col gap-0.5">
              <a
                href="https://github.com/MrOwaisAbdullah/SEO-Blog-Agent/tree/master/docs"
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-2 px-2.5 py-1.5 text-secondary hover:text-ink hover:bg-surface-container rounded-lg text-[12px] transition-colors"
              >
                <Glyph name="help" className="text-[16px]" />
                <span>Documentation</span>
              </a>
              <Link
                href="/instances"
                className="flex items-center gap-2 px-2.5 py-1.5 text-secondary hover:text-ink hover:bg-surface-container rounded-lg text-[12px] transition-colors"
              >
                <Glyph name="settings" className="text-[16px]" />
                <span>Engine Settings</span>
              </Link>
            </div>

            {/* Operator Profile & Sign Out */}
            <div className="flex items-center justify-between gap-2 px-2.5 py-2 rounded-lg bg-surface-container border border-outline-variant/30">
              <div className="flex items-center gap-2.5 min-w-0">
                <div className="w-7 h-7 rounded-full bg-primary-container/20 border border-primary-container/40 flex items-center justify-center text-primary-container text-xs font-bold shrink-0">
                  CF
                </div>
                <div className="flex flex-col min-w-0">
                  <span className="text-[12px] font-semibold text-ink truncate">Operator</span>
                  <span className="text-[11px] font-mono text-secondary truncate">Console Operator</span>
                </div>
              </div>
              <form action={logoutAction} className="shrink-0">
                <PendingButton
                  title="Sign out of Console"
                  aria-label="Sign out"
                  className="p-1 rounded text-secondary hover:text-danger hover:bg-surface-lowest transition-colors"
                  leftIcon={<Glyph name="logout" className="text-[16px]" />}
                >
                  <span className="sr-only">Sign out</span>
                </PendingButton>
              </form>
            </div>
          </div>
        )}
      </aside>

      {/* Mobile Navigation Drawer */}
      {navOpen ? (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-xs"
            onClick={() => setNavOpen(false)}
            aria-hidden
          />
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Navigation"
            className="absolute left-0 top-0 flex h-full w-64 flex-col justify-between border-r border-line bg-surface p-5 shadow-2xl shadow-black/80"
          >
            <div className="flex flex-col gap-y-6">
              <div className="flex items-center justify-between">
                <BrandHeader onNavigate={() => setNavOpen(false)} />
                <button
                  type="button"
                  onClick={() => setNavOpen(false)}
                  aria-label="Close navigation"
                  className="rounded-lg p-1.5 text-secondary hover:text-ink hover:bg-surface-container"
                >
                  <X className="h-5 w-5" aria-hidden />
                </button>
              </div>
              <SidebarNav
                approvalsCount={approvalsCount}
                sitesCount={sites.length}
                onNavigate={() => setNavOpen(false)}
              />
            </div>

            <div className="flex flex-col gap-3 pt-3 border-t border-line">
              {sites.length > 1 ? (
                <div className="flex items-center justify-between gap-2 px-2.5 py-2 rounded-lg bg-surface-container border border-outline-variant/30">
                  <CustomSiteSelect sites={sites} currentSite={searchParams.get("site") ?? ""} onSelect={(slug) => {
                    const params = new URLSearchParams(searchParams);
                    if (slug) params.set("site", slug);
                    else params.delete("site");
                    router.push(params.toString() ? `${pathname}?${params.toString()}` : pathname);
                    setNavOpen(false);
                  }} />
                </div>
              ) : null}
              <div className="flex items-center justify-between gap-2 px-2.5 py-2 rounded-lg bg-surface-container border border-outline-variant/30">
                <span className="text-[12px] font-semibold text-ink truncate">Operator</span>
                <form action={logoutAction}>
                  <PendingButton
                    title="Sign out"
                    className="text-xs text-secondary hover:text-danger"
                    leftIcon={<LogOut className="h-4 w-4" />}
                  >
                    <span className="sr-only">Sign out</span>
                  </PendingButton>
                </form>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {/* Main Content Area */}
      <div
        className={`flex min-w-0 flex-1 flex-col w-full max-w-full overflow-x-hidden transition-all duration-200 ${
          sidebarCollapsed ? "lg:pl-[68px]" : "lg:pl-64"
        }`}
      >
        <Topbar
          sites={sites}
          instances={instances}
          currentInstance={currentInstance}
          engineOk={engineOk}
          onMenu={() => setNavOpen(true)}
          onOpenPalette={() => setPaletteOpen(true)}
        />
        <main id="main-content" className="w-full min-w-0 flex-1 p-6 lg:p-10 max-w-[1600px] mx-auto">{children}</main>
      </div>

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        sites={sites}
        articles={articles}
      />
    </div>
  );
}
