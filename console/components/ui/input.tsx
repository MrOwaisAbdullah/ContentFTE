import * as React from "react";

export interface InputProps
  extends React.InputHTMLAttributes<HTMLInputElement> {
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
  error?: string;
  helperText?: string;
  label?: string;
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  (
    {
      className = "",
      type,
      leftIcon,
      rightIcon,
      error,
      helperText,
      label,
      id,
      ...props
    },
    ref
  ) => {
    const generatedId = React.useId();
    const inputId = id || (label ? generatedId : undefined);

    return (
      <div className="w-full space-y-1.5">
        {label && (
          <label
            htmlFor={inputId}
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
              ? "border-rose-400 dark:border-rose-600 focus-within:border-rose-500 focus-within:ring-rose-500/20"
              : "border-line hover:border-ink-faint/60"
          }`}
        >
          {leftIcon && (
            <div className="pointer-events-none pl-3 text-ink-faint transition-colors group-focus-within:text-accent shrink-0">
              {leftIcon}
            </div>
          )}
          <input
            id={inputId}
            type={type}
            ref={ref}
            className={`flex h-9 w-full bg-transparent px-3 py-2 text-xs text-ink placeholder:text-ink-faint/70 focus:outline-none disabled:cursor-not-allowed disabled:opacity-50 ${
              leftIcon ? "pl-2" : ""
            } ${rightIcon ? "pr-2" : ""} ${className}`}
            {...props}
          />
          {rightIcon && (
            <div className="pr-3 text-ink-faint shrink-0">{rightIcon}</div>
          )}
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
Input.displayName = "Input";
