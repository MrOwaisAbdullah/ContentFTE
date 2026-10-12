"use client";

import { useActionState, useState } from "react";
import { generateEnvAction, type EnvResult } from "@/actions/instances";

const CHECKLIST = [
  {
    title: "1. Neon project #2 (free tier)",
    body: "Create a second Neon project, copy its pooled connection string. Paste it into DATABASE_URL in the generated .env.",
  },
  {
    title: "2. Provider accounts (free tier, separate from site #1)",
    body: "New Gemini API key, new OpenRouter key, new Cloudflare Workers account (account id + API token), Tavily key. Paste each into the generated .env.",
  },
  {
    title: "3. WordPress site",
    body: "Set up the WP site; in WP admin create an Application Password for the console's WP_USERNAME. Paste it as WP_APP_PASSWORD.",
  },
  {
    title: "4. Start the second process",
    body: "From a second checkout (or the same repo) with the generated .env: uvicorn main:app --port 8001. Add it to this console's CONSOLE_INSTANCES and switch to it.",
  },
];

export default function ProvisionPage() {
  const [state, formAction, pending] = useActionState<EnvResult, FormData>(
    generateEnvAction,
    {},
  );
  const [downloaded, setDownloaded] = useState(false);

  function download() {
    if (!state.env) return;
    const blob = new Blob([state.env], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `.env.${state.slug || "instance"}`;
    a.click();
    URL.revokeObjectURL(url);
    setDownloaded(true);
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-lg font-semibold text-white">Provision a new instance</h1>
        <p className="mt-1 text-sm text-slate-400">
          Fill in the site details; the wizard generates the complete env file for the second
          process and optionally creates the site row on the currently selected instance.
        </p>
      </div>

      <form action={formAction} className="grid max-w-xl gap-3 rounded border border-slate-800 bg-slate-900/40 p-4">
        <label className="text-xs text-slate-400">
          Slug (required)
          <input
            name="slug"
            required
            className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-200"
            placeholder="my-second-blog"
          />
        </label>
        <label className="text-xs text-slate-400">
          Name
          <input
            name="name"
            className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-200"
            placeholder="My Second Blog"
          />
        </label>
        <label className="text-xs text-slate-400">
          Site type
          <select
            name="site_type"
            defaultValue="wordpress"
            className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-200"
          >
            <option value="wordpress">wordpress</option>
            <option value="custom">custom</option>
          </select>
        </label>
        <label className="text-xs text-slate-400">
          Base URL
          <input
            name="base_url"
            className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-200"
            placeholder="https://example.com"
          />
        </label>
        <label className="text-xs text-slate-400">
          WP username
          <input
            name="wp_user"
            className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-200"
          />
        </label>
        <label className="text-xs text-slate-400">
          WP application password
          <input
            name="wp_password"
            type="password"
            className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-200"
          />
        </label>
        <label className="text-xs text-slate-400">
          SDK key (leave blank to generate)
          <input
            name="sdk_key"
            className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 font-mono text-sm text-slate-200"
          />
        </label>
        <label className="flex items-center gap-2 text-xs text-slate-400">
          <input type="checkbox" name="also_create_site" value="1" className="rounded" />
          Also create the site row on the selected instance
        </label>
        <button
          disabled={pending}
          className="mt-1 w-fit rounded bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50"
        >
          {pending ? "Generating…" : "Generate env"}
        </button>
      </form>

      {state.err && (
        <p className="rounded border border-rose-800 bg-rose-950/40 px-3 py-2 text-sm text-rose-300">
          {state.err}
        </p>
      )}
      {state.siteCreated && (
        <p className="rounded border border-emerald-800 bg-emerald-950/40 px-3 py-2 text-sm text-emerald-300">
          Site row &quot;{state.siteCreated}&quot; created on the selected instance.
        </p>
      )}

      {state.env && (
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-white">
              Generated .env.{state.slug}
            </h2>
            <div className="flex gap-3">
              <button
                onClick={download}
                className="rounded bg-emerald-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-600"
              >
                {downloaded ? "Downloaded" : "Download .env"}
              </button>
            </div>
          </div>
          <pre className="max-h-96 overflow-auto rounded border border-slate-800 bg-slate-950 p-4 text-xs text-slate-300">
            {state.env}
          </pre>
        </section>
      )}

      <section className="space-y-4">
        <h2 className="text-sm font-semibold text-white">Remaining checklist</h2>
        {CHECKLIST.map((c) => (
          <div key={c.title} className="rounded border border-slate-800 bg-slate-900/40 p-4">
            <h3 className="text-sm font-medium text-slate-200">{c.title}</h3>
            <p className="mt-1 text-xs text-slate-400">{c.body}</p>
          </div>
        ))}
      </section>
    </div>
  );
}
