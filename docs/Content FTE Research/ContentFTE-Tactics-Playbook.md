# ContentFTE Tactics Playbook — Edward Sturm (@buildinpublic)

**Source:** Edward Sturm — edwardsturm.com articles (~99), The Edward Show (900+ daily episodes), Compact Keywords method. Distilled from his public articles and two community skill files documenting his system (`luuow/meridian-mcp` skills/edward-sturm, `fkleppe/seo-qs`).
**Purpose:** the living tactics library behind ContentFTE's brief agent, draft agent, and eval agent. New tactics get added here with a source; agents reference this file, not hardcoded prompt tricks.
**Last updated:** 2026-10-04

> **Key tension, resolved:** Sturm's thesis is "blog SEO targets cold searchers; Compact Keywords landing pages target warm buyers." ContentFTE does both jobs: **Factory service/location pages = Compact Keywords format** (the money pages), **blog posts = topical authority + PAA capture** that feeds them. Different pages, different jobs, one system.

---

## 1. Compact Keywords (core method)

Target bottom-of-funnel, high-intent keywords — not informational blog topics.
- **Format:** 400–500 word landing pages (his tested average: ~415 words), exact-match H1/title ("If someone searches 'BCBA supervision tools', your title is 'BCBA Supervision Tools'").
- **Why it works:** very low competition, less content needed to rank, fewer backlinks required, high conversion. Searchers already want the thing — the page just has to be the brand that gives it to them.
- **Rules:** clear CTA on every page; no fluff; genuinely unique data per page (not template fill-in with swapped entity names — post March-2026 spam update); patterns to hunt: "best X for Y", "cheapest X", "X vs Y", "X without Z", "[solution] for [niche audience]".
- **ContentFTE mapping:** Factory service/location pages use this format (§5.10-5 programmatic templates). Blog posts stay longer-form but every post links to the relevant Compact page (see §6).

## 2. On-page structure

- **Keyword at the very beginning of Page Title and H1** — "VERY important" (his Claude Artifacts ranking test).
- **First sentence of body contains the keyword and answers the search intent immediately.** Answer above the fold, before scroll.
- **TL;DR summary at page top** — +33% conversion in his tests. (Already in spec §5.7; now with a number behind it.)
- **Short beats long for buyer intent.** 3,000-word fluff targets language everyone else targets; compact pages fill gaps Google can't otherwise fill.

## 3. PAA (People Also Ask) systems

- **PAA Funnel:** capture all PAA questions for the target keyword → write ~120-word answers → publish under a `/keyword-faq/` subfolder → internal-link from FAQ pages to the BOFU/Compact pages.
- **PAA Atomization (stronger claim):** one **dedicated page per question**, not accordions, not one FAQ page. Rationale: Google doesn't index hidden accordion content effectively; separate pages maximize crawlable surface and LLM query fan-out surface area.
- **ContentFTE mapping:** keep the on-page FAQ block (UX + FAQPage schema, spec §5.7) AND generate dedicated PAA pages for high-value questions. Both — the page serves readers, the atomized pages serve crawlers. Eval agent checks PAA coverage from alsoasked-style data.

## 4. LLM / GEO tactics (getting cited by AI)

- **Query Fan-Out pages:** observe what queries LLMs actually run when answering questions in your niche → create individual pages targeting those exact queries. These are BOFU by nature — LLMs query specifics, not broad topics.
- **"Best X for Y" self-first listicles:** ChatGPT loves these (43.8% of page types analyzed for relevant prompts) and cites them even when the author ranks themselves first. Rules: keep them a **fraction** of output, link out to competitors, write neutrally, demonstrate research, **keep updated** (79.1% of cited ones were updated in 2025; recency matters enormously). Underused in ecommerce.
- **Win-announcement posts:** blog posts announcing your wins get cited by ChatGPT. Publish them.
- **Press releases for SEO + LLMs:** AB Newswire ($6–80/release). Keyword in title, subheading, opening sentence. Compounds traditional rankings AND LLM citations. Underused = asymmetric opportunity.
- **Bing AI Performance Report:** use it to find weak spots in Microsoft AI coverage — fixing those fixes AI coverage broadly (same grounding across engines).
- **Google Preferred Sources:** 5-minute setup; users who add you as a preferred source see more of you. Worth a setup guide per client site.
- **Parasite SEO (awareness, use carefully):** LinkedIn posts and similar high-authority surfaces get cited in AI Overviews. Legitimate use = publish real content on high-authority platforms; don't spam.

