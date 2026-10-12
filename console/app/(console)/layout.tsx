import Link from "next/link";
import { requireSession } from "@/lib/session";
import { logoutAction } from "@/actions/auth";
import { switchInstanceAction } from "@/actions/instances";
import { currentInstance, registry } from "@/lib/instances";

const NAV = [
  { href: "/", label: "Dashboard" },
  { href: "/queue", label: "Queue" },
  { href: "/articles", label: "Articles" },
  { href: "/stages", label: "Stages" },
  { href: "/sites", label: "Sites" },
  { href: "/provision", label: "Provision" },
];

export default async function ConsoleLayout({ children }: { children: React.ReactNode }) {
  await requireSession();
  const instances = registry();
  const current = await currentInstance();
  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-800 bg-slate-900/60">
        <div className="mx-auto flex max-w-6xl items-center gap-6 px-4 py-3">
          <span className="text-sm font-semibold tracking-wide text-sky-400">
            ContentFTE
          </span>
          <nav className="flex gap-4 text-sm text-slate-300">
            {NAV.map((n) => (
              <Link key={n.href} href={n.href} className="hover:text-white">
                {n.label}
              </Link>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-4">
            {instances.length > 1 ? (
              <form action={switchInstanceAction} className="flex items-center gap-2">
                <label className="text-xs text-slate-500" htmlFor="instance-switch">
                  Instance
                </label>
                <select
                  id="instance-switch"
                  name="instance"
                  defaultValue={current.name}
                  className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200"
                >
                  {instances.map((i) => (
                    <option key={i.name} value={i.name}>
                      {i.name}
                    </option>
                  ))}
                </select>
                <button className="text-xs text-sky-400 hover:text-sky-300">Switch</button>
              </form>
            ) : (
              <span className="text-xs text-slate-500">{current.name}</span>
            )}
            <form action={logoutAction}>
              <button className="text-sm text-slate-400 hover:text-white">Sign out</button>
            </form>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8">{children}</main>
    </div>
  );
}
