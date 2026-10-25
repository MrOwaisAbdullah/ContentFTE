"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Laptop, Moon, Sun } from "lucide-react";

type ThemeMode = "light" | "dark" | "system";

export function ThemeToggle() {
  const [theme, setTheme] = useState<ThemeMode>("dark");
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setMounted(true);
    const saved = localStorage.getItem("theme") as ThemeMode | null;
    if (saved === "light" || saved === "dark" || saved === "system") {
      setTheme(saved);
      applyTheme(saved);
    } else {
      const isDark = document.documentElement.classList.contains("dark");
      setTheme(isDark ? "dark" : "light");
    }
  }, []);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const applyTheme = (mode: ThemeMode) => {
    if (mode === "system") {
      const systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      if (systemDark) {
        document.documentElement.classList.add("dark");
      } else {
        document.documentElement.classList.remove("dark");
      }
      localStorage.setItem("theme", "system");
      document.cookie = "theme=system; path=/; max-age=31536000";
    } else if (mode === "dark") {
      document.documentElement.classList.add("dark");
      localStorage.setItem("theme", "dark");
      document.cookie = "theme=dark; path=/; max-age=31536000";
    } else {
      document.documentElement.classList.remove("dark");
      localStorage.setItem("theme", "light");
      document.cookie = "theme=light; path=/; max-age=31536000";
    }
  };

  const selectTheme = (mode: ThemeMode) => {
    setTheme(mode);
    applyTheme(mode);
    setOpen(false);
  };

  if (!mounted) {
    return (
      <span className="flex h-8 w-8 items-center justify-center rounded-lg border border-line bg-surface-container text-secondary">
        <Moon className="h-4 w-4" />
      </span>
    );
  }

  return (
    <div className="relative" ref={menuRef}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        title="Theme settings"
        aria-label="Toggle theme menu"
        className="flex h-8 w-8 items-center justify-center rounded-lg border border-line bg-surface-container text-ink hover:border-outline-variant/60 hover:bg-surface-high transition-colors focus-visible:outline-none cursor-pointer"
      >
        {theme === "light" ? (
          <Sun className="h-4 w-4 text-primary-container" />
        ) : theme === "system" ? (
          <Laptop className="h-4 w-4 text-secondary" />
        ) : (
          <Moon className="h-4 w-4 text-secondary" />
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 w-36 rounded-xl border border-line bg-surface-lowest shadow-xl z-50 p-1 font-mono text-[12px] animate-in fade-in zoom-in-95 duration-100">
          <button
            type="button"
            onClick={() => selectTheme("dark")}
            className={`flex w-full items-center justify-between px-2.5 py-1.5 rounded-lg transition-colors cursor-pointer ${
              theme === "dark"
                ? "bg-surface-container text-primary-container font-semibold"
                : "text-secondary hover:text-ink hover:bg-surface-container/60"
            }`}
          >
            <span className="flex items-center gap-2">
              <Moon className="h-3.5 w-3.5" />
              <span>Dark</span>
            </span>
            {theme === "dark" && <Check className="h-3 w-3 text-primary-container" />}
          </button>

          <button
            type="button"
            onClick={() => selectTheme("light")}
            className={`flex w-full items-center justify-between px-2.5 py-1.5 rounded-lg transition-colors cursor-pointer ${
              theme === "light"
                ? "bg-surface-container text-primary-container font-semibold"
                : "text-secondary hover:text-ink hover:bg-surface-container/60"
            }`}
          >
            <span className="flex items-center gap-2">
              <Sun className="h-3.5 w-3.5" />
              <span>Light</span>
            </span>
            {theme === "light" && <Check className="h-3 w-3 text-primary-container" />}
          </button>

          <button
            type="button"
            onClick={() => selectTheme("system")}
            className={`flex w-full items-center justify-between px-2.5 py-1.5 rounded-lg transition-colors cursor-pointer ${
              theme === "system"
                ? "bg-surface-container text-primary-container font-semibold"
                : "text-secondary hover:text-ink hover:bg-surface-container/60"
            }`}
          >
            <span className="flex items-center gap-2">
              <Laptop className="h-3.5 w-3.5" />
              <span>System</span>
            </span>
            {theme === "system" && <Check className="h-3 w-3 text-primary-container" />}
          </button>
        </div>
      )}
    </div>
  );
}
