import { requireSession } from "@/lib/session";
import { currentInstance, registry } from "@/lib/instances";
import { removeInstanceAction, saveInstanceAction, switchInstanceAction } from "@/actions/instances";

export const dynamic = "force-dynamic";

export default async function InstancesPage({
  searchParams,
}: {
  searchParams: Promise<{ err?: string; saved?: string; removed?: string }>;
}) {
  await requireSession();
  const { err, saved, removed } = await searchParams;
  const instances = await registry();
  const current = await currentInstance();

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-lg font-semibold">Instances</h1>
        <p className="mt-1 text-sm text-slate-400">
          Every engine this console can manage. <span className="text-slate-200">env</span> entries
          come from <code className="text-xs">CONSOLE_INSTANCES</code> (edit the env to change
          them); <span className="text-slate-200">file</span> entries are stored in{" "}
          <code className="text-xs">instances.json</code> and managed right here.
        </p>
      </div>

      {saved && (
        <p className="rounded border border-emerald-800 bg-emerald-950/40 px-3 py-2 text-sm text-emerald-300">
          Instance &quot;{saved}&quot; saved.
        </p>
      )}
      {removed && (
        <p className="rounded border border-emerald-800 bg-emerald-950/40 px-3 py-2 text-sm text-emerald-300">
          Instance &quot;{removed}&quot; removed.
        </p>
      )}
      {err && (
        <p className="rounded border border-rose-800 bg-rose-950/40 px-3 py-2 text-sm text-rose-300">
          {err}
        </p>
      )}

      <div className="overflow-x-auto rounded-lg border border-slate-800">
        <table className="w-full text-sm">
          <thead className="bg-slate-900 text-left text-xs text-slate-400">
            <tr>
              <th className="px-4 py-2">Name</th>
              <th className="px-4 py-2">Base URL</th>
              <th className="px-4 py-2">API key</th>
              <th className="px-4 py-2">Origin</th>
              <th className="px-4 py-2">Selected</th>
              <th className="px-4 py-2" />
            </tr>
          </thead>
          <tbody>
            {instances.map((i) => (
              <tr key={i.name} className="border-t border-slate-800/80">
                <td className="px-4 py-2 font-medium text-slate-200">{i.name}</td>
                <td className="px-4 py-2 text-xs text-slate-400">{i.baseUrl}</td>
                <td className="px-4 py-2 text-xs text-slate-500">
                  {i.apiKey ? "••• set" : "—"}
                </td>
                <td className="px-4 py-2 text-xs">
                  <span className={i.origin === "env" ? "text-amber-300" : "text-sky-300"}>
                    {i.origin}
                  </span>
                </td>
                <td className="px-4 py-2 text-xs">
                  {i.name === current.name ? (
                    <span className="text-emerald-400">active</span>
                  ) : (
                    <form action={switchInstanceAction} className="inline">
                      <input type="hidden" name="instance" value={i.name} />
                      <button className="text-xs text-sky-400 hover:underline">switch →</button>
                    </form>
                  )}
                </td>
                <td className="px-4 py-2 text-right">
                  {i.origin === "file" ? (
                    <form action={removeInstanceAction} className="inline">
                      <input type="hidden" name="name" value={i.name} />
                      <button className="text-xs text-rose-400 hover:underline">remove</button>
                    </form>
                  ) : (
                    <span className="text-xs text-slate-600">env-locked</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <section className="rounded border border-slate-800 bg-slate-900/40 p-4">
        <h2 className="text-sm font-semibold text-white">Add / edit a file instance</h2>
        <form action={saveInstanceAction} className="mt-4 grid max-w-xl gap-3">
          <label className="text-xs text-slate-400">
            Name (unique)
            <input
              name="name"
              required
              className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-200"
              placeholder="site2"
            />
          </label>
          <label className="text-xs text-slate-400">
            Base URL (engine)
            <input
              name="base_url"
              required
              className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-200"
              placeholder="http://127.0.0.1:8001"
            />
          </label>
          <label className="text-xs text-slate-400">
            API key (X-Site-Key / SDK_MASTER_KEY; blank if the engine has none)
            <input
              name="api_key"
              type="password"
              className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 font-mono text-sm text-slate-200"
            />
          </label>
          <button className="mt-1 w-fit rounded bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500">
            Save instance
          </button>
        </form>
        <p className="mt-3 text-xs text-slate-500">
          Saving with an existing name overwrites that entry. After starting a second
          engine, add it here and use the header switcher (or the row&apos;s switch link).
        </p>
      </section>
    </div>
  );
}
