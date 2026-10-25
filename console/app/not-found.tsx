import Link from "next/link";

export default function NotFound() {
  return (
    <div className="min-h-screen bg-page text-ink flex items-center justify-center p-6 selection:bg-primary-container selection:text-white">
      <div className="max-w-md w-full bg-surface-lowest border border-outline-variant/30 rounded-xl p-8 text-center space-y-6 shadow-xs">
        <div className="w-12 h-12 rounded-xl bg-primary-container/20 border border-primary-container/40 text-primary-container flex items-center justify-center mx-auto text-xl font-bold">
          404
        </div>
        <div className="space-y-2">
          <h1 className="text-xl font-headline font-bold text-ink">Endpoint Not Found</h1>
          <p className="text-sm text-secondary leading-relaxed">
            The requested console route does not exist or has been relocated within the fleet.
          </p>
        </div>
        <div>
          <Link
            href="/"
            className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-lg bg-primary-container text-white font-mono text-xs font-semibold hover:brightness-110 active:scale-[0.98] transition-all"
          >
            ← Return to Fleet Overview
          </Link>
        </div>
      </div>
    </div>
  );
}
