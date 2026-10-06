# Technical Foundations

Content is wasted on a broken site. Fix the foundation first: **don't sprint before you can crawl — or be crawled.**

## Crawlability → indexation → structure
- Audit in this order: can crawlers reach the pages? Are they indexed? Is the structure sane (≤3 clicks, no orphan clusters)?
- **Rule:** No content production until crawlability, indexation, and site structure pass. Content on an uncrawlable site is invisible work.

## Core Web Vitals
- LCP, INP, CLS within "Good" thresholds on the pages that matter (templates first, then top-traffic pages).
- **Why:** Ranking factor and the difference between a visit and a bounce.

## XML sitemaps
- Clean sitemap(s), submitted to GSC and Bing Webmaster Tools. No 404s, no noindexed URLs in the sitemap.
- Split by type (posts, pages) when the site grows.

## IndexNow + Bing Webmaster Tools
- On every publish/update: IndexNow ping **and** Bing WMT URL submission via API.
- **Why:** IndexNow notifies participating engines instantly; Bing submission covers the rest of the non-Google world.

## Standard data quartet
- **GSC + GA4 + PageSpeed + CrUX** — the four APIs every site gets wired to. Rankings, behavior, lab performance, field performance.
- **Why:** One dashboard lies; four cross-check each other.

## Slugs & duplicates
- **Slug collisions:** check before publish; never silently overwrite. Collided slug → suffix or merge decision, logged.
- **Duplicate prevention:** check new content against the corpus on three axes — URL, title, vector similarity. Near-duplicate → merge/differentiate decision (see keyword-strategy cannibalization).
- **Why:** Duplicate and collided URLs are the quietest traffic killers in multi-client engines.
