import Link from "next/link";
import { notFound } from "next/navigation";
import {
  engine,
  type ArticleList,
  type BriefPeek,
  type QueueView,
  type SiteHealth,
  type SiteList,
} from "@/lib/engine";
import { currentInstance } from "@/lib/instances";
import { requireSession } from "@/lib/session";
import { Alert, PageHeader, Pill, SectionCard, checkTier, fmtDate, fmtScore } from "@/lib/ui";

export const dynamic = "force-dynamic";

function Stat({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="rounded-xl border border-line bg-card px-4 py-3">
      <p className="text-[11px] uppercase tracking-wide text-ink-faint">{label}</p>
      <p className="mt-1 font-mono text-2xl text-ink">{value}</p>
      <p className="mt-0.5 text-xs text-ink-faint">{sub}</p>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[11px] uppercase tracking-wide text-ink-faint">{label}</dt>
      <dd className="mt-0.5 break-words font-mono text-xs text-ink-dim">{value}</dd>
    </div>
  );
}

function Finding({ tier, text }: { tier: "fail" | "warn" | "info"; text: string }) {
  const cls =
    tier === "fail" ? "text-rose-300" : tier === "warn" ? "text-amber-300" : "text-ink-dim";
  const dot = tier === "fail" ? "bg-danger" : tier === "warn" ? "bg-gold" : "bg-ink-faint/60";
  return (
    <p className={`flex items-start gap-2 text-xs ${cls}`}>
      <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} aria-hidden />
      <span className="min-w-0">{text}</span>
    </p>
  );
}

