import * as React from "react";
import { ChevronDown } from "lucide-react";

export interface SelectProps
  extends React.SelectHTMLAttributes<HTMLSelectElement> {
  leftIcon?: React.ReactNode;
  label?: string;
  helperText?: string;
  error?: string;
}

export const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  (
    {
      className = "",
      leftIcon,
      label,
      helperText,
      error,
      id,
      children,
      ...props
    },
    ref
  ) => {
    const generatedId = React.useId();
    const selectId = id || (label ? generatedId : undefined);

    return (
      <div className="w-full space-y-1.5">
        {label && (
          <label
            htmlFor={selectId}
            className="flex items-center justify-between text-xs font-medium text-ink-dim"
          >
            <span>{label}</span>
            {props.required && (
              <span className="text-[11px] font-normal text-accent">*required</span>
            )}
          </label>
        )}
        <div
          className={`group relative flex items-center rounded-xl border bg-page transition-all duration-150 focus-within:border-accent focus-within:ring-2 focus-within:ring-accent/20 ${
            error
              ? "border-rose-400 dark:border-rose-600 focus-within:border-rose-500"
              : "border-line hover:border-ink-faint/60"
          }`}
        >
          {leftIcon && (
            <div className="pointer-events-none pl-3 text-ink-faint transition-colors group-focus-within:text-accent shrink-0">
              {leftIcon}
            </div>
          )}
          <select
            id={selectId}
            ref={ref}
            className={`flex h-9 w-full appearance-none bg-transparent px-3 py-2 text-xs text-ink focus:outline-none disabled:cursor-not-allowed disabled:opacity-50 pr-8 ${
              leftIcon ? "pl-2" : ""
            } ${className}`}
            {...props}
          >
            {children}
          </select>
          <div className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-ink-faint transition-colors group-focus-within:text-accent">
            <ChevronDown className="h-3.5 w-3.5" aria-hidden />
          </div>
        </div>
        {error ? (
          <p className="text-[11px] text-rose-500 dark:text-rose-400">{error}</p>
        ) : helperText ? (
          <p className="text-[11px] text-ink-faint leading-tight">{helperText}</p>
        ) : null}
      </div>
    );
  }
);
Select.displayName = "Select";
