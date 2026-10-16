import { requireSession } from "@/lib/session";
import { logoutAction } from "@/actions/auth";
import { switchInstanceAction } from "@/actions/instances";
import { currentInstance, registry } from "@/lib/instances";
import { NavLinks, PendingButton } from "@/lib/interactive";
import { Toaster } from "@/lib/toast";
import { Bot } from "lucide-react";

// Sheet-tab order (spec §5) drives the nav inside <NavLinks/>: the console
// mirrors the Google Sheets workbook — keywords, research, brief, content,
// logs — then the instance/tooling screens. Full sidebar IA lands in Wave 1.
export default async function ConsoleLayout({ children }: { children: React.ReactNode }) {
  await requireSession();
  const instances = await registry();
  const current = await currentInstance();
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-line bg-card/80 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
          <span className="flex items-center gap-2 text-sm font-semibold tracking-wide text-accent">
            <span className="flex h-6 w-6 items-center justify-center rounded-md bg-accent/10" aria-hidden>
              <Bot className="h-4 w-4" />
            </span>
            ContentFTE
          </span>
          <NavLinks />
          <div className="ml-auto flex items-center gap-3">
            {instances.length > 1 ? (
              <form action={switchInstanceAction} className="flex items-center gap-2">
                <label className="text-xs text-ink-faint" htmlFor="instance-switch">
                  Instance
                </label>
                <select
                  id="instance-switch"
                  name="instance"
                  defaultValue={current.name}
                  className="rounded-md border border-line bg-surface px-2 py-1 text-xs text-ink"
                >
                  {instances.map((i) => (
                    <option key={i.name} value={i.name}>
                      {i.name}
                    </option>
                  ))}
                </select>
                <PendingButton className="rounded-md border border-line bg-page px-2.5 py-1 text-xs text-ink-dim hover:border-ink-faint hover:text-ink">
                  Switch
                </PendingButton>
              </form>
            ) : (
              <span className="hidden rounded-md border border-line bg-surface px-2.5 py-1 text-xs text-ink-faint sm:block">
                instance: {current.name}
              </span>
            )}
            <form action={logoutAction}>
              <PendingButton className="rounded-md px-2.5 py-1 text-xs text-ink-faint hover:text-ink">
                Sign out
              </PendingButton>
            </form>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-8">{children}</main>
      <Toaster />
    </div>
  );
}
