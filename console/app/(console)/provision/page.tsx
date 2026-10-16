"use client";

import { useActionState, useState } from "react";
import { generateEnvAction, type EnvResult } from "@/actions/instances";
import { Alert } from "@/lib/ui";

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

const INPUT =
  "mt-1 w-full rounded-md border border-line bg-page px-3 py-2 text-sm text-ink placeholder:text-ink-faint/70 focus:border-accent";

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
        <h1 className="text-xl font-semibold tracking-tight text-ink">Provision a new instance</h1>
        <p className="mt-1 text-sm text-ink-dim">
          Fill in the site details; the wizard generates the complete env file for the second
          process and optionally creates the site row on the currently selected instance.
        </p>
      </div>

      <form action={formAction} className="grid max-w-xl gap-3 rounded-xl border border-line bg-card p-5">
        <label className="text-xs text-ink-dim">
          Slug (required)
          <input name="slug" required className={INPUT} placeholder="my-second-blog" />
        </label>
        <label className="text-xs text-ink-dim">
          Name
          <input name="name" className={INPUT} placeholder="My Second Blog" />
        </label>
        <label className="text-xs text-ink-dim">
          Site type
          <select name="site_type" defaultValue="wordpress" className={INPUT}>
            <option value="wordpress">wordpress</option>
            <option value="custom">custom</option>
          </select>
        </label>
        <label className="text-xs text-ink-dim">
          Base URL
          <input name="base_url" className={INPUT} placeholder="https://example.com" />
        </label>
        <label className="text-xs text-ink-dim">
          WP username
          <input name="wp_user" className={INPUT} />
        </label>
        <label className="text-xs text-ink-dim">
          WP application password
          <input name="wp_password" type="password" className={INPUT} />
        </label>
        <label className="text-xs text-ink-dim">
          SDK key (leave blank to generate)
          <input name="sdk_key" className={`${INPUT} font-mono`} />
        </label>
        <label className="flex items-center gap-2 text-xs text-ink-dim">
          <input type="checkbox" name="also_create_site" value="1" className="rounded" />
          Also create the site row on the selected instance
        </label>
        <button
          disabled={pending}
          className="mt-1 w-fit rounded-md bg-accent-strong px-4 py-2 text-sm font-medium text-page transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
        >
          {pending ? "Generating…" : "Generate env"}
        </button>
      </form>

      {state.err ? <Alert tone="error">{state.err}</Alert> : null}
      {state.siteCreated ? (
        <Alert tone="success">Site row "{state.siteCreated}" created on the selected instance.</Alert>
      ) : null}

      {state.env ? (
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-ink">Generated .env.{state.slug}</h2>
            <button
              onClick={download}
              className="rounded-md bg-emerald-700 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-emerald-600"
            >
              {downloaded ? "Downloaded ✓" : "Download .env"}
            </button>
          </div>
          <pre className="max-h-96 overflow-auto rounded-xl border border-line bg-page p-4 text-xs text-ink-dim">
            {state.env}
          </pre>
        </section>
      ) : null}

      <section className="space-y-4">
        <h2 className="text-sm font-semibold text-ink">Remaining checklist</h2>
        {CHECKLIST.map((c) => (
          <div key={c.title} className="rounded-xl border border-line bg-card p-4">
            <h3 className="text-sm font-medium text-ink">{c.title}</h3>
            <p className="mt-1 text-xs text-ink-dim">{c.body}</p>
          </div>
        ))}
      </section>
    </div>
  );
}
