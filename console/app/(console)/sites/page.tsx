import { engine, type SiteList } from "@/lib/engine";
import { currentInstance } from "@/lib/instances";
import { requireSession } from "@/lib/session";
import { createSiteAction } from "@/actions/instances";

export const dynamic = "force-dynamic";

export default async function SitesPage({
  searchParams,
}: {
  searchParams: Promise<{ err?: string; created?: string }>;
}) {
  await requireSession();
  const { err, created } = await searchParams;
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
      <div>
        <h1 className="text-lg font-semibold text-white">Sites</h1>
        <p className="mt-1 text-sm text-slate-400">
          Instance <span className="text-slate-200">{inst.name}</span> ({inst.baseUrl}) — create or
          inspect site rows on this instance.
        </p>
      </div>

      {created && (
        <p className="rounded border border-emerald-800 bg-emerald-950/40 px-3 py-2 text-sm text-emerald-300">
          Site &quot;{created}&quot; created.
        </p>
      )}
      {err && (
        <p className="rounded border border-rose-800 bg-rose-950/40 px-3 py-2 text-sm text-rose-300">
          {err}
        </p>
      )}
      {loadErr && (
        <p className="rounded border border-amber-800 bg-amber-950/40 px-3 py-2 text-sm text-amber-300">
          Could not load sites: {loadErr}
        </p>
      )}

      {sites && sites.sites.length > 0 && (
        <table className="w-full text-left text-sm">
          <thead className="text-xs uppercase text-slate-500">
            <tr className="border-b border-slate-800">
              <th className="py-2 pr-4">Slug</th>
              <th className="py-2 pr-4">Name</th>
              <th className="py-2 pr-4">Type</th>
              <th className="py-2">Base URL</th>
            </tr>
          </thead>
          <tbody>
            {sites.sites.map((s) => (
              <tr key={s.id} className="border-b border-slate-900 text-slate-300">
                <td className="py-2 pr-4 font-mono text-xs text-sky-300">{s.slug}</td>
                <td className="py-2 pr-4">{s.name}</td>
                <td className="py-2 pr-4">{s.site_type}</td>
                <td className="py-2 text-xs text-slate-400">{s.base_url}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <section className="rounded border border-slate-800 bg-slate-900/40 p-4">
        <h2 className="text-sm font-semibold text-white">Create / upsert a site</h2>
        <form action={createSiteAction} className="mt-4 grid max-w-xl gap-3">
          <label className="text-xs text-slate-400">
            Slug
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
            Type
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
              required
              className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-200"
              placeholder="https://example.com"
            />
          </label>
          <button className="mt-1 w-fit rounded bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500">
            Create site
          </button>
        </form>
      </section>
    </div>
  );
}
