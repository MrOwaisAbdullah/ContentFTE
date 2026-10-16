"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/articles", label: "Content" },
  { href: "/articles/keywords", label: "Keywords" },
  { href: "/articles/research", label: "Research" },
  { href: "/articles/briefs", label: "Briefs" },
];

export function ArticlesTabs() {
  const pathname = usePathname();
  return (
    <nav className="flex gap-1 overflow-x-auto border-b border-line text-sm" aria-label="Article tabs">
      {TABS.map((t) => {
        const active =
          t.href === "/articles"
            ? pathname === "/articles" || /^\/articles\/\d+$/.test(pathname)
            : pathname.startsWith(t.href);
        return (
          <Link
            key={t.href}
            href={t.href}
            aria-current={active ? "page" : undefined}
            className={`-mb-px whitespace-nowrap rounded-t-md border-b-2 px-3 pb-2 pt-1.5 transition-colors ${
              active
                ? "border-accent font-medium text-ink"
                : "border-transparent text-ink-dim hover:text-ink"
            }`}
          >
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}
