"use client";

// Client-side interaction primitives:
// pending states on every server-action button, custom themed modal confirm before destructive actions.

import { useEffect, useRef, useState } from "react";
import { useFormStatus } from "react-dom";
import { AlertTriangle, Loader2, X } from "lucide-react";
import type { MouseEventHandler, ReactNode } from "react";

export function PendingButton({
  children,
  className = "",
  confirmMessage,
  confirmTitle = "Confirm Action",
  confirmButtonLabel = "Confirm",
  cancelButtonLabel = "Cancel",
  confirmVariant = "danger",
  pendingLabel,
  disabled,
  leftIcon,
  title,
  name,
  value,
  "aria-label": ariaLabel,
}: {
  children: ReactNode;
  className?: string;
  confirmMessage?: string;
  confirmTitle?: string;
  confirmButtonLabel?: string;
  cancelButtonLabel?: string;
  confirmVariant?: "danger" | "primary";
  pendingLabel?: string;
  disabled?: boolean;
  leftIcon?: ReactNode;
  title?: string;
  name?: string;
  value?: string;
  "aria-label"?: string;
}) {
  const { pending } = useFormStatus();
  const [showConfirm, setShowConfirm] = useState(false);
  const btnRef = useRef<HTMLButtonElement>(null);
  const confirmBtnRef = useRef<HTMLButtonElement>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!showConfirm) return;
    previouslyFocused.current = document.activeElement as HTMLElement | null;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        setShowConfirm(false);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    // focus the confirm button
    setTimeout(() => confirmBtnRef.current?.focus(), 0);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      previouslyFocused.current?.focus?.();
    };
  }, [showConfirm]);

  const handleClick: MouseEventHandler<HTMLButtonElement> = (e) => {
    if (confirmMessage) {
      e.preventDefault();
      setShowConfirm(true);
    }
  };

  const handleConfirm = () => {
    setShowConfirm(false);
    if (btnRef.current?.form) {
      // Dispatch submit request programmatically
      btnRef.current.form.requestSubmit(btnRef.current);
    }
  };

  return (
    <>
      <button
        ref={btnRef}
        type="submit"
        name={name}
        value={value}
        disabled={pending || disabled}
        aria-busy={pending}
        aria-label={ariaLabel}
        title={title}
        onClick={handleClick}
        className={className}
      >
        {pending ? (
          <>
            <Loader2 className="h-3.5 w-3.5 animate-spin shrink-0" aria-hidden />
            <span>{pendingLabel ?? children}</span>
          </>
        ) : (
          <>
            {leftIcon}
            {children}
          </>
        )}
      </button>

      {/* Custom Themed Confirmation Modal */}
      {showConfirm && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
          <div
            className="fixed inset-0 bg-black/70 backdrop-blur-sm transition-opacity animate-in fade-in duration-150"
            onClick={() => setShowConfirm(false)}
            aria-hidden
          />
          <div
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="confirm-modal-title"
            aria-describedby="confirm-modal-desc"
            className="relative w-full max-w-md rounded-2xl border border-line bg-surface-lowest p-6 shadow-2xl animate-in zoom-in-95 duration-150 z-10"
          >
            {/* Header Icon & Close */}
            <div className="flex items-start justify-between gap-4">
              <div
                className={`flex h-10 w-10 items-center justify-center rounded-xl border ${
                  confirmVariant === "danger"
                    ? "border-rose-500/30 bg-rose-500/10 text-rose-400"
                    : "border-primary-container/30 bg-primary-container/10 text-primary-container"
                }`}
              >
                <AlertTriangle className="h-5 w-5" />
              </div>
              <button
                type="button"
                onClick={() => setShowConfirm(false)}
                className="rounded-lg p-1 text-secondary hover:bg-surface-container hover:text-ink transition-colors"
                aria-label="Close dialog"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* Title & Description */}
            <div className="mt-4 space-y-2">
              <h3 id="confirm-modal-title" className="text-base font-semibold text-ink tracking-tight font-headline">
                {confirmTitle}
              </h3>
              <p id="confirm-modal-desc" className="text-xs text-secondary leading-relaxed">
                {confirmMessage}
              </p>
            </div>

            {/* Actions */}
            <div className="mt-6 flex items-center justify-end gap-2.5">
              <button
                type="button"
                onClick={() => setShowConfirm(false)}
                className="px-3.5 py-1.5 rounded-lg border border-line bg-surface-container hover:bg-surface-high text-xs font-medium text-secondary hover:text-ink transition-colors cursor-pointer"
              >
                {cancelButtonLabel}
              </button>
              <button
                ref={confirmBtnRef}
                type="button"
                onClick={handleConfirm}
                className={`px-4 py-1.5 rounded-lg text-xs font-semibold text-white transition-all cursor-pointer shadow-xs ${
                  confirmVariant === "danger"
                    ? "bg-rose-600 hover:bg-rose-500 active:scale-[0.98]"
                    : "bg-primary-container hover:brightness-110 active:scale-[0.98]"
                }`}
              >
                {confirmButtonLabel}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
