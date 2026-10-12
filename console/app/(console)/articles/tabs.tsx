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
    <nav className="flex gap-5 border-b border-slate-800 text-sm">
      {TABS.map((t) => {
        const active =
          t.href === "/articles"
            ? pathname === "/articles" || /^\/articles\/\d+$/.test(pathname)
            : pathname.startsWith(t.href);
        return (
          <Link
            key={t.href}
            href={t.href}
            className={`-mb-px border-b-2 pb-2 ${
              active
                ? "border-sky-500 text-white"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}
