import { requireSession } from "@/lib/session";
import { currentInstance, registry } from "@/lib/instances";
import { removeInstanceAction, saveInstanceAction, switchInstanceAction } from "@/actions/instances";
import { Alert, PageHeader } from "@/lib/ui";
import { PendingButton } from "@/lib/interactive";

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
      <PageHeader
        title="Instances"
        sub="every engine this console can manage"
      />
      <p className="-mt-4 text-sm text-ink-dim">
        <span className="text-ink">env</span> entries come from{" "}
        <code className="rounded bg-surface px-1 py-0.5 font-mono text-xs">CONSOLE_INSTANCES</code>{" "}
        (edit the env to change them); <span className="text-ink">file</span> entries are stored in{" "}
        <code className="rounded bg-surface px-1 py-0.5 font-mono text-xs">instances.json</code> and
        managed right here.
      </p>

      {saved ? <Alert tone="success">Instance "{saved}" saved.</Alert> : null}
      {removed ? <Alert tone="success">Instance "{removed}" removed.</Alert> : null}
      {err ? <Alert tone="error">{err}</Alert> : null}

      <div className="overflow-x-auto rounded-xl border border-line bg-card">
        <table className="w-full text-sm">
          <thead className="border-b border-line text-left text-xs text-ink-faint">
            <tr>
              <th className="px-4 py-2.5">Name</th>
              <th className="px-4 py-2.5">Base URL</th>
              <th className="px-4 py-2.5">API key</th>
              <th className="px-4 py-2.5">Origin</th>
              <th className="px-4 py-2.5">Selected</th>
              <th className="px-4 py-2.5" />
            </tr>
          </thead>
          <tbody>
            {instances.map((i) => (
              <tr key={i.name} className="border-t border-line/60 first:border-t-0 hover:bg-surface/40">
                <td className="px-4 py-2.5 font-medium text-ink">{i.name}</td>
                <td className="px-4 py-2.5 font-mono text-xs text-ink-dim">{i.baseUrl}</td>
                <td className="px-4 py-2.5 text-xs text-ink-faint">{i.apiKey ? "••• set" : "—"}</td>
                <td className="px-4 py-2.5 text-xs">
                  <span className={i.origin === "env" ? "text-amber-300" : "text-accent"}>{i.origin}</span>
                </td>
                <td className="px-4 py-2.5 text-xs">
                  {i.name === current.name ? (
                    <span className="text-emerald-300">active</span>
                  ) : (
                    <form action={switchInstanceAction} className="inline">
                      <input type="hidden" name="instance" value={i.name} />
                      <PendingButton className="text-xs text-accent hover:underline" pendingLabel="Switching…">
                        switch →
                      </PendingButton>
                    </form>
                  )}
                </td>
                <td className="px-4 py-2.5 text-right">
                  {i.origin === "file" ? (
                    <form action={removeInstanceAction} className="inline">
                      <input type="hidden" name="name" value={i.name} />
                      <PendingButton
                        className="text-xs text-rose-300 hover:underline"
                        confirmMessage={`Remove instance "${i.name}" from the console registry?`}
                        pendingLabel="Removing…"
                      >
                        remove
                      </PendingButton>
                    </form>
                  ) : (
                    <span className="text-xs text-ink-faint/60">env-locked</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <section className="rounded-xl border border-line bg-card p-5">
        <h2 className="text-sm font-semibold text-ink">Add / edit a file instance</h2>
        <form action={saveInstanceAction} className="mt-4 grid max-w-xl gap-3">
          <label className="text-xs text-ink-dim">
            Name (unique)
            <input
              name="name"
              required
              className="mt-1 w-full rounded-md border border-line bg-page px-3 py-2 text-sm text-ink placeholder:text-ink-faint/70 focus:border-accent"
              placeholder="site2"
            />
          </label>
          <label className="text-xs text-ink-dim">
            Base URL (engine)
            <input
              name="base_url"
              required
              className="mt-1 w-full rounded-md border border-line bg-page px-3 py-2 text-sm text-ink placeholder:text-ink-faint/70 focus:border-accent"
              placeholder="http://127.0.0.1:8001"
            />
          </label>
          <label className="text-xs text-ink-dim">
            API key (X-Site-Key / SDK_MASTER_KEY; blank if the engine has none)
            <input
              name="api_key"
              type="password"
              className="mt-1 w-full rounded-md border border-line bg-page px-3 py-2 font-mono text-sm text-ink focus:border-accent"
            />
          </label>
          <PendingButton
            pendingLabel="Saving…"
            className="mt-1 w-fit rounded-md bg-accent-strong px-4 py-2 text-sm font-medium text-page transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            Save instance
          </PendingButton>
        </form>
        <p className="mt-3 text-xs text-ink-faint">
          Saving with an existing name overwrites that entry. After starting a second
          engine, add it here and use the header switcher (or the row's switch link).
        </p>
      </section>
    </div>
  );
}
