# Keyword Strategy

## Compact Keywords (BOFU pages)
- **Tactic:** Target purchase-intent phrases, ~400–500 words (tested average ~415), exact-intent H1/title, direct CTA. Less competition, fewer backlinks needed than generic informational topics.
- **Why:** High-intent searches have thin, weak SERPs; a tight, specific page outranks a 3,000-word generic guide.
- **Patterns:** `"best X for Y"`, `"cheapest X"`, `"X vs Y"`, `"X without Z"`, `"[solution] for [niche]"` (e.g. "CRM for dental clinics").
- **Rule:** One intent per page. Unique data per page (pricing, examples, screenshots) — no template-stuffed boilerplate.
- **ContentFTE wiring:** Factory service/location pages use this format; blog posts build authority around them.

## Intent templates
- **Tactic:** Brief agent picks the article template by search intent: how-to, comparison, listicle, landing, definition, review.
- **Why:** Intent-template mismatch is the #1 reason good content underranks.
- **ContentFTE wiring:** Brief selects template; templates versioned alongside this pack.

## Cannibalization detection
- **Tactic:** Before writing on a keyword, check the corpus for *intent overlap* — not just duplicate text, but two pages that would compete for the same query.
- **Rule:** Similarity + intent-overlap check → decision: **write / merge / differentiate**. Never publish two pages targeting one intent.
- **ContentFTE wiring:** JEV triage lane runs this check on every new brief.

## Semantic clustering → hub-and-spoke
- **Tactic:** Seed keyword → SERP-based semantic clustering → hub page + spoke pages, deliberately interlinked.
- **Why:** Topical authority compounds — clusters rank for keywords they weren't even optimized for.
- **ContentFTE wiring:** Cluster plan decides *which* pages get generated; programmatic templates decide *how*.

## Programmatic page planning
- **Tactic:** Generate many similar pages (locations, comparisons, use-cases) from one template — but each page must carry unique data (local stats, real examples).
- **Why:** Scale without tripping thin-content filters.
- **ContentFTE wiring:** Programmatic engine sits under the cluster plan; unique-data requirement enforced at eval.

## Site keyword ledger (campaign memory)
- **Tactic:** Every site keeps a keyword ledger (Postgres): keyword, intent, volume, difficulty, priority score, cluster, status (`researched → approved → queued → briefed → drafted → published → ranking → won | lost | retired`), target URL, research snapshot, review date (30/60 days).
- **Rule:** Briefs may only pull from `approved`/`queued` rows. No ledger row, no brief — kills random one-off topics.
- **Priority:** `(volume × intent_value × winnability) / difficulty`. Engine always works the highest-scoring queued keyword next.
- **Lifecycle:** rank tracking writes back `won`/`lost`; lost keywords auto-generate refresh briefs, won keywords free their slot. Every 30/60 days the operator reviews: retire winners and dead keywords, approve the next batch. History is kept — never blindly re-target a loser.
- **Cluster coverage:** track published-pages ÷ cluster-keywords per cluster, not just single-keyword wins.
- **Query mining:** monthly GSC scan for impression-earning queries with no targeting page → suggested ledger additions.
- **ContentFTE wiring:** spec §5.16. The ledger is the campaign's memory; the calendar view (keyword → week) is the Phase 1 operator view and Phase 2 customer feature.