## 5. Authority & link building

- **PageRank Decay Routing:** point external backlinks at `/services/` (money pages), not just the homepage — prevents PageRank pooling at the root instead of converting pages.
- **Topical Authority Shaping:** actively control anchor text pointing at the site; use consistent, precise terminology across all surfaces. Authority is built deliberately, not accumulated passively. (This is why the internal-link agent controls anchors, spec §5.6.)
- **Topical authority compounds:** content ranks for keywords it isn't even optimized for once the cluster is strong — the reason to build clusters, not one-offs.
- **Niche podcast guesting:** be a guest on niche podcasts → high-quality backlinks + brand mentions LLMs pick up. (Also: run your own show and clip it.)
- **Featured.com free tier:** free expert-quote placements = exposure + backlinks + social proof.
- **"Cheap" modifier + $50 micro-influencers:** target "cheap X" keyword variants; pay micro-influencers ~$50 for mentions that drive rankings, clicks, AND LLM mentions.
- **No black-hat indexing on your own sites.** GSC submit + white-hat links is enough. (Churn-and-burn gets Search Consoles penalized — his guests' cautionary tales.)

## 6. Internal linking (Sturm-flavored)

- Authority flow matters more than total backlinks: **every important page max 3 clicks from homepage.**
- Hub pages link prominently to Compact/BOFU pages; every guide links 2–3 relevant money pages; guides show 3–4 related guides (no dead ends).
- Strong pages (homepage, hubs) deliberately link to pages you want to lift.
- (Maps to spec §5.6 + orphan rescue §5.10 — the agent now has explicit depth/role rules, not just "add links".)

## 7. Refresh & decay (matches spec §5.10)

- **Content Refresh Protocol:** identify underperformers → update and improve → **republish under a new URL → 301 redirect old → new.** (Stronger than just updating in place.)
- **Content refreshes double traffic** — his case studies. The GSC decay job (§5.10-1) should use republish+301 for major refreshes, in-place update for minor ones.
- Recency is a citation factor for LLMs too (79.1% of cited listicles updated in 2025).

## 8. Coverage multiplication (one keyword, many surfaces)

- **Maximize Coverage:** one target keyword → one web page + one YouTube video + IG/TikTok/FB versions, published simultaneously.
- **YouTube Shorts rank on Google for years** (his Shorts from 2024 still page 1). **Facebook Page posts rank within hours** (his testimonial video ranked for "Compact Keywords Review" in 5 hours).
- **Target competitor brand names with video:** videos surface under competitor brand searches before buyers choose.
- **ContentFTE mapping:** Phase 1 = web page. The video/social multiplication is a Phase 2 or Factory upsell input — but the brief agent should already output a "video script seed" (title + 3 bullet talking points) per article so the surface expansion is ready when the client wants it.

## 9. Local SEO (Factory-critical)

- **GBP changes trigger a full-site Googlebot crawl** ("the whole damn thing") — Google re-validates the site as the authoritative data source behind the GBP. Implication: keep the website thorough, detailed, review-rich, and **consistent** with GBP data.
- **The website is the verification database** for the Knowledge Graph — entity consistency (name, address, hours, services) across site ↔ GBP is a ranking input.
- Reviews on-site convert consideration-stage buyers; AI-generated fake reviews are an active brand threat — monitor.

## 10. What NOT to do

- No churn-and-burn tactics, no black-hat paid indexing on client sites.
- Don't spam "Best X for Y" listicles — a fraction of output, or they stop working.
- Don't build 3,000-word fluff targeting the same language as everyone else.
- Don't run accordion-only FAQs and expect them indexed (see §3 debate).
- Don't do SEO before the basics work: crawlability, indexation, site structure first ("don't sprint before you can crawl — or be crawled").

---

## Engine wiring

| Playbook section | ContentFTE stage | Status |
|---|---|---|
| §1 Compact Keywords | Factory service/location page templates (§5.10-5) | Spec'd |
| §2 On-page structure | Draft agent system prompt; eval checklist | Add to prompts |
| §3 PAA funnel + atomization | Brief agent (PAA capture) + dedicated PAA page generator | New work |
| §4 GEO tactics | Brief agent (fan-out queries, listicle/press-release flags) | Partially spec'd |
| §5 Authority/links | Internal-link agent (anchor control); outreach backlog (podcasts, Featured.com) | Partially spec'd |
| §6 Internal linking | Internal-link agent rules | Harden per above |
| §7 Refresh protocol | GSC decay job (§5.10-1): add republish+301 path | Extend |
| §8 Coverage multiplication | Brief agent outputs video script seed | New, cheap |
| §9 Local SEO | GBP consistency checker per site; review monitoring | New work |

**Maintenance:** re-check edwardsturm.com/articles monthly; append new tactics with source + date. Tactics are never removed silently — mark superseded with the reason.

---

# Part 2 — Daniel Agrici (@AgriciDaniel)

**Source:** Agrici Daniel — AI marketing systems architect. `claude-seo` (18.2k stars, MIT): 26 sub-skills + 19 sub-agents — technical SEO, E-E-A-T, schema, GEO/AEO, agent readiness. `claude-blog` (2.3k stars, MIT): 30 sub-skills, 5 agents, 5-gate Blog Delivery Contract (blocks delivery below 90, iterates up to 3x — same philosophy as our gate). YouTube: practical AI marketing systems, n8n automation.
**Why he matters differently than Sturm:** Sturm gives you *what to do*; Agrici gives you *how to build it* — his repos are a working reference implementation (MIT licensed) for half our engine. Study the code, don't just read the tactics.
**Last updated:** 2026-10-04

> **Gray-area policy (per operator decision 2026-10-04):** gray tactics are never named in product copy, docs, or UI. We implement only their white-hat mechanism, quietly. E.g. "parasite SEO" → "high-authority platform publishing"; "indexing tricks" → "fast-indexing surfaces + GSC submission". The playbook marks these `[inspiration only]`.

---

## 11. Question-based citability scoring (GEO)

Score individual passages on how quotable they are by AI systems — aligned with Google's AI Optimization Guide. Not a vibe check: a per-passage metric (self-contained? attributed? concise?).
- **ContentFTE mapping:** new eval sub-score. The revision agent rewrites low-citability passages. This is the measurable version of playbook §4.

## 12. Image provenance metadata

Add IPTC `TrainedAlgorithmicMedia` tags to AI-generated images. Forward-looking signal as engines start distinguishing/handling AI imagery. Costs nothing at generation time.
- **ContentFTE mapping:** image pipeline writes the tag on every Klein 4B output.

## 13. Agent readiness (beyond llms.txt)

Full checklist: llms.txt ✓ (spec'd), **Markdown alternate of every article** (`.md` version at a predictable URL — agents and LLMs prefer it), WebMCP readiness, Lighthouse "Agentic Browsing" category checks.
- **ContentFTE mapping:** publish pipeline emits `article-slug.md` alongside HTML. Cheap, and it's the kind of thing competitors aren't doing yet.

## 14. Falsifiable eval guidance

Every improvement recommendation from the critic must carry: (a) the observation it rests on, (b) **"how would we know this failed?"**, (c) a leading indicator to watch. Kills vague feedback ("make it more engaging") that the revision agent can't act on.
- **ContentFTE mapping:** harden the frontier critic prompt (§5.2) — guidance without a falsifiability check gets rejected and regenerated.

## 15. Discourse research (brief input)

Mine what people are *actually saying* about the topic in the last 30 days — Reddit threads, forums, social — API-free, compiled into a brief appendix of real questions, complaints, and language. This is where PAA questions, fan-out queries, and authentic phrasing come from.
- **ContentFTE mapping:** new brief-agent step before drafting. Feeds §3 (PAA), §4 (fan-out), and Brand DNA (real audience language). Effectively free (no API).

## 16. Cannibalization detection

Before writing on a keyword, check it against the existing corpus for keyword cannibalization — not just near-duplicate text (JEV dedup covers that) but *intent overlap*: two pages that would compete for the same query get merged or differentiated at brief time.
- **ContentFTE mapping:** extend triage (JEV lane): new keyword → similarity + intent-overlap check vs published corpus → write / merge / differentiate decision.

## 17. Fact-check as a discrete gate

Separate the verification step from drafting entirely: a dedicated pass that takes the draft's statistics and checks each against its cited source (his `/blog factcheck`). Draft → fact-check → revise is more reliable than asking the drafter to self-verify.
- **ContentFTE mapping:** already the shape of our §5.3 (claim extraction → verification). Adopt his gate ordering explicitly: fact-check runs *before* the frontier eval, so the critic never wastes tokens on unverified claims.

## 18. Brand files auto-loaded (implementation pattern)

`BRAND.md` + `VOICE.md` per site, **auto-loaded into every agent's context** — not passed as a parameter that can be forgotten. Voice learned from 5–10 sample posts (`/blog style learn` equivalent).
- **ContentFTE mapping:** this is our Brand DNA (§5.1) with a concrete implementation rule: the profile is injected at the system-prompt level for brief/draft/eval/image-prompt agents, never optional.

## 19. Content templates by intent

12 templates picked by search intent (how-to, comparison, listicle, landing, etc.) — the brief agent selects the template, the draft agent fills it. Distinct from Sturm's Compact pages: these are *article* templates.
- **ContentFTE mapping:** brief agent gains a template-selection step; templates versioned alongside the playbook.

## 20. Repurpose outputs

Every article ships with platform adaptations (the brief already holds the material): LinkedIn post, X thread, short-video script seed. (Extends playbook §8.)
- **ContentFTE mapping:** draft agent emits a `repurpose/` bundle per article. Phase 1: generate and store; distribution is Phase 2/Factory upsell.

## 21. Competitor comparison pages

Generate "X vs Y" comparison pages from the brief's SERP data — matches Sturm's "X vs Y" compact-keyword pattern (§1) with a concrete generator.
- **ContentFTE mapping:** new brief type for Factory clients: "[Client] vs [Competitor]" pages, fact-checked (§17), self-first but neutral-toned per §4 rules.

## 22. Programmatic SEO planning

Cluster-based planning: seed keyword → SERP-based semantic clustering → hub-and-spoke execution plan. (His `/seo cluster` + `/seo programmatic`.)
- **ContentFTE mapping:** this is the planning layer above §5.10-5 programmatic templates — the cluster plan decides *which* pages get generated, the templates decide *how*.

## 23. Bing Webmaster + IndexNow (concrete mechanism)

Spec §5.6 says "IndexNow ping" — his implementation detail: submit via Bing Webmaster Tools API on publish. Also: GSC + GA4 + PageSpeed + CrUX as the standard API quartet for the feedback loop.
- **ContentFTE mapping:** publish pipeline calls IndexNow + Bing WMT submission; GSC API feeds the decay job (§5.10-1).

## 24. AI Share-of-Voice tracking

Prompt ChatGPT / Gemini / Perplexity / AI Overviews / AI Mode with category questions on a schedule; track brand-mention share over time. (Commercial tools: SE Ranking, Profound. Scriptable without them.)
- **ContentFTE mapping:** extends spec §5.8's "Phase 1 lite" visibility log into a real metric: share-of-voice per client, monthly. This becomes a Factory retainer report centerpiece.

## 25. Hero image ladder (alternative ordering)

His fallback chain: premium image API → direct API → stock APIs → Openverse; first working source wins. Ours (§5.9) is VLM-gated stock-first. Keep ours (cheaper), but adopt his principle: **the chain is ordered and the first working source wins — never leave a slot empty silently.**
- **ContentFTE mapping:** no change needed; noted as alignment confirmation.

---

## Engine wiring — Part 2

| Playbook section | ContentFTE stage | Status |
|---|---|---|
| §11 Citability scoring | Eval agent new sub-score; revision rewrites low passages | New work |
| §12 IPTC provenance | Image pipeline writes tag on every AI image | Cheap add |
| §13 Agent readiness | Publish emits `.md` alternate; agentic checks | New, cheap |
| §14 Falsifiable guidance | Critic prompt hardened; guidance without fail-check rejected | Prompt work |
| §15 Discourse research | Brief agent new step (API-free) | New work |
| §16 Cannibalization | Triage extended: intent-overlap check | Extend JEV lane |
| §17 Fact-check gate ordering | Fact-check before frontier eval | Reorder |
| §18 Brand files auto-load | System-prompt-level injection, never optional | Implementation rule |
| §19 Intent templates | Brief agent template selection | New work |
| §20 Repurpose bundle | Draft emits platform adaptations; stored | New, cheap |
| §21 Comparison pages | New brief type for Factory clients | New work |
| §22 Cluster planning | Planning layer above programmatic templates | Phase 1.5 |
| §23 Bing WMT + IndexNow | Publish pipeline submission calls | Concrete mechanism |
| §24 Share-of-voice | Monthly metric; retainer report centerpiece | New work |
| §25 Image ladder | Alignment confirmed with §5.9 | No change |

**Study list (MIT, free):** `github.com/AgriciDaniel/claude-seo` (audit/GEO implementation), `github.com/AgriciDaniel/claude-blog` (5-gate contract, 12 templates, 22 references). His YouTube builds the systems live — worth an hour for the n8n automation patterns even though our stack is Python.
