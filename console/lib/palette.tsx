"use client";

import { useEffect, useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import {
  BarChart3,
  Boxes,
  ClipboardCheck,
  FileClock,
  FileText,
  Globe,
  Images,
  LayoutDashboard,
  ListOrdered,
  Moon,
  Rocket,
  ScrollText,
  Search,
  Send,
  Sun,
  Workflow,
  X,
} from "lucide-react";

type PaletteItem = {
  id: string;
  category: "Navigation" | "Sites" | "Content" | "Actions";
  title: string;
  subtitle?: string;
  icon: typeof Search;
  action: () => void;
};

export function CommandPalette({
  open,
  onClose,
  sites = [],
  articles = [],
}: {
  open: boolean;
  onClose: () => void;
  sites: { slug: string; name: string }[];
  articles?: { id: number; title: string; slug: string; site: string; status: string }[];
}) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [selectedIdx, setSelectedIdx] = useState(0);

  const items = useMemo<PaletteItem[]>(() => {
    const list: PaletteItem[] = [
      {
        id: "nav-overview",
        category: "Navigation",
        title: "Overview",
        subtitle: "Mission Control & Fleet Health",
        icon: LayoutDashboard,
        action: () => { router.push("/"); onClose(); },
      },
      {
        id: "nav-approvals",
        category: "Navigation",
        title: "Approvals",
        subtitle: "Review generated articles & evidence",
        icon: ClipboardCheck,
        action: () => { router.push("/approvals"); onClose(); },
      },
      {
        id: "nav-publish",
        category: "Navigation",
        title: "Publish Queue",
        subtitle: "Approved articles ready to dispatch",
        icon: Send,
        action: () => { router.push("/publish"); onClose(); },
      },
      {
        id: "nav-articles",
        category: "Navigation",
        title: "Content Pipeline",
        subtitle: "All articles & live status",
        icon: FileText,
        action: () => { router.push("/articles"); onClose(); },
      },
      {
        id: "nav-keywords",
        category: "Navigation",
        title: "Keyword Ledger",
        subtitle: "Queue, intent, priority scores",
        icon: ListOrdered,
        action: () => { router.push("/articles/keywords"); onClose(); },
      },
      {
        id: "nav-research",
        category: "Navigation",
        title: "Research Findings",
        subtitle: "Extracted SERP & competitor research",
        icon: Search,
        action: () => { router.push("/articles/research"); onClose(); },
      },
      {
        id: "nav-briefs",
        category: "Navigation",
        title: "Content Briefs",
        subtitle: "Approved outlines & FAQs",
        icon: ScrollText,
        action: () => { router.push("/articles/briefs"); onClose(); },
      },
      {
        id: "nav-stages",
        category: "Navigation",
        title: "Pipeline Stages",
        subtitle: "Autonomous execution & cron runners",
        icon: Workflow,
        action: () => { router.push("/stages"); onClose(); },
      },
      {
        id: "nav-insights",
        category: "Navigation",
        title: "Insights & Cost",
        subtitle: "Token spend, models & ROI",
        icon: BarChart3,
        action: () => { router.push("/insights"); onClose(); },
      },
      {
        id: "nav-logs",
        category: "Navigation",
        title: "Logs & Audit",
        subtitle: "Historical telemetry & error traces",
        icon: FileClock,
        action: () => { router.push("/logs"); onClose(); },
      },
      {
        id: "nav-sites",
        category: "Navigation",
        title: "Sites & Search Console",
        subtitle: "Manage properties & credentials",
        icon: Globe,
        action: () => { router.push("/sites"); onClose(); },
      },
      {
        id: "nav-provision",
        category: "Navigation",
        title: "Provision New Site",
        subtitle: "Onboard new site / instance wizard",
        icon: Rocket,
        action: () => { router.push("/provision"); onClose(); },
      },
      {
        id: "site-fleet",
        category: "Sites",
        title: "Fleet View (All Sites)",
        subtitle: "Switch context to global fleet aggregate",
        icon: Globe,
        action: () => { router.push("/?site="); onClose(); },
      },
      ...sites.map((s) => ({
        id: `site-${s.slug}`,
        category: "Sites" as const,
        title: `Switch to ${s.name || s.slug}`,
        subtitle: `Filter views to ${s.slug}`,
        icon: Globe,
        action: () => { router.push(`/?site=${encodeURIComponent(s.slug)}`); onClose(); },
      })),
      ...(articles || []).map((a) => ({
        id: `article-${a.id}`,
        category: "Content" as const,
        title: a.title || `Article #${a.id}`,
        subtitle: `${a.site} · ${a.status}`,
        icon: FileText,
        action: () => { router.push(`/articles/${a.id}`); onClose(); },
      })),
      {
        id: "action-theme",
        category: "Actions",
        title: "Toggle Theme (Light / Dark)",
        subtitle: "Switch between Graphite and Chalk themes",
        icon: Sun,
        action: () => {
          const isDark = document.documentElement.classList.contains("dark");
          if (isDark) {
            document.documentElement.classList.remove("dark");
            localStorage.setItem("theme", "light");
            document.cookie = "theme=light; path=/; max-age=31536000";
          } else {
            document.documentElement.classList.add("dark");
            localStorage.setItem("theme", "dark");
            document.cookie = "theme=dark; path=/; max-age=31536000";
          }
          onClose();
        },
      },
    ];
    return list;
  }, [router, sites, articles, onClose]);

  const filtered = useMemo(() => {
    if (!query.trim()) return items;
    const q = query.toLowerCase().trim();
    return items.filter(
      (it) => it.title.toLowerCase().includes(q) || (it.subtitle && it.subtitle.toLowerCase().includes(q))
    );
  }, [items, query]);

  useEffect(() => {
    setSelectedIdx(0);
  }, [query]);

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        if (open) onClose();
      }
      if (!open) return;
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIdx((prev) => (prev + 1 < filtered.length ? prev + 1 : 0));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIdx((prev) => (prev - 1 >= 0 ? prev - 1 : filtered.length - 1));
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (filtered[selectedIdx]) {
          filtered[selectedIdx].action();
        }
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [open, onClose, filtered, selectedIdx]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center p-4 pt-16 sm:pt-24">
      <div
        className="fixed inset-0 bg-black/60 backdrop-blur-sm transition-opacity"
        onClick={onClose}
        aria-hidden
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        className="relative w-full max-w-xl overflow-hidden rounded-xl border border-line bg-card shadow-2xl"
      >
        <div className="flex items-center border-b border-line px-3.5 py-2.5">
          <Search className="mr-2.5 h-4 w-4 shrink-0 text-ink-faint" aria-hidden />
          <input
            type="text"
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Type a command, site name, or page..."
            className="flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-ink-faint"
          />
          <kbd className="hidden rounded border border-line bg-surface px-1.5 py-0.5 font-mono text-[10px] text-ink-faint sm:inline">
            ESC
          </kbd>
          <button
            type="button"
            onClick={onClose}
            className="ml-2 rounded p-1 text-ink-faint hover:text-ink"
            aria-label="Close command palette"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="max-h-80 overflow-y-auto p-2">
          {filtered.length === 0 ? (
            <p className="p-4 text-center text-xs text-ink-faint">No matching commands or pages.</p>
          ) : (
            <ul className="space-y-0.5">
              {filtered.map((item, idx) => {
                const Icon = item.icon;
                const active = idx === selectedIdx;
                return (
                  <li key={item.id}>
                    <button
                      type="button"
                      onClick={item.action}
                      onMouseEnter={() => setSelectedIdx(idx)}
                      className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm transition-colors ${
                        active
                          ? "bg-accent/15 text-accent font-medium"
                          : "text-ink hover:bg-surface/60"
                      }`}
                    >
                      <span className={`flex h-6 w-6 items-center justify-center rounded-md border ${
                        active ? "border-accent/40 bg-accent/20 text-accent" : "border-line bg-surface text-ink-faint"
                      }`}>
                        <Icon className="h-3.5 w-3.5" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-xs font-medium">{item.title}</p>
                        {item.subtitle ? (
                          <p className="truncate text-[11px] text-ink-faint">{item.subtitle}</p>
                        ) : null}
                      </div>
                      <span className="text-[10px] uppercase font-mono tracking-wider text-ink-faint">
                        {item.category}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
