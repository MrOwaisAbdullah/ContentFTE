"use client";

import { useActionState } from "react";
import { loginAction } from "@/actions/auth";

export default function LoginPage() {
  const [state, formAction, pending] = useActionState(loginAction, null);
  return (
    <main className="mx-auto mt-24 max-w-sm rounded-xl border border-slate-800 bg-slate-900 p-8">
      <h1 className="mb-1 text-xl font-semibold">ContentFTE Console</h1>
      <p className="mb-6 text-sm text-slate-400">Operator sign-in</p>
      <form action={formAction} className="space-y-4">
        <input
          type="password"
          name="password"
          autoFocus
          placeholder="Operator password"
          className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-sky-600"
        />
        {state?.error ? (
          <p className="text-sm text-red-400">{state.error}</p>
        ) : null}
        <button
          type="submit"
          disabled={pending}
          className="w-full rounded-md bg-sky-600 px-3 py-2 text-sm font-medium hover:bg-sky-500 disabled:opacity-50"
        >
          {pending ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
