import { engine, type SiteList } from "@/lib/engine";
import { currentInstance } from "@/lib/instances";
import { requireSession } from "@/lib/session";
import { createSiteAction } from "@/actions/instances";
import { Alert, Empty, PageHeader } from "@/lib/ui";
import { PendingButton } from "@/lib/interactive";
import { Globe } from "lucide-react";

export const dynamic = "force-dynamic";

export default async function SitesPage({
  searchParams,
}: {
  searchParams: Promise<{ err?: string; created?: string; updated?: string }>;
}) {
  await requireSession();
  const { err, created, updated } = await searchParams;
  const inst = await currentInstance();

  let sites: SiteList | null = null;
  let loadErr: string | null = null;
  try {
    sites = await engine<SiteList>("/sites");
  } catch (e) {
    loadErr = e instanceof Error ? e.message : String(e);
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="Sites"
        sub={`instance ${inst.name} (${inst.baseUrl}) — create or inspect site rows on this instance`}
      />

      {created ? <Alert tone="success">Site "{created}" created.</Alert> : null}
      {updated ? <Alert tone="info">Site "{updated}" updated.</Alert> : null}
      {err ? <Alert tone="error">{err}</Alert> : null}
      {loadErr ? <Alert tone="warn">Could not load sites: {loadErr}</Alert> : null}

      {sites && sites.sites.length > 0 ? (
        <div className="overflow-x-auto rounded-xl border border-line bg-card">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-line text-left text-xs uppercase tracking-wide text-ink-faint">
              <tr>
                <th className="px-4 py-2.5">Slug</th>
                <th className="px-4 py-2.5">Name</th>
                <th className="px-4 py-2.5">Type</th>
                <th className="px-4 py-2.5">Base URL</th>
              </tr>
            </thead>
            <tbody>
              {sites.sites.map((s) => (
                <tr key={s.id} className="border-t border-line/60 first:border-t-0 hover:bg-surface/40">
                  <td className="px-4 py-2.5 font-mono text-xs text-accent">{s.slug}</td>
                  <td className="px-4 py-2.5 text-ink-dim">{s.name}</td>
                  <td className="px-4 py-2.5 text-xs text-ink-dim">{s.site_type}</td>
                  <td className="px-4 py-2.5 text-xs text-ink-faint">{s.base_url}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty
          icon={Globe}
          title="No sites on this instance"
          hint="Create the first site below — keyword ledger, briefs and articles are always site-scoped."
        />
      )}

      <section className="rounded-xl border border-line bg-card p-5">
        <h2 className="text-sm font-semibold text-ink">Create / upsert a site</h2>
        <form action={createSiteAction} className="mt-4 grid max-w-xl gap-3">
          <label className="text-xs text-ink-dim">
            Slug
            <input
              name="slug"
              required
              className="mt-1 w-full rounded-md border border-line bg-page px-3 py-2 text-sm text-ink placeholder:text-ink-faint/70 focus:border-accent"
              placeholder="my-second-blog"
            />
          </label>
          <label className="text-xs text-ink-dim">
            Name
            <input
              name="name"
              className="mt-1 w-full rounded-md border border-line bg-page px-3 py-2 text-sm text-ink placeholder:text-ink-faint/70 focus:border-accent"
              placeholder="My Second Blog"
            />
          </label>
          <label className="text-xs text-ink-dim">
            Type
            <select
              name="site_type"
              defaultValue="wordpress"
              className="mt-1 w-full rounded-md border border-line bg-page px-3 py-2 text-sm text-ink focus:border-accent"
            >
              <option value="wordpress">wordpress</option>
              <option value="custom">custom</option>
            </select>
          </label>
          <label className="text-xs text-ink-dim">
            Base URL
            <input
              name="base_url"
              required
              className="mt-1 w-full rounded-md border border-line bg-page px-3 py-2 text-sm text-ink placeholder:text-ink-faint/70 focus:border-accent"
              placeholder="https://example.com"
            />
          </label>
          <PendingButton
            pendingLabel="Saving…"
            className="mt-1 w-fit rounded-md bg-accent-strong px-4 py-2 text-sm font-medium text-page transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            Save site (existing slug updates)
          </PendingButton>
        </form>
      </section>
    </div>
  );
}
