# Authority & Internal Linking

## PageRank decay routing
- **Tactic:** Point backlinks at `/services/` and money pages — not the homepage. Authority decays with each click from the link target, so land it where it converts.
- **Why:** Homepage links waste equity; deep links compound on the pages that earn.
- **ContentFTE wiring:** Outreach/link briefs name the target money page, never default to home.

## Anchor-text control + consistent terminology
- **Tactic:** Use the same money-keyword phrasing in internal anchors site-wide; keep terminology identical across pages.
- **Why:** Consistent anchors teach crawlers what each page is about. Inconsistent phrasing dilutes the signal.

## Topical authority compounds
- **Tactic:** Build dense clusters around the money topic. Clusters start ranking for keywords they were never optimized for.
- **Why:** Authority is topical, not page-level. Ten interlinked pages beat one "perfect" page.

## Internal link rules
- Every important page ≤ **3 clicks** from the homepage.
- Hub pages link deliberately to BOFU pages.
- Guides link to **2–3 relevant money pages** and **3–4 related guides**.
- **No dead ends** — every page links onward.
- **Hygiene gate (spec §5.6):** 3–8 internal links and 1–3 external links per
  article, and no exact-match anchor text reused more than twice. Enforced in
  `lib/linkguard.py` before publish.
- **ContentFTE wiring:** Eval checks the link map; draft agent gets the target link list in the brief.

## Orphan rescue
- **Tactic:** Find published pages with **<3 inbound internal links** and wire them into relevant hubs/guides.
- **Why:** Orphans don't rank no matter how good they are.

## Niche podcast guesting
- **Tactic:** Appear on niche podcasts in the client's industry.
- **Why:** Earns backlinks, brand mentions, and entity associations LLMs pick up.

## Expert-quote platforms
- **Tactic:** Answer journalist queries on platforms like Featured.com (free tier).
- **Why:** High-authority mentions + links for the cost of an email.

## "Cheap X" modifiers + micro-influencer mentions
- **Tactic:** Target "cheap/affordable X" modifier keywords (weak SERPs, buyer intent); seed product with niche micro-influencers for mentions.
- **Why:** Low-competition entry points that compound into branded search and citations.
