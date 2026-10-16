"use client";

// Client-side interaction primitives (docs/console-dashboard-plan.md §3):
// pending states on every server-action button, confirm-before-destructive.
// Server pages embed these inside their server-action <form>s — useFormStatus
// binds to that form. The shell's nav / site switcher live in ./shell.tsx.

import { useFormStatus } from "react-dom";
import { Loader2 } from "lucide-react";
import type { MouseEventHandler, ReactNode } from "react";

export function PendingButton({
  children,
  className = "",
  confirmMessage,
  pendingLabel,
  disabled,
}: {
  children: ReactNode;
  className?: string;
  confirmMessage?: string;
  pendingLabel?: string;
  disabled?: boolean;
}) {
  const { pending } = useFormStatus();
  const handleClick: MouseEventHandler<HTMLButtonElement> = (e) => {
    if (confirmMessage && !window.confirm(confirmMessage)) e.preventDefault();
  };
  return (
    <button
      type="submit"
      disabled={pending || disabled}
      aria-busy={pending}
      onClick={handleClick}
      className={className}
    >
      {pending ? (
        <>
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
          <span>{pendingLabel ?? children}</span>
        </>
      ) : (
        children
      )}
    </button>
  );
}
