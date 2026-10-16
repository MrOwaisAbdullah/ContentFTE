import Link from "next/link";
import { engine, LogsView } from "@/lib/engine";
import { actionColor, Alert, Empty, PageHeader, fmtCost } from "@/lib/ui";
import { FileClock } from "lucide-react";

export const dynamic = "force-dynamic";

/* Logs (plan §6 Wave 4): audit/usage + cost ledger, newest first. Rows
   expand in place (full payload) and the pager walks `offset` through the
   engine — /sdk/v1/logs pages whichever list is surfaced. */

const PAGE = 100;

const KINDS: { key: string; label: string }[] = [
  { key: "", label: "all" },
  { key: "usage", label: "usage (model+image)" },
  { key: "publish", label: "publish" },
  { key: "article", label: "article" },
  { key: "cost", label: "cost ledger" },
];

const FILTER_CLS = (active: boolean) =>
  `rounded-full border px-3 py-1 transition-colors ${
    active
      ? "border-accent/60 bg-accent/10 text-accent"
      : "border-line bg-page text-ink-faint hover:border-ink-faint hover:text-ink"
  }`;

const when = (iso: string | null) => (iso ? iso.slice(0, 19).replace("T", " ") : "—");

export default async function LogsPage({
  searchParams,
}: {
  searchParams: Promise<{ kind?: string; offset?: string }>;
}) {
  const { kind = "", offset: offsetRaw } = await searchParams;
  const offset = Math.max(0, Number.parseInt(offsetRaw ?? "0", 10) || 0);

  let data: LogsView | null = null;
  let error = "";
  try {
    const qs = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
    if (kind) qs.set("kind", kind);
    data = await engine<LogsView>(`/logs?${qs}`);
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  const auditRows: LogsView["audit"] =
    data !== null && kind !== "cost" ? data.audit : [];
  const costRows: LogsView["costs"] =
    data !== null && (!kind || kind === "cost") ? data.costs : [];
  const hasMore = auditRows.length === PAGE || costRows.length === PAGE;
  const shown = Math.max(auditRows.length, costRows.length);
  const pastEnd = data !== null && offset > 0 && shown === 0;

  const pagedHref = (next: number) => {
    const qs = new URLSearchParams();
    if (kind) qs.set("kind", kind);
    if (next > 0) qs.set("offset", String(next));
    const s = qs.toString();
    return s ? `/logs?${s}` : "/logs";
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Logs"
        sub="audit + usage + cost ledger, newest first — click a row for its full payload"
        right={
          <span className="flex items-center gap-4">
            <Link href="/insights" className="text-xs text-accent hover:text-accent-strong hover:underline">
              insights (cost) →
            </Link>
            <Link href="/stages" className="text-xs text-accent hover:text-accent-strong hover:underline">
              pipeline runs →
            </Link>
          </span>
        }
      />

      {error ? <Alert tone="error">Engine unreachable: {error}</Alert> : null}

      <div className="flex flex-wrap gap-2 text-xs">
        {KINDS.map((k) => (
          <Link
            key={k.key || "all"}
            href={k.key ? `/logs?kind=${k.key}` : "/logs"}
            className={FILTER_CLS(kind === k.key)}
          >
            {k.label}
          </Link>
        ))}
      </div>

      {data && pastEnd ? (
        <Empty
          icon={FileClock}
          title="Nothing in this window"
          hint={`The pager landed past the newest ${kind === "cost" ? "cost" : "log"} rows.`}
          cta={{ href: pagedHref(0), label: "Back to newest" }}
        />
      ) : null}

      {data && !pastEnd && kind !== "cost" ? (
        <section className="space-y-2">
          <h2 className="text-sm font-medium text-ink-dim">
            Audit / usage rows ({auditRows.length} shown)
          </h2>
          {auditRows.length === 0 ? (
            offset > 0 ? (
              <p className="text-xs text-ink-faint">No audit rows in this window.</p>
            ) : (
              <Empty
                icon={FileClock}
                title="No audit rows"
                hint="Engine activity lands here as it runs stages and articles."
                cta={{ href: "/stages", label: "Open stage runs" }}
              />
            )
          ) : (
            <ul className="space-y-1.5">
              {auditRows.map((a) => (
                <li key={a.id} className="overflow-hidden rounded-lg border border-line/60 bg-page/40">
                  <details>
                    <summary className="flex cursor-pointer flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-xs">
                      <FileClock className="h-3.5 w-3.5 shrink-0 text-ink-faint" aria-hidden />
                      <span className="whitespace-nowrap font-mono text-[11px] text-ink-faint">
                        {when(a.created_at)}
                      </span>
                      <span className={`font-mono ${actionColor(a.action)}`}>{a.action}</span>
                      {a.article_id ? (
                        <Link href={`/articles/${a.article_id}`} className="text-accent hover:underline">
                          #{a.article_id}
                        </Link>
                      ) : null}
                      <span className="max-w-md truncate font-mono text-[11px] text-ink-faint/80">
                        {JSON.stringify(a.payload)}
                      </span>
                    </summary>
                    <pre className="max-h-64 overflow-auto border-t border-line/60 px-3 py-2 font-mono text-[11px] leading-5 text-ink-faint">
                      {JSON.stringify(a.payload, null, 2)}
                    </pre>
                  </details>
                </li>
              ))}
            </ul>
          )}
        </section>
      ) : null}

      {data && !pastEnd && (!kind || kind === "cost") ? (
        <section className="space-y-2">
          <h2 className="text-sm font-medium text-ink-dim">
            Cost ledger ({costRows.length} shown)
          </h2>
          {costRows.length === 0 ? (
            offset > 0 ? (
              <p className="text-xs text-ink-faint">No cost rows in this window.</p>
            ) : (
              <Empty
                icon={FileClock}
                title="No cost rows"
                hint="Every LLM / image call logs its spend here."
                cta={{ href: "/insights", label: "Open insights" }}
              />
            )
          ) : (
            <div className="overflow-x-auto rounded-xl border border-line bg-card">
              <table className="w-full text-sm">
                <thead className="border-b border-line text-left text-xs text-ink-faint">
                  <tr>
                    <th className="px-4 py-2.5">When</th>
                    <th className="px-4 py-2.5">Article</th>
                    <th className="px-4 py-2.5">Kind</th>
                    <th className="px-4 py-2.5 text-right">Amount</th>
                    <th className="px-4 py-2.5">Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {costRows.map((c) => (
                    <tr
                      key={c.id}
                      className="border-t border-line/60 align-top first:border-t-0 hover:bg-surface/40"
                    >
                      <td className="whitespace-nowrap px-4 py-2 font-mono text-xs text-ink-faint">
                        {when(c.created_at)}
                      </td>
                      <td className="px-4 py-2 text-xs">
                        <Link href={`/articles/${c.article_id}`} className="text-accent hover:underline">
                          #{c.article_id}
                        </Link>
                      </td>
                      <td className="px-4 py-2 text-xs text-ink-dim">{c.kind}</td>
                      <td className="px-4 py-2 text-right font-mono text-xs text-gold">
                        {fmtCost(c.amount_usd)}
                      </td>
                      <td className="px-4 py-2">
                        <details className="max-w-xl">
                          <summary className="cursor-pointer truncate font-mono text-xs text-ink-faint hover:text-ink-dim">
                            {JSON.stringify(c.detail)}
                          </summary>
                          <pre className="mt-1 max-h-64 overflow-auto rounded border border-line/60 bg-page/40 px-2 py-1.5 font-mono text-[11px] leading-5 text-ink-faint">
                            {JSON.stringify(c.detail, null, 2)}
                          </pre>
                        </details>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ) : null}

      {data && !pastEnd ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-card px-4 py-2.5 text-xs">
          {offset > 0 ? (
            <Link href={pagedHref(Math.max(0, offset - PAGE))} className="text-accent hover:underline">
              ← Newer
            </Link>
          ) : (
            <span aria-disabled="true" className="text-ink-faint/50">
              ← Newer
            </span>
          )}
          <span className="font-mono text-[11px] text-ink-faint">
            {shown === 0
              ? "no rows"
              : `rows ${offset + 1}–${offset + shown}${hasMore ? "" : " · end"}`}
          </span>
          {hasMore ? (
            <Link href={pagedHref(offset + PAGE)} className="text-accent hover:underline">
              Older →
            </Link>
          ) : (
            <span aria-disabled="true" className="text-ink-faint/50">
              Older →
            </span>
          )}
        </div>
      ) : null}
    </div>
  );
}
