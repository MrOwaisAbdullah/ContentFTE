import Link from "next/link";
import { requireSession } from "@/lib/session";
import { logoutAction } from "@/actions/auth";

const NAV = [
  { href: "/", label: "Dashboard" },
  { href: "/queue", label: "Queue" },
  { href: "/articles", label: "Articles" },
  { href: "/stages", label: "Stages" },
];

export default async function ConsoleLayout({ children }: { children: React.ReactNode }) {
  await requireSession();
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
          <form action={logoutAction} className="ml-auto">
            <button className="text-sm text-slate-400 hover:text-white">Sign out</button>
          </form>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8">{children}</main>
    </div>
  );
}
