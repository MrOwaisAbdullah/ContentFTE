/**
 * Shown while a console page streams in (plan CON-07). Pages await several
 * engine calls, so without this navigation feels frozen until all of them finish.
 */
export default function ConsoleLoading() {
  return (
    <div className="space-y-6" role="status" aria-live="polite" aria-busy="true">
      <span className="sr-only">Loading…</span>
      <div className="space-y-2">
        <div className="h-6 w-56 animate-pulse rounded-md bg-surface" />
        <div className="h-3.5 w-80 max-w-full animate-pulse rounded bg-surface/70" />
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <div key={i} className="h-24 animate-pulse rounded-xl border border-line bg-card" />
        ))}
      </div>
      <div className="h-64 animate-pulse rounded-xl border border-line bg-card" />
    </div>
  );
}
