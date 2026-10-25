import * as React from "react";
import { Loader2 } from "lucide-react";

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "destructive" | "outline" | "secondary" | "ghost" | "link";
  size?: "default" | "sm" | "lg" | "icon";
  isLoading?: boolean;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
}

export const buttonVariants = {
  base: "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl text-xs font-medium transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50 focus-visible:ring-offset-1 disabled:pointer-events-none disabled:opacity-50 active:scale-[0.98]",
  variants: {
    default: "bg-accent-strong text-white shadow-sm hover:bg-accent hover:shadow",
    destructive:
      "bg-rose-500/10 text-rose-500 border border-rose-500/20 hover:bg-rose-500 hover:text-white dark:bg-rose-950/40 dark:text-rose-400 dark:border-rose-900/60 dark:hover:bg-rose-600 dark:hover:text-white",
    outline:
      "border border-line bg-card text-ink hover:bg-surface hover:text-ink shadow-sm",
    secondary:
      "bg-surface text-ink hover:bg-surface/80 border border-line/60",
    ghost: "text-ink-dim hover:bg-surface hover:text-ink",
    link: "text-accent underline-offset-4 hover:underline p-0 h-auto",
  },
  sizes: {
    default: "h-9 px-4 py-2",
    sm: "h-8 rounded-lg px-3 text-xs",
    lg: "h-10 rounded-xl px-6 text-sm",
    icon: "h-8 w-8 rounded-lg p-0",
  },
};

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      className = "",
      variant = "default",
      size = "default",
      isLoading = false,
      leftIcon,
      rightIcon,
      children,
      disabled,
      ...props
    },
    ref
  ) => {
    return (
      <button
        ref={ref}
        disabled={disabled || isLoading}
        className={`${buttonVariants.base} ${buttonVariants.variants[variant]} ${buttonVariants.sizes[size]} ${className}`}
        {...props}
      >
        {isLoading ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin shrink-0" aria-hidden />
        ) : (
          leftIcon
        )}
        {children}
        {!isLoading && rightIcon}
      </button>
    );
  }
);
Button.displayName = "Button";
