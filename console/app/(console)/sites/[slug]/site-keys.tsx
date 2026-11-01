"use client";

import { useActionState, useState } from "react";
import { Check, Copy, KeyRound, ShieldAlert } from "lucide-react";
import { createSiteKeyAction, revokeSiteKeyAction, type KeyCreateResult } from "@/actions/instances";
import type { SiteKey } from "@/lib/engine";
import { KEY_SCOPES } from "@/lib/key-scopes";
import { fmtDateTimeUtc } from "@/lib/format";
import { PendingButton } from "@/lib/interactive";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const SCOPE_HELP: Record<string, string> = {
  read: "Read this site's articles, content and views",
  write: "Submit keywords, generate, edit content, stage images",
  approve: "Approve / reopen articles (subject to the quality gate)",
  publish: "Publish and refresh articles on the live site",
  admin: "Everything above, plus deleting articles and keywords",
};

/**
 * Per-site API keys (plan SEC-03). A site key can only ever act on this one site, with only the
 * scopes ticked here; it is shown ONCE at creation and stored only as a hash.
 */
export function SiteKeys({ slug, keys }: { slug: string; keys: SiteKey[] }) {
  const [created, formAction, pending] = useActionState<KeyCreateResult, FormData>(createSiteKeyAction, {});
  const [copied, setCopied] = useState(false);
  const active = keys.filter((k) => k.active);

  const copy = async () => {
    if (!created.key) return;
    try {
      await navigator.clipboard.writeText(created.key);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard blocked: the key is selectable in the box */
    }
  };

  return (
    <Card>
      <CardHeader className="bg-surface/30 pb-3">
        <div className="flex items-center gap-2">
          <KeyRound className="h-4 w-4 text-accent" aria-hidden />
          <CardTitle className="text-sm font-semibold">Site API keys</CardTitle>
          <Badge variant="outline" className="text-[10px]">
            {active.length} active
          </Badge>
        </div>
        <CardDescription className="text-xs">
          For this site&apos;s own website or integration. A key can only act on <code>{slug}</code> — never on another
          site — and only with the scopes you give it. The console itself uses the instance key, not these.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5 pt-4">
        {created.key ? (
          <div role="status" className="space-y-2 rounded-xl border border-amber-500/40 bg-amber-500/10 p-3.5">
            <p className="flex items-center gap-1.5 text-xs font-semibold text-amber-300">
              <ShieldAlert className="h-3.5 w-3.5" aria-hidden /> Copy this key now — it is shown only once and can&apos;t
              be recovered.
            </p>
            <div className="flex items-center gap-2">
              <input
                readOnly
                value={created.key}
                onFocus={(e) => e.currentTarget.select()}
                aria-label="New API key"
                className="w-full rounded-lg border border-line bg-page px-3 py-2 font-mono text-xs text-ink"
              />
              <button
                type="button"
                onClick={copy}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-2 text-xs font-medium text-ink hover:bg-surface-high"
              >
                {copied ? <Check className="h-3.5 w-3.5" aria-hidden /> : <Copy className="h-3.5 w-3.5" aria-hidden />}
                {copied ? "Copied" : "Copy"}
              </button>
            </div>
            <p className="text-[11px] text-ink-faint">
              Send it as the <code>X-Site-Key</code> header. Scopes: {created.scopes?.join(", ")}.
            </p>
          </div>
        ) : null}
        {created.err ? (
          <p role="alert" className="text-xs text-rose-300">
            {created.err}
          </p>
        ) : null}

        <form action={formAction} className="space-y-3 rounded-xl border border-line bg-surface/20 p-3.5">
          <input type="hidden" name="slug" value={slug} />
          <div className="space-y-1.5">
            <label htmlFor="key-label" className="block text-xs font-medium text-ink-dim">
              What is this key for?
            </label>
            <input
              id="key-label"
              name="label"
              maxLength={120}
              placeholder="e.g. marketing website"
              className="w-full rounded-lg border border-line bg-card px-3 py-2 text-xs text-ink focus:border-accent focus:outline-none"
            />
          </div>
          <fieldset className="space-y-1.5">
            <legend className="text-xs font-medium text-ink-dim">Scopes</legend>
            <div className="grid gap-1.5 sm:grid-cols-2">
              {KEY_SCOPES.map((scope) => (
                <label key={scope} className="flex items-start gap-2 text-xs text-ink">
                  <input
                    type="checkbox"
                    name="scopes"
                    value={scope}
                    defaultChecked={scope === "read"}
                    className="mt-0.5 h-3.5 w-3.5 accent-accent"
                  />
                  <span>
                    <span className="font-mono font-semibold">{scope}</span>
                    <span className="block text-[11px] text-ink-faint">{SCOPE_HELP[scope]}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
          <PendingButton
            pendingLabel="Creating…"
            disabled={pending}
            className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3.5 py-1.5 font-mono text-xs font-semibold text-white hover:brightness-110"
          >
            Create key
          </PendingButton>
        </form>

        {keys.length === 0 ? (
          <p className="text-xs text-ink-faint">No keys yet.</p>
        ) : (
          <ul className="divide-y divide-line/60 rounded-xl border border-line">
            {keys.map((k) => (
              <li key={k.id} className="flex flex-wrap items-center justify-between gap-3 p-3">
                <div className="min-w-0 space-y-0.5">
                  <p className="flex items-center gap-2 text-xs font-medium text-ink">
                    <span className="font-mono">{k.prefix}…</span>
                    {k.label ? <span className="truncate text-ink-dim">{k.label}</span> : null}
                    {!k.active ? (
                      <Badge variant="outline" className="text-[10px] text-rose-300">
                        revoked
                      </Badge>
                    ) : null}
                  </p>
                  <p className="text-[11px] text-ink-faint">
                    {k.scopes.join(" · ")} · created {fmtDateTimeUtc(k.created_at)} · last used{" "}
                    {k.last_used_at ? fmtDateTimeUtc(k.last_used_at) : "never"}
                  </p>
                </div>
                {k.active ? (
                  <form action={revokeSiteKeyAction}>
                    <input type="hidden" name="slug" value={slug} />
                    <input type="hidden" name="key_id" value={k.id} />
                    <PendingButton
                      pendingLabel="Revoking…"
                      confirmTitle="Revoke API key"
                      confirmMessage={`Revoke ${k.prefix}…${k.label ? ` (${k.label})` : ""}? Anything using it stops working immediately.`}
                      confirmButtonLabel="Revoke key"
                      confirmVariant="danger"
                      className="rounded-lg border border-line px-2.5 py-1 text-xs text-ink-dim hover:border-rose-500/30 hover:bg-rose-500/10 hover:text-rose-300"
                    >
                      Revoke
                    </PendingButton>
                  </form>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
