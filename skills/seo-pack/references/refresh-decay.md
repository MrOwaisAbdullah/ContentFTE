# Refresh & Decay

## Refresh protocol
- **Major refresh** (angle outdated, intent shifted, big quality gap): improve content → republish at a **new URL** → 301 old → new.
- **Minor refresh** (stats stale, new section, light rewrite): update **in place**, bump `dateModified`.
- **Why:** Refreshes routinely **double traffic** on decaying pages. Wrong choice (minor when major was needed) wastes the effort.

## GSC decay loop
- **Tactic:** Monitor Search Console per page. **>30% click decay over 90 days** → generate a refresh brief automatically.
- **Why:** Decay is a leading indicator you can act on; waiting for "traffic dropped" post-mortems loses months.
- **ContentFTE wiring:** Decay job emits refresh briefs; brief agent picks major vs minor route.

## dateModified bumps
- Always update `dateModified` (and visible "Updated" date) on refresh.
- **Why:** Freshness signal for crawlers and a recency factor for LLM citations.

## SEO drift snapshots
- **Tactic:** Snapshot rankings, indexed pages, and key on-page facts to SQLite on a schedule; diff baseline vs current.
- **Why:** Catches silent regressions (lost schema, dropped pages, title rewrites) before they cost quarters.

## Recency as citation factor
- LLMs prefer fresh sources. A current page with 2026 data beats a better 2023 page for citations.
- **Rule:** Date-sensitive claims (stats, pricing, "best" lists) get a refresh SLA: review every 6–12 months.