export default async function SiteDetailPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  await requireSession();
  const { slug } = await params;
  const inst = await currentInstance();

  let sites: SiteList | null = null;
  let loadErr = "";
  try {
    sites = await engine<SiteList>("/sites");
  } catch (e) {
    loadErr = e instanceof Error ? e.message : String(e);
  }

  if (loadErr) {
    return (
      <div className="space-y-6">
        <PageHeader title={`Site ${slug}`} sub={`instance ${inst.name} (${inst.baseUrl})`} />
        <Alert tone="warn">Could not load sites: {loadErr}</Alert>
        <Link href="/sites" className="text-xs text-accent hover:underline">
          ← All sites
        </Link>
      </div>
    );
  }

  const site = sites?.sites.find((s) => s.slug === slug);
  if (!site) notFound();

  const [health, queue, brief, articles] = await Promise.all([
    engine<SiteHealth>(`/sites/${encodeURIComponent(slug)}/health`).catch(() => null),
    engine<QueueView>(`/sites/${encodeURIComponent(slug)}/queue?limit=1`).catch(() => null),
    engine<BriefPeek>(`/sites/${encodeURIComponent(slug)}/brief`).catch(() => null),
    engine<ArticleList>(`/articles?site_slug=${encodeURIComponent(slug)}&limit=500`).catch(() => null),
  ]);

  const statusCounts: Record<string, number> = {};
  for (const a of articles?.articles ?? []) {
    statusCounts[a.status] = (statusCounts[a.status] ?? 0) + 1;
  }
  const readyToPublish = statusCounts["approved"] ?? 0;
  const latest = (articles?.articles ?? []).slice(0, 6);

  const settings = site.settings ?? {};
  const settingsEmpty = Object.keys(settings).length === 0;

  const links: { href: string; label: string }[] = [
    { href: `/articles/keywords?site=${encodeURIComponent(slug)}`, label: "Keyword ledger" },
    { href: `/articles/research?site=${encodeURIComponent(slug)}`, label: "Research" },
    { href: `/articles/briefs?site=${encodeURIComponent(slug)}`, label: "Briefs" },
    { href: `/media?site=${encodeURIComponent(slug)}`, label: "Media" },
    { href: `/insights?site=${encodeURIComponent(slug)}`, label: "Insights" },
    { href: `/stages?site=${encodeURIComponent(slug)}`, label: "Stages" },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title={site.name || site.slug}
        sub={`${site.slug} · ${site.site_type} · publish: ${site.publish_mode || "draft"} · ${
          site.base_url || "no base url"
        } — instance ${inst.name}`}
        right={
          <Link href="/sites" className="text-xs text-accent hover:underline">
            ← All sites
          </Link>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Briefable keywords"
          value={health ? String(health.ledger.briefable) : "—"}
          sub="ledger rows ready for the brief stage"
        />
        <Stat
          label="Published"
          value={health ? String(health.ledger.published) : "—"}
          sub="ledger rows marked published"
        />
        <Stat
          label="Articles"
          value={articles ? String(articles.total) : "—"}
          sub="all statuses on this site"
        />
        <Stat
          label="Ready to publish"
          value={articles ? String(readyToPublish) : "—"}
          sub="articles in approved state"
        />
      </div>

      <SectionCard title="Health">
        {health ? (
          <div className="space-y-2">
            <p className="text-xs text-ink-faint">
              {health.ledger.briefable} briefable · {health.ledger.published} published ·{" "}
              {health.wp_configured ? "WP config OK" : "WP not configured"} · base{" "}
              {health.base_url || "—"}
            </p>
            {health.critical.map((line) => (
              <Finding key={`c-${line}`} tier="fail" text={line} />
            ))}
            {health.checks.map((line) => (
              <Finding key={`k-${line}`} tier={checkTier(line)} text={line} />
            ))}
            {health.critical.length === 0 && health.checks.length === 0 ? (
              <p className="text-xs text-ink-faint">No findings — the probes reported nothing.</p>
            ) : null}
          </div>
        ) : (
          <p className="text-xs text-ink-faint">Health unreachable — the engine probe failed.</p>
        )}
      </SectionCard>

      <SectionCard title="Pipeline snapshot">
        <div className="grid gap-4 lg:grid-cols-2">
          <div>
            <p className="text-[11px] uppercase tracking-wide text-ink-faint">
              Next briefable keyword
            </p>
            {brief?.keyword ? (
              <>
                <p className="mt-1 text-sm text-ink" title={brief.keyword}>
                  {brief.keyword}
                </p>
                <p className="mt-0.5 text-xs text-ink-faint">
                  {brief.intent || "no intent"} · priority {fmtScore(brief.priority_score)}
                </p>
              </>
            ) : (
              <p className="mt-1 text-xs text-ink-faint">
                {brief?.hint || brief?.error || "peek unavailable"}
              </p>
            )}
          </div>
          <div>
            <p className="text-[11px] uppercase tracking-wide text-ink-faint">
              Ledger by status
            </p>
            {queue && Object.keys(queue.counts).length > 0 ? (
              <div className="mt-1 flex flex-wrap gap-1.5">
                {Object.entries(queue.counts).map(([st, n]) => (
                  <span
                    key={st}
                    className="rounded-full border border-line bg-surface/60 px-2 py-0.5 text-[11px] text-ink-dim"
                  >
                    {st} {n}
                  </span>
                ))}
              </div>
            ) : (
              <p className="mt-1 text-xs text-ink-faint">ledger empty</p>
            )}
          </div>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {links.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className="rounded-full border border-line bg-surface/60 px-3 py-1 text-xs text-accent hover:border-accent/50"
            >
              {l.label} →
            </Link>
          ))}
        </div>
      </SectionCard>

      <SectionCard title="Settings (read-only)">
        <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
          <Fact label="Site type" value={site.site_type || "—"} />
          <Fact label="Publish mode" value={site.publish_mode || "draft"} />
          <Fact label="Base URL" value={site.base_url || "—"} />
          <Fact
            label="API key"
            value={site.has_key ? "set — value never leaves the engine" : "not set"}
          />
          <Fact label="Created" value={fmtDate(site.created_at)} />
        </dl>
        <div className="mt-4">
          <p className="text-[11px] uppercase tracking-wide text-ink-faint">settings JSON</p>
          {settingsEmpty ? (
            <p className="mt-1 text-xs text-ink-faint">
              {"{}"} — no site overrides; engine defaults apply.
            </p>
          ) : (
            <pre className="mt-1 overflow-x-auto rounded-lg border border-line bg-page px-3 py-2 font-mono text-xs text-ink-dim">
              {JSON.stringify(settings, null, 2)}
            </pre>
          )}
        </div>
        <p className="mt-3 text-xs text-ink-faint">
          Read-only for now — site settings are written by the engine/env; console editing
          arrives with a PATCH op.
        </p>
      </SectionCard>

      <SectionCard
        title="Articles"
        right={
          <Link href="/articles" className="text-xs text-accent hover:underline">
            all articles →
          </Link>
        }
      >
        {articles && articles.articles.length > 0 ? (
          <>
            {Object.keys(statusCounts).length > 0 ? (
              <div className="mb-3 flex flex-wrap gap-1.5">
                {Object.entries(statusCounts).map(([st, n]) => (
                  <span
                    key={st}
                    className="rounded-full border border-line bg-surface/60 px-2 py-0.5 text-[11px] text-ink-dim"
                  >
                    {st} {n}
                  </span>
                ))}
              </div>
            ) : null}
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-line text-xs uppercase tracking-wide text-ink-faint">
                  <tr>
                    <th className="px-3 py-2">#</th>
                    <th className="px-3 py-2">Title</th>
                    <th className="px-3 py-2">Status</th>
                    <th className="px-3 py-2">Created</th>
                  </tr>
                </thead>
                <tbody>
                  {latest.map((a) => (
                    <tr key={a.id} className="border-t border-line/60">
                      <td className="px-3 py-2 font-mono text-xs">
                        <Link href={`/articles/${a.id}`} className="text-accent hover:underline">
                          #{a.id}
                        </Link>
                      </td>
                      <td className="max-w-[360px] truncate px-3 py-2 text-ink-dim" title={a.title}>
                        {a.title}
                      </td>
                      <td className="px-3 py-2">
                        <Pill status={a.status} />
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-xs text-ink-faint">
                        {fmtDate(a.created_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {articles.total > latest.length ? (
              <p className="mt-2 text-xs text-ink-faint">
                Showing the newest {latest.length} of {articles.total} — the full list lives on
                Content pipeline.
              </p>
            ) : null}
          </>
        ) : (
          <p className="text-xs text-ink-faint">
            No articles on this site yet — submit a keyword on the ledger and run the
            brief/content stages.
          </p>
        )}
      </SectionCard>
    </div>
  );
}
