"use client";

import { Suspense, useActionState, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { loginAction } from "@/actions/auth";
import { Bot, Lock } from "lucide-react";

function LoginPageInner() {
  const [state, formAction, pending] = useActionState(loginAction, null);
  const sp = useSearchParams();
  const [next, setNext] = useState("/");

  useEffect(() => {
    const n = sp.get("next");
    if (n && n.startsWith("/") && !n.startsWith("//")) {
      setNext(n);
    } else {
      // preserve the last visited path if it was saved client-side
      try {
        const last = window.sessionStorage.getItem("console:lastPath");
        if (last && last.startsWith("/") && last !== "/login") setNext(last);
      } catch {}
    }
  }, [sp]);

  return (
    <main className="mx-auto mt-24 max-w-sm rounded-2xl border border-line bg-card p-8 shadow-lg shadow-black/40">
      <div className="mb-6 flex items-center gap-3">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent/10 text-accent" aria-hidden>
          <Bot className="h-5 w-5" />
        </span>
        <div>
          <h1 className="text-lg font-semibold text-ink">ContentFTE Console</h1>
          <p className="text-xs text-ink-faint">Internal operator console — sign in with your operator password.</p>
        </div>
      </div>
      <form action={formAction} className="space-y-4">
        <input type="hidden" name="next" value={next} />
        <label className="block text-xs text-ink-faint">Operator password</label>
        <div className="relative">
          <input
            type="password"
            name="password"
            autoFocus
            placeholder="Operator password"
            aria-label="Operator password"
            className="w-full rounded-md border border-line bg-page px-3 py-2.5 text-sm outline-none focus:border-accent"
          />
          <Lock className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" aria-hidden />
        </div>
        {state?.error ? <p className="text-xs text-rose-300">{state.error}</p> : null}
        <button
          type="submit"
          disabled={pending}
          className="w-full rounded-md bg-accent-strong px-3 py-2.5 text-sm font-medium text-page transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
        >
          {pending ? "Signing in…" : "Sign in"}
        </button>
        <p className="text-[11px] text-ink-faint">
          The password is set in <code className="font-mono">console/.env.local</code> as <code className="font-mono">OPERATOR_PASSWORD</code>.
        </p>
      </form>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<main className="mx-auto mt-24 max-w-sm rounded-2xl border border-line bg-card p-8 shadow-lg shadow-black/40" />}>
      <LoginPageInner />
    </Suspense>
  );
}
