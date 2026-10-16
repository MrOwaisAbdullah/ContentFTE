import Link from "next/link";
import { Images } from "lucide-react";

import { engine, ArticleDetail, ArticleList, ArticleListItem } from "@/lib/engine";
import { MediaCard, MediaImage } from "@/lib/media";
import { Alert, Empty, PageHeader, Pill, fmtDate } from "@/lib/ui";

export const dynamic = "force-dynamic";

/* Site Media gallery (plan §6 Wave 3): every staged image across the
   site's articles, grouped by article, with the Jev style pick + VLM lane
   scores from meta.images. Read-only — staging/replacing happens on the
   article page. Articles with art are found via the list `images` count,
   so no detail fetch is wasted on empty rows. */
export default async function MediaPage({
  searchParams,
}: {
  searchParams: Promise<{ site?: string }>;
}) {
  const { site = "" } = await searchParams;
  let list: ArticleList | null = null;
  let error = "";
  try {
    list = await engine<ArticleList>(`/articles?limit=500`);
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  const withArt = (list?.articles ?? []).filter(
    (a) => (a.images ?? 0) > 0 && (!site || a.site_slug === site),
  );
  const details = await Promise.allSettled(
    withArt.map((a) => engine<ArticleDetail>(`/articles/${a.id}/content`)),
  );
  const groups: { article: ArticleListItem; images: MediaImage[] }[] = [];
  details.forEach((res, i) => {
    if (res.status !== "fulfilled") return;
    const imgs = (res.value.meta?.images as MediaImage[] | undefined) ?? [];
    if (imgs.length) groups.push({ article: withArt[i], images: imgs });
  });
  const total = groups.reduce((n, g) => n + g.images.length, 0);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Media"
        sub={
          list
            ? total > 0
              ? `${total} image${total === 1 ? "" : "s"} across ${groups.length} article${
                  groups.length === 1 ? "" : "s"
                }${site ? ` on ${site}` : " across all sites"}`
              : `No staged art${site ? ` on ${site}` : ""} yet`
            : "staged article art with style + QA provenance"
        }
        right={
          <Link href="/articles" className="text-xs text-accent hover:text-accent-strong hover:underline">
            content pipeline →
          </Link>
        }
      />

      {error ? <Alert tone="error">Engine unreachable: {error}</Alert> : null}

      {!list ? null : groups.length === 0 ? (
        <Empty
          icon={Images}
          title={site ? `No staged art on ${site}` : "No staged art yet"}
          hint="Images land here when an article stages them (header 'Stage images', or automatically at publish). Each card carries the Jev style pick and VLM QA lanes from meta.images."
          cta={{ href: "/articles", label: "Open content pipeline" }}
        />
      ) : (
        <>
          {site ? (
            <p className="text-xs text-ink-faint">
              Filtered to <span className="font-mono text-ink-dim">{site}</span> ·{" "}
              <Link href="/media" className="text-accent hover:underline">
                show all sites
              </Link>
            </p>
          ) : null}
          <div className="space-y-8">
            {groups.map((g) => (
              <section key={g.article.id} className="space-y-3">
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <Link
                    href={`/articles/${g.article.id}?tab=media`}
                    className="text-sm font-medium hover:text-accent"
                  >
                    {g.article.title || `#${g.article.id}`}
                  </Link>
                  <Pill status={g.article.status} />
                  <span className="font-mono text-xs text-ink-faint">{g.article.site_slug}</span>
                  <span className="text-xs text-ink-faint">
                    {g.images.length} image{g.images.length === 1 ? "" : "s"}
                  </span>
                  <span className="ml-auto text-xs text-ink-faint">
                    {fmtDate(g.article.published_at || g.article.created_at)}
                  </span>
                </div>
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                  {g.images.map((img, i) => (
                    <MediaCard key={`${g.article.id}-${i}`} articleId={g.article.id} image={img} />
                  ))}
                </div>
              </section>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
