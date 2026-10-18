import Link from "next/link";
import {
  engine,
  type SearchConsoleSiteStatus,
  type SearchConsoleView,
  type SiteHealth,
  type SiteList,
} from "@/lib/engine";
import { currentInstance } from "@/lib/instances";
import { requireSession } from "@/lib/session";
import { createSiteAction } from "@/actions/instances";
import { Alert, Empty, PageHeader, checkTier } from "@/lib/ui";
import { PendingButton } from "@/lib/interactive";
import { Globe } from "lucide-react";

export const dynamic = "force-dynamic";

/** GSC chip: connected (permission level) / not shared (with the fix hint)
    / unknown when the check itself couldn't run. One engine call answers
    every row. */
function gscCell(gsc: SearchConsoleSiteStatus | undefined, sa: string) {
  if (!gsc) return <span className="text-ink-faint">—</span>;
  if (gsc.connected === true)
    return (
      <span
        className="text-emerald-300"
        title={`${gsc.property}\nvisible to ${sa || "the service account"} (${gsc.permission_level || "unknown level"})`}
      >
        ✓ {gsc.permission_level || "connected"}
      </span>
    );
  if (gsc.connected === null)
    return (
      <span className="text-amber-300" title={gsc.reason || "check failed"}>
        unknown
      </span>
    );
  const noCreds = (gsc.reason || "").includes("GOOGLE_CREDENTIALS");
  return (
    <span
      className={noCreds ? "text-ink-faint" : "text-rose-300"}
      title={
        noCreds
          ? gsc.reason
          : `Share ${gsc.property} with ${sa || "the service account"} in Search Console → Settings → Users and permissions (Restricted is enough for reads)`
      }
    >
      {noCreds ? "no creds" : "not shared"}
    </span>
  );
}

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

  /* Health badges mirror the overview tiering (critical > warn > healthy). */
  let health: (SiteHealth | null)[] = [];
  if (sites) {
    health = await Promise.all(
      sites.sites.map((s) =>
        engine<SiteHealth>(`/sites/${encodeURIComponent(s.slug)}/health`).catch(() => null),
      ),
    );
  }

  /* Search Console connectivity — one sites.list call answers every row. */
  const sc: SearchConsoleView | null = sites
    ? await engine<SearchConsoleView>("/search-console").catch(() => null)
    : null;

  return (
    <div className="space-y-8">
      <PageHeader
        title="Sites"
        sub={`instance ${inst.name} (${inst.baseUrl}) — open a slug for detail, health and read-only settings; create or upsert below`}
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
                <th className="px-4 py-2.5">Publish</th>
                <th className="px-4 py-2.5">Health</th>
                <th className="px-4 py-2.5">GSC</th>
                <th className="px-4 py-2.5">Base URL</th>
              </tr>
            </thead>
            <tbody>
              {sites.sites.map((s, i) => {
                const h = health[i];
                const tier = !h
                  ? "unreachable"
                  : h.critical.length > 0
                    ? "fail"
                    : h.checks.some((c) => checkTier(c) === "warn")
                      ? "watch"
                      : "healthy";
                const tierCls =
                  tier === "healthy"
                    ? "text-emerald-300"
                    : tier === "watch"
                      ? "text-amber-300"
                      : tier === "fail"
                        ? "text-rose-300"
                        : "text-ink-faint";
                const dotCls =
                  tier === "healthy"
                    ? "bg-emerald-400"
                    : tier === "watch"
                      ? "bg-amber-400"
                      : tier === "fail"
                        ? "bg-danger"
                        : "bg-ink-faint";
                return (
                  <tr key={s.id} className="border-t border-line/60 first:border-t-0 hover:bg-surface/40">
                    <td className="px-4 py-2.5 font-mono text-xs">
                      <Link
                        href={`/sites/${encodeURIComponent(s.slug)}`}
                        className="text-accent hover:underline"
                      >
                        {s.slug}
                      </Link>
                    </td>
                    <td className="px-4 py-2.5 text-ink-dim">{s.name}</td>
                    <td className="px-4 py-2.5 text-xs text-ink-dim">{s.site_type}</td>
                    <td className="px-4 py-2.5 text-xs">
                      <span className={s.publish_mode === "auto" ? "text-gold" : "text-ink-faint"}>
                        {s.publish_mode || "draft"}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-xs">
                      <span className={`flex items-center gap-1.5 ${tierCls}`}>
                        <span className={`h-1.5 w-1.5 rounded-full ${dotCls}`} aria-hidden />
                        {tier}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-xs">
                      {gscCell(
                        sc?.sites.find((x) => x.slug === s.slug),
                        sc?.service_account_email ?? "",
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-ink-faint">
                      {s.base_url || "—"}
                    </td>
                  </tr>
                );
              })}
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
