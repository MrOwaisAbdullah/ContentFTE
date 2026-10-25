"use client";

import { useState, useMemo } from "react";
import Link from "next/link";
import { Pill, fmtCost, fmtDate, fmtScore } from "@/lib/ui";
import { type ArticleListItem } from "@/lib/engine";
import { ArrowUpDown, ChevronLeft, ChevronRight, ExternalLink, Search } from "lucide-react";

export function ArticlesTable({
  articles,
  activeSite,
  initialStatus = "",
}: {
  articles: ArticleListItem[];
  activeSite?: string;
  initialStatus?: string;
}) {
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState(initialStatus);
  const [sortBy, setSortBy] = useState<"date" | "quality" | "cost" | "title">("date");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  const statuses = useMemo(() => {
    const counts: Record<string, number> = { all: articles.length };
    for (const a of articles) {
      counts[a.status] = (counts[a.status] || 0) + 1;
    }
    return [
      { key: "", label: "All", count: counts.all || 0 },
      { key: "published", label: "Published", count: counts["published"] || 0 },
      { key: "approved", label: "Approved", count: counts["approved"] || 0 },
      { key: "generated", label: "Generated", count: counts["generated"] || 0 },
      { key: "needs_review", label: "Needs Review", count: counts["needs_review"] || 0 },
      { key: "briefed", label: "Briefed", count: counts["briefed"] || 0 },
    ];
  }, [articles]);

  const filtered = useMemo(() => {
    let result = articles;
    if (statusFilter) {
      result = result.filter((a) => a.status === statusFilter);
    }
    if (query.trim()) {
      const q = query.toLowerCase().trim();
      result = result.filter(
        (a) =>
          (a.title && a.title.toLowerCase().includes(q)) ||
          (a.slug && a.slug.toLowerCase().includes(q)) ||
          (a.summary && a.summary.toLowerCase().includes(q)) ||
          (a.site_slug && a.site_slug.toLowerCase().includes(q))
      );
    }

    return [...result].sort((a, b) => {
      let cmp = 0;
      if (sortBy === "date") {
        cmp = (a.created_at || "").localeCompare(b.created_at || "");
      } else if (sortBy === "quality") {
        cmp = (Number(a.quality) || 0) - (Number(b.quality) || 0);
      } else if (sortBy === "cost") {
        cmp = (Number(a.cost_usd) || 0) - (Number(b.cost_usd) || 0);
      } else if (sortBy === "title") {
        cmp = (a.title || "").localeCompare(b.title || "");
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [articles, statusFilter, query, sortBy, sortDir]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const currentPage = Math.min(page, totalPages);
  const paged = filtered.slice((currentPage - 1) * pageSize, currentPage * pageSize);

  const toggleSort = (col: typeof sortBy) => {
    if (sortBy === col) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortBy(col);
      setSortDir("desc");
    }
  };

  const scoreBadge = (score: number | null | undefined) => {
    if (score == null || !Number.isFinite(score)) {
      return <span className="text-[11px] font-mono text-ink-faint" title="No eval recorded for this run">Not scored</span>;
    }
    const n = Math.round(score);
    if (n >= 90) {
      return (
        <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 font-mono text-[11px] font-semibold text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-300">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-600 dark:bg-emerald-400" />
          {n}/100
        </span>
      );
    }
    if (n >= 80) {
      return (
        <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 font-mono text-[11px] font-semibold text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-300">
          <span className="h-1.5 w-1.5 rounded-full bg-amber-600 dark:bg-amber-400" />
          {n}/100
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-rose-200 bg-rose-50 px-2 py-0.5 font-mono text-[11px] font-semibold text-rose-800 dark:border-rose-900/60 dark:bg-rose-950/40 dark:text-rose-300">
        <span className="h-1.5 w-1.5 rounded-full bg-rose-600 dark:bg-rose-400" />
        {n}/100
      </span>
    );
  };

  return (
    <div className="space-y-4">
      {/* Top Filter and Search Bar */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          {statuses.map((s) => (
            <button
              key={s.key}
              type="button"
              onClick={() => { setStatusFilter(s.key); setPage(1); }}
              className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 font-medium transition-colors ${
                statusFilter === s.key
                  ? "border-accent bg-accent text-white"
                  : "border-line bg-card text-ink-dim hover:border-ink-faint hover:text-ink"
              }`}
            >
              {s.label}
              <span className={`text-[10px] ${statusFilter === s.key ? "text-white/80" : "text-ink-faint"}`}>
                {s.count}
              </span>
            </button>
          ))}
        </div>

        <div className="relative min-w-[220px]">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-faint" />
          <input
            type="text"
            value={query}
            onChange={(e) => { setQuery(e.target.value); setPage(1); }}
            placeholder="Search articles or topics..."
            className="w-full rounded-md border border-line bg-card py-1.5 pl-8 pr-3 text-xs text-ink placeholder:text-ink-faint focus:border-accent focus:outline-none"
          />
        </div>
      </div>

      {/* Main Table */}
      <div className="overflow-hidden rounded-lg border border-line bg-card shadow-sm">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-line bg-surface/30 font-semibold text-ink-faint">
              <tr>
                <th className="px-4 py-3">
                  <button
                    type="button"
                    onClick={() => toggleSort("title")}
                    className="inline-flex items-center gap-1 hover:text-ink"
                  >
                    Article & Title
                    <ArrowUpDown className="h-3 w-3" />
                  </button>
                </th>
                <th className="px-3 py-3">Site</th>
                <th className="px-3 py-3">Status</th>
                <th className="px-3 py-3 text-center">
                  <button
                    type="button"
                    onClick={() => toggleSort("quality")}
                    className="inline-flex items-center gap-1 hover:text-ink"
                  >
                    Quality Score
                    <ArrowUpDown className="h-3 w-3" />
                  </button>
                </th>
                <th className="hidden px-3 py-3 text-right sm:table-cell">
                  <button
                    type="button"
                    onClick={() => toggleSort("cost")}
                    className="inline-flex items-center gap-1 hover:text-ink"
                  >
                    Cost
                    <ArrowUpDown className="h-3 w-3" />
                  </button>
                </th>
                <th className="px-3 py-3 text-right">
                  <button
                    type="button"
                    onClick={() => toggleSort("date")}
                    className="inline-flex items-center gap-1 hover:text-ink"
                  >
                    Created
                    <ArrowUpDown className="h-3 w-3" />
                  </button>
                </th>
                <th className="px-4 py-3 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line/50">
              {paged.length === 0 ? (
                <tr>
                  <td colSpan={7} className="p-8 text-center text-ink-faint">
                    No articles match your search or filter.
                  </td>
                </tr>
              ) : (
                paged.map((a) => (
                  <tr key={a.id} className="transition-colors hover:bg-surface/40">
                    <td className="px-4 py-3 max-w-sm">
                      <Link
                        href={`/articles/${a.id}`}
                        className="font-medium text-ink transition-colors hover:text-accent block leading-snug"
                      >
                        {a.title || `#${a.id}`}
                      </Link>
                      <p className="mt-0.5 truncate text-[11px] text-ink-faint" title={a.summary || a.slug}>
                        {a.summary || a.slug}
                      </p>
                    </td>
                    <td className="px-3 py-3 font-mono text-ink-faint whitespace-nowrap">
                      {a.site_slug}
                    </td>
                    <td className="px-3 py-3 whitespace-nowrap">
                      <Pill status={a.status} />
                    </td>
                    <td className="px-3 py-3 text-center whitespace-nowrap">
                      {scoreBadge(a.quality)}
                    </td>
                    <td className="hidden px-3 py-3 text-right font-mono text-ink-faint sm:table-cell whitespace-nowrap">
                      <span title={a.cost_usd ? undefined : "No cost recorded for this run"}>{fmtCost(a.cost_usd)}</span>
                    </td>
                    <td className="px-3 py-3 text-right text-ink-faint whitespace-nowrap">
                      {fmtDate(a.created_at)}
                    </td>
                    <td className="px-4 py-3 text-right whitespace-nowrap">
                      <Link
                        href={`/articles/${a.id}`}
                        className="inline-flex items-center gap-1 rounded border border-line bg-surface/60 px-2.5 py-1 text-xs font-medium text-ink-dim transition-colors hover:border-accent hover:text-accent"
                      >
                        {a.status === "generated" || a.status === "needs_review" ? "Review" : "Open"}
                        <ChevronRight className="h-3 w-3" />
                      </Link>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Bar */}
        {filtered.length > 0 ? (
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line bg-surface/20 px-4 py-2.5 text-xs text-ink-faint">
            <div className="flex items-center gap-2">
              <span>Showing {(currentPage - 1) * pageSize + 1}–{Math.min(currentPage * pageSize, filtered.length)} of {filtered.length} posts</span>
              <span className="text-line">|</span>
              <label className="flex items-center gap-1">
                <span>Per page:</span>
                <select
                  value={pageSize}
                  onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}
                  className="rounded border border-line bg-card px-1.5 py-0.5 text-ink focus:outline-none"
                >
                  <option value={25}>25</option>
                  <option value={50}>50</option>
                  <option value={100}>100</option>
                </select>
              </label>
            </div>

            <div className="flex items-center gap-1">
              <button
                type="button"
                disabled={currentPage <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                className="flex h-7 w-7 items-center justify-center rounded border border-line bg-card disabled:opacity-40"
              >
                <ChevronLeft className="h-3.5 w-3.5" />
              </button>
              <span className="px-2 font-mono">
                {currentPage} / {totalPages}
              </span>
              <button
                type="button"
                disabled={currentPage >= totalPages}
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                className="flex h-7 w-7 items-center justify-center rounded border border-line bg-card disabled:opacity-40"
              >
                <ChevronRight className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
