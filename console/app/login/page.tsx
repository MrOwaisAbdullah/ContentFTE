"use client";

import { useActionState } from "react";
import { loginAction } from "@/actions/auth";
import { Bot } from "lucide-react";

export default function LoginPage() {
  const [state, formAction, pending] = useActionState(loginAction, null);
  return (
    <main className="mx-auto mt-24 max-w-sm rounded-2xl border border-line bg-card p-8 shadow-lg shadow-black/40">
      <div className="mb-6 flex items-center gap-3">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent/10 text-accent" aria-hidden>
          <Bot className="h-5 w-5" />
        </span>
        <div>
          <h1 className="text-lg font-semibold text-ink">ContentFTE Console</h1>
          <p className="text-xs text-ink-faint">Operator sign-in</p>
        </div>
      </div>
      <form action={formAction} className="space-y-4">
        <input
          type="password"
          name="password"
          autoFocus
          placeholder="Operator password"
          aria-label="Operator password"
          className="w-full rounded-md border border-line bg-page px-3 py-2.5 text-sm outline-none focus:border-accent"
        />
        {state?.error ? <p className="text-xs text-rose-300">{state.error}</p> : null}
        <button
          type="submit"
          disabled={pending}
          className="w-full rounded-md bg-accent-strong px-3 py-2.5 text-sm font-medium text-page transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
        >
          {pending ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
