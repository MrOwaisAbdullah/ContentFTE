import * as React from "react";

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?:
    | "default"
    | "secondary"
    | "outline"
    | "success"
    | "warning"
    | "destructive"
    | "accent"
    | "info";
  dot?: boolean;
}

export function Badge({
  className = "",
  variant = "default",
  dot = false,
  children,
  ...props
}: BadgeProps) {
  const variantStyles = {
    default:
      "bg-surface-container text-ink border-line border font-mono",
    secondary:
      "bg-surface-container/60 text-secondary border-line/60 border font-mono",
    outline:
      "border border-line bg-transparent text-secondary font-mono",
    success:
      "border-emerald-500/40 bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border font-mono shadow-[0_0_8px_rgba(16,185,129,0.12)]",
    warning:
      "border-amber-500/40 bg-amber-500/15 text-amber-600 dark:text-amber-400 border font-mono shadow-[0_0_8px_rgba(245,158,11,0.12)]",
    destructive:
      "border-rose-500/40 bg-rose-500/15 text-rose-600 dark:text-rose-400 border font-mono shadow-[0_0_8px_rgba(239,68,68,0.12)]",
    accent:
      "border-primary-container/40 bg-primary-container/15 text-primary-container border font-mono shadow-[0_0_8px_rgba(242,100,58,0.15)]",
    info:
      "border-sky-500/40 bg-sky-500/15 text-sky-600 dark:text-sky-400 border font-mono shadow-[0_0_8px_rgba(14,165,233,0.12)]",
  };

  const dotStyles = {
    default: "bg-ink-dim",
    secondary: "bg-ink-faint",
    outline: "bg-ink-faint",
    success: "bg-emerald-600 dark:bg-emerald-400",
    warning: "bg-amber-600 dark:bg-amber-400",
    destructive: "bg-rose-600 dark:bg-rose-400",
    accent: "bg-accent",
    info: "bg-sky-600 dark:bg-sky-400",
  };

  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-[11px] font-medium tracking-wide transition-colors ${variantStyles[variant]} ${className}`}
      {...props}
    >
      {dot && (
        <span
          className={`h-1.5 w-1.5 rounded-full shrink-0 ${dotStyles[variant]}`}
          aria-hidden
        />
      )}
      {children}
    </span>
  );
}
