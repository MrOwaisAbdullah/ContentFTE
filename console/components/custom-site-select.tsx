"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Check, ChevronDown, ExternalLink, Globe, Layers, Search, X } from "lucide-react";

export type SiteOption = {
  slug: string;
  name: string;
};

interface CustomSiteSelectProps {
  sites: SiteOption[];
  currentSite: string;
  onSelect: (slug: string) => void;
  className?: string;
}

export function CustomSiteSelect({
  sites,
  currentSite,
  onSelect,
  className = "",
}: CustomSiteSelectProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const dropdownRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  const selectedSite = sites.find((s) => s.slug === currentSite);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && open) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  useEffect(() => {
    if (open) {
      setSearch("");
    }
  }, [open]);

  const filteredSites = sites.filter((s) => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return s.slug.toLowerCase().includes(q) || (s.name && s.name.toLowerCase().includes(q));
  });

  const handleSelect = (slug: string) => {
    onSelect(slug);
    setOpen(false);
  };

  return (
    <div className={`relative flex items-center gap-1.5 ${className}`} ref={dropdownRef}>
      {/* Trigger Button */}
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex items-center gap-2 h-8 px-2.5 rounded-lg bg-surface-container border border-outline-variant/30 hover:border-outline-variant/60 hover:bg-surface-high text-xs font-mono transition-colors focus:outline-none focus:ring-1 focus:ring-primary-container cursor-pointer select-none"
      >
        <span className="text-secondary/70">site:</span>
        <div className="flex items-center gap-1.5 font-medium text-ink max-w-[160px] truncate">
          {selectedSite ? (
            <>
              <Globe className="w-3.5 h-3.5 text-primary-container shrink-0" />
              <span className="truncate">{selectedSite.name || selectedSite.slug}</span>
            </>
          ) : (
            <>
              <Layers className="w-3.5 h-3.5 text-secondary shrink-0" />
              <span className="truncate">All Sites (Fleet)</span>
            </>
          )}
        </div>
        <ChevronDown
          className={`w-3.5 h-3.5 text-secondary transition-transform duration-150 shrink-0 ${
            open ? "rotate-180 text-primary-container" : ""
          }`}
        />
      </button>

      {/* Jump to site config button */}
      {currentSite && (
        <Link
          href={`/sites/${encodeURIComponent(currentSite)}`}
          className="p-1.5 rounded-lg text-secondary hover:text-primary-container hover:bg-surface-container transition-colors"
          title="Open site configuration"
        >
          <ExternalLink className="w-3.5 h-3.5" />
        </Link>
      )}

      {/* Dropdown Floating Panel */}
      {open && (
        <div className="absolute left-0 top-full mt-2 w-72 rounded-xl border border-line bg-surface-lowest shadow-2xl z-50 p-1.5 font-mono text-[12px] animate-in fade-in zoom-in-95 duration-100">
          {/* Search Input when > 3 sites */}
          {sites.length > 2 && (
            <div className="flex items-center gap-2 px-2.5 py-1.5 mb-1 rounded-lg bg-surface-container/60 border border-line">
              <Search className="w-3.5 h-3.5 text-secondary shrink-0" />
              <input
                ref={searchInputRef}
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Filter sites..."
                className="w-full bg-transparent text-xs text-ink placeholder:text-secondary/60 !outline-none !border-none !ring-0 focus:!outline-none focus:!border-none focus:!ring-0 focus-visible:!outline-none focus-visible:!ring-0 shadow-none"
                style={{ outline: "none", boxShadow: "none", border: "none" }}
              />
              {search && (
                <button
                  type="button"
                  onClick={() => setSearch("")}
                  className="text-secondary hover:text-ink p-0.5"
                >
                  <X className="w-3 h-3" />
                </button>
              )}
            </div>
          )}

          {/* All Sites Option */}
          <button
            type="button"
            onClick={() => handleSelect("")}
            className={`flex w-full items-center justify-between px-2.5 py-2 rounded-lg transition-colors cursor-pointer text-left ${
              !currentSite
                ? "bg-primary-container/10 border border-primary-container/30 text-primary-container font-semibold"
                : "text-secondary hover:text-ink hover:bg-surface-container/60"
            }`}
          >
            <div className="flex items-center gap-2 min-w-0">
              <div
                className={`p-1 rounded-md border ${
                  !currentSite
                    ? "border-primary-container/30 bg-primary-container/20 text-primary-container"
                    : "border-line bg-surface-container text-secondary"
                }`}
              >
                <Layers className="w-3.5 h-3.5" />
              </div>
              <div className="min-w-0">
                <p className="font-medium text-xs leading-none">All Sites (Fleet)</p>
                <p className="text-[10px] text-secondary/70 mt-0.5">Aggregate fleet view ({sites.length} sites)</p>
              </div>
            </div>
            {!currentSite && <Check className="w-3.5 h-3.5 text-primary-container shrink-0" />}
          </button>

          <div className="my-1 border-t border-line" />

          {/* Individual Sites List */}
          <div className="max-h-56 overflow-y-auto space-y-0.5 custom-scroll">
            {filteredSites.length === 0 ? (
              <p className="px-3 py-3 text-center text-xs text-secondary/60 font-sans">
                No sites found matching &quot;{search}&quot;
              </p>
            ) : (
              filteredSites.map((site) => {
                const isSelected = site.slug === currentSite;
                return (
                  <button
                    key={site.slug}
                    type="button"
                    onClick={() => handleSelect(site.slug)}
                    className={`flex w-full items-center justify-between px-2.5 py-2 rounded-lg transition-colors cursor-pointer text-left ${
                      isSelected
                        ? "bg-primary-container/10 border border-primary-container/30 text-primary-container font-semibold"
                        : "text-secondary hover:text-ink hover:bg-surface-container/60"
                    }`}
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <div
                        className={`p-1 rounded-md border ${
                          isSelected
                            ? "border-primary-container/30 bg-primary-container/20 text-primary-container"
                            : "border-line bg-surface-container text-secondary"
                        }`}
                      >
                        <Globe className="w-3.5 h-3.5" />
                      </div>
                      <div className="min-w-0">
                        <p className="font-medium text-xs truncate leading-none">
                          {site.name || site.slug}
                        </p>
                        <p className="text-[10px] text-secondary/70 font-mono mt-0.5 truncate">
                          {site.slug}
                        </p>
                      </div>
                    </div>
                    {isSelected && (
                      <Check className="w-3.5 h-3.5 text-primary-container shrink-0" />
                    )}
                  </button>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
