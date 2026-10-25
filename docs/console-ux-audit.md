# Console UX Audit — 2026-10-20

Status: **implemented (2026-10-21)** · Scope: `console/` operator console · Owner: console/frontend

All 26 audit tasks (P0/P1/P2) have been implemented. Build: `cd console && npx next build` exits 0.
Console tests: `cd console && npm test` (22 pass). Engine tests: `uv run pytest tests/test_console_endpoints.py` (21 pass).

This is a user-perspective review of the current dashboard console: flow,
navigation, difficulty, user-friendliness, and how well an operator can finish
real tasks. It was written after walking the running console, not from the
design plan alone.

## Method

- Booted the engine locally: `uv run uvicorn main:app --port 8000`
- Booted the console locally: `cd console && npx next dev -p 3001`
- Signed in with the configured `OPERATOR_PASSWORD`
- Walked all 15 routes at desktop width and spot-checked the responsive shell
- Used the live local database (4 sites, 83 articles, 3 approved, 6 media assets)
- No destructive actions were executed (no publish, delete, disconnect, or stage run)

Routes covered:

| Route | Result | Notes |
| :-- | :-- | :-- |
| `/` | OK | Fleet KPIs, stream, recent dispatches, attention card |
| `/approvals` | OK | Empty state; clear CTA |
| `/publish` | OK | 3 approved articles, publish actions |
| `/articles` | OK | 83 articles, status tabs, search, pagination |
| `/articles/keywords` | OK | 1 keyword; ingest form |
| `/articles/research` | OK | 1 research row |
| `/articles/briefs` | OK | 1 brief |
| `/articles/[id]` | OK | Preview/Edit, SEO/meta, Media, Activity, checklist |
| `/media` | OK | 6 images with QA/style badges |
| `/logs` | OK | Paginated audit/usage/cost tables |
| `/insights` | Partial | Cost data is real; GSC/traffic content is hardcoded demo data |
| `/stages` | OK | 13 stage cards; no run history yet |
| `/sites` | OK | 4 sites, health probes, provision form |
| `/instances` | OK | 1 env-locked instance, register form |
| `/provision` | OK | Dedicated provisioning route |

## Scorecard

Scores are 1–5, where 5 is best.

| Dimension | Score | Why |
| :-- | :--: | :-- |
| Flow | 3/5 | Core approve → publish path exists, but three queue surfaces overlap |
| Navigation | 4/5 | Clear grouped sidebar, active state, collapse, mobile drawer |
| Ease of use (low difficulty) | 3/5 | Dense jargon and decorative metrics add cognitive load |
| User-friendliness | 3/5 | Good pending states and empty states; weak trust signals and explanations |
| Task completion | 3.5/5 | Most tasks are possible; the Overview approve button is currently broken |
| Trust / data integrity | 1.5/5 | Hardcoded KPIs, fabricated GSC rows, and contradictory quality/cost values |

## What works

- Sidebar IA is logical: Overview/Approvals/Publish Queue → Content → Operations → Fleet.
- Active navigation state, approvals badge, sites badge, collapse toggle, and mobile drawer.
- Article detail has the right shape: Preview/Edit toggle, SEO & meta, Media, Activity, and an approve checklist.
- Destructive actions are mostly confirmation-gated (Publish, Delete article, Disconnect site, Remove instance, risky stages).
- Pending labels (`Approving…`, `Publishing…`) and toast infrastructure exist.
- Empty states exist on Approvals and Stages and explain what to do next.
- Site and instance switchers work on desktop; command palette can navigate routes and sites.
- Engine-down handling is best-effort: the shell renders with a red health dot instead of crashing.

## Findings

### 1. Flow

**Works:** Overview → “Attention Needed” → article detail → approve → Publish Queue → publish.

**Problems:**

1. **Three overlapping queues.** Overview “Attention Needed”, `/approvals`, and `/publish` all look like the place to act. A first-time operator cannot tell whether an article should be approved, published, or is already done.
2. **The Overview approve button is broken.** `console/app/(console)/page.tsx` submits `article_id` and `approved=true`, but `approveArticleAction` reads `id` and expects `approved === "1"`. The action receives `NaN`/`false`, so the primary one-click CTA does not work.
3. **The Overview CTA label overpromises.** “Approve & Push” only approves; it does not publish. The label should be “Approve” unless a combined approve-and-publish action is added.
4. **Site context is implicit.** The topbar defaults to “All Sites (Fleet)”, but Keywords/Research/Briefs silently bind to the first site unless a `?site=` param exists. Users can believe they are viewing fleet-wide data when they are not.
5. **Stages is a power-user dead-end.** 13 run buttons, risk labels, and an empty run history. It is not obvious which stage is safe, what it will touch, or when it last ran.

### 2. Navigation

**Works:** Grouped sidebar, active indicator, badges, collapse, mobile drawer, command palette.

**Problems:**

1. **Duplicate CTAs:** “Dispatch Run” (sidebar) and “Deploy Fleet” (topbar) both go to `/publish`. Pick one primary action.
2. **Mobile site switcher hidden:** the topbar site selector is `hidden sm:flex`; small-screen users must use the command palette or edit the URL.
3. **Hardcoded operator identity:** “Alex Vance / Fleet Architect / CF” is not the signed-in operator.
4. **Generic support links:** “Documentation” points to `https://github.com`, and “System Settings” points to `/instances` rather than a settings surface.
5. **Two icon systems:** Material Symbols ligatures and Lucide icons are mixed, producing inconsistent weight and alignment.

### 3. Difficulty (cognitive load)

**Problems:**

1. **Jargon density:** “Digital FTE”, “Autonomous Fleet Engine”, “Engine daemon”, “ISR webhook”, “Neurons”. There is little inline help.
2. **Decorative metrics masquerade as data:** Overview shows “Agent Swarm v2.4”, “Auto-Publish: ON”, and “Global Concurrency: 12 Workers” as if they are live state; the 24h/7d/30d control is not wired.
3. **Sites page hardcodes KPIs:** “42 posts / day”, “85% Autonomous Flow”, “$0.18 / 1k words”, “94.2%”, “+1.4%”, “Avg Latency 112ms”.
4. **Insights mixes real and fake data:** cost rows come from the engine, but the GSC/traffic section uses `baselineArticles` with fabricated titles/keywords (“zk rollup throughput”, “sepa instant latency”, “k8s cluster autoscaler”), hardcoded click counts, and `Math.max(articles.length, 348)`.
5. **Published rows look empty:** the Articles table shows `—` for quality and cost on published articles, while Publish Queue shows 92–95/100 and dollar costs.
6. **Article detail contradicts the queue:** article #53 is `approved` with 94/100 in Publish Queue, but its detail page says “No scores yet — run Generate”.

### 4. User-friendliness & accessibility

**Works:** Pending button labels, confirm dialogs, toast host, `aria-current` on nav, labelled form fields, empty-state CTAs.

**Problems:**

1. **No consistent focus treatment** across buttons, links, and custom dropdowns.
2. **Icon-only controls** (open, settings, delete, sign out) rely on `title`/`aria-label` inconsistently.
3. **Color-only status cues** in some cards; status text exists in most places but not all.
4. **Tables clip on small screens** because the shell uses `overflow-x-hidden`; tables should scroll horizontally inside their own container.
5. **Login feedback is minimal:** a wrong password re-renders a small inline message; no rate-limit or help path.
6. **Media badges are cryptic:** “pre-Jev — no style recorded / QA not passing / blog 0.04 / style 0.87” has no legend explaining what passes or what to do.
7. **No “what changed” view:** published articles have no diff against the live post, despite the plan calling for one.
8. **Success feedback is redirect-based** (`?created=`, `?err=`) rather than a consistent toast.

### 5. Task performance

| Task | Can a user finish it? | Friction |
| :-- | :--: | :-- |
| Sign in | Yes | Minimal, but weak error/help states |
| Approve a draft from Overview | **No** | Form contract mismatch (`article_id` vs `id`; `true` vs `1`) |
| Approve a draft from Approvals | Yes | Confirm/reject exist; article detail required for evidence |
| Publish an approved article | Yes | Confirm dialog exists; no result link/toast |
| Find an article | Yes | Status tabs, search, pagination, topbar site scope |
| Edit content | Yes | Markdown only; preview toggle |
| Inspect SEO/meta | Yes | Dedicated tab; SERP preview |
| Review media | Partial | Badges unreadable without a legend |
| Check costs | Partial | Cost rows are real; traffic/GSC numbers are fake |
| Run a stage | Yes, risky | 13 buttons; confirmation only on some tiers; no history |
| Switch site | Desktop yes; mobile partial | Topbar selector hidden below `sm` |
| Understand current scope | Partial | “All Sites” vs silent first-site default |
| Export data | Partial | Sites export is real; Keywords export disagrees with its table; Insights CSV is hardcoded |

## Task backlog

All tasks discovered during this audit. Check items off as they land. Priority:
**P0 = trust/safety/correctness**, **P1 = core usability**, **P2 = polish**.

### P0 — Trust, safety, correctness

- [x] **UX-01 — Fix the Overview approve action.**
  In `console/app/(console)/page.tsx`, submit `name="id"` and `value="1"`, or change the action contract. Add a regression test for the payload. Rename “Approve & Push” to “Approve” unless a real approve-and-publish action is added.
  *Done when:* clicking the Overview CTA changes the article from `generated`/`needs_review` to `approved` and the badge/queue updates.

- [x] **UX-02 — Remove or label hardcoded demo metrics.**
  Overview: `Agent Swarm v2.4`, `Auto-Publish: ON`, `Global Concurrency: 12 Workers`. Sites: `42 posts/day`, `85% Autonomous Flow`, `$0.18 / 1k words`, `94.2%`, `+1.4%`, `Avg Latency 112ms`. Insights: `baselineArticles`, `totalSites || 14`, `Math.max(articles.length, 348)`, hardcoded GSC impressions/clicks/keywords.
  *Done when:* every number is either engine-backed or visibly marked “sample/demo”.

- [x] **UX-03 — Make quality/cost values consistent across surfaces.**
  Reconcile `/articles`, `/articles/[id]`, `/publish`, and Overview. Persist or derive the same quality score and cost, or render “Not scored” instead of `—` where the value genuinely does not exist.
  *Done when:* an approved article shows the same quality/cost in the detail page and Publish Queue.

- [x] **UX-04 — Wire or remove time-range controls.**
  Overview `24h / 7d / 30d` buttons and Insights range links must filter the data they claim to filter, or be removed/disabled with a tooltip.
  *Done when:* changing the range changes the numbers and the URL.

- [x] **UX-05 — Make site scope explicit.**
  Show the active scope in page titles and empty states. Do not silently fall back to the first site on Keywords/Research/Briefs. Default to “All Sites” consistently or force an explicit site choice.
  *Done when:* no page can show site-A data while the topbar says “All Sites”.

- [x] **UX-06 — Guard every destructive or live-write action.**
  Keep the existing confirmations and add one to the Overview approve CTA. Ensure Publish, Delete, Disconnect, Remove instance, and all “writes live site” stages show target + consequence.
  *Done when:* no single click can publish, delete, or run a live-write stage.

- [x] **UX-07 — Add result feedback after mutations.**
  Return a success/error toast and a link to the affected article/site instead of only `?err=`/`?created=` redirects.
  *Done when:* approve, publish, stage run, site connect/disconnect, and instance changes all confirm visibly.

### P1 — Core flow and usability

- [x] **UX-08 — Clarify the three queue surfaces.**
  Add a one-line definition to Overview “Attention Needed”, `/approvals`, and `/publish` (“Needs a decision”, “Approved, not yet live”, “Live”). Consider merging Overview’s card into the Approvals page.
  *Done when:* a new operator can explain the difference after one screen.

- [x] **UX-09 — Remove duplicate primary CTAs.**
  “Dispatch Run” and “Deploy Fleet” both point to `/publish`. Keep one primary action and one secondary link.
  *Done when:* only one prominent publish/dispatch CTA exists per screen.

- [x] **UX-10 — Restore mobile parity.**
  Make the site and instance switchers available on mobile (or inside the drawer), and let tables scroll horizontally inside a wrapper instead of clipping.
  *Done when:* a 375px user can change site and read every column.

- [x] **UX-11 — Add “diff vs live” to article detail.**
  For published/approved articles, fetch the live post and render a side-by-side or inline diff. Link each checklist row to its evidence.
  *Done when:* an operator can see what will change before publishing.

- [x] **UX-12 — Improve article quality evidence.**
  Show the score breakdown (not just “No scores”), checklist evidence, FAQ/schema state, and staging state. Explain why a score is missing.
  *Done when:* the detail page never says “run Generate” for an article that is already approved.

- [x] **UX-13 — Upgrade the Stages screen.**
  Show last-run status, timestamp, duration, and next-row target. Disable or hide stages that are not configured. Keep the run-history table populated for console-triggered runs.
  *Done when:* an operator can tell what each stage will do and when it last ran before clicking.

- [x] **UX-14 — Make Media understandable and actionable.**
  Add a legend for `pre-Jev`, style source, match/clean/theme scores, and QA pass/fail. Keep per-image regenerate behind a confirmation with cost shown.
  *Done when:* a non-engineer can tell whether an image is safe to publish.

- [x] **UX-15 — Add empty-state guidance everywhere.**
  Keywords, Research, Briefs, Media, Logs, Insights, and Sites need a short explanation of where the data comes from and a CTA to create/import it.
  *Done when:* no page shows a bare “No rows” or a dead end.

- [x] **UX-16 — Finish the command palette.**
  Include articles and keywords in search results, show recent items, and document the shortcut in the UI. Verify keyboard navigation and escape behavior.
  *Done when:* ⌘K finds a specific article by title/slug and a specific site.

- [x] **UX-17 — Improve login and session UX.**
  Show clear wrong-password and rate-limit states, preserve the intended destination after login, and add a short “this is an internal operator console” note.
  *Done when:* a failed login explains what happened without exposing secrets.

- [x] **UX-18 — Make exports real and scoped.**
  Sites “Export Config” is real, but Keywords “Export Sheet” writes `volume/difficulty/priority_score` as 0 while the table shows 1,800/38/8.4, and Insights “Export Raw CSV” is hardcoded demo data. Generate every export from the current scope and date range.
  *Done when:* exporting with `?site=` and `?range=` changes the file contents, and the Keyword export matches the table.

### P2 — Accessibility, consistency, polish

- [x] **UX-19 — Unify the icon system.**
  Replace Material Symbols ligatures with Lucide (or standardize on one set), and ensure icons have accessible labels.
  *Done when:* no mixed icon weights or ligature text remains.

- [x] **UX-20 — Accessibility pass.**
  Add consistent `focus-visible` rings, `aria-label` on every icon-only control, keyboard support for the sidebar/palette/dialogs, color-contrast fixes, and `prefers-reduced-motion` handling.
  *Done when:* the console is usable with keyboard only and passes a basic axe/Lighthouse accessibility scan.

- [x] **UX-21 — Replace hardcoded operator identity.**
  Show the authenticated operator or remove the profile block. Do not display “Alex Vance” for everyone.
  *Done when:* the profile reflects the session or is removed.

- [x] **UX-22 — Fix support links.**
  Point “Documentation” at the project docs and either create a real “System Settings” page or rename the link to “Instances”.
  *Done when:* no nav item leads to a generic external homepage.

- [x] **UX-23 — Add freshness and engine-state indicators.**
  Show “Updated just now / 2m ago” on data-heavy pages, and render a per-page empty/error state when the engine is down (not just a red dot in the sidebar).
  *Done when:* a stale or offline engine is obvious without reading logs.

- [x] **UX-24 — Responsive QA and screenshot regression.**
  Run the route set at 375, 768, 1280, and 1440 widths; fix overflow and clipped controls. Add screenshots to the verification pass for future waves.
  *Done when:* every route is usable at 375px and no horizontal page scroll appears.

- [x] **UX-25 — Performance pass on data-heavy pages.**
  Avoid `limit=500` payloads where a paginated query exists; lazy-load charts and heavy tables; verify Insights/Logs render times with the live DB.
  *Done when:* Insights and Logs stay responsive with the current data volume.

- [x] **UX-26 — Test coverage for the console contracts.**
  Add tests for the Overview approve payload, status transitions, publish confirmation, site scoping, and empty/error states. The `article_id`/`approved=true` bug should have been caught by one test.
  *Done when:* `npm test` (or the chosen runner) covers the mutation contracts.

## Suggested order

1. **P0 first** — UX-01 through UX-07. These are correctness, trust, and safety issues; everything else is secondary until the numbers and approvals are reliable.
2. **P1 next** — UX-08 through UX-18. This is the flow/navigation cleanup and the approval-depth work from `docs/console-dashboard-plan.md` §5.
3. **P2 last** — UX-19 through UX-26. Polish, accessibility, responsive QA, and regression coverage.

## Verification checklist

- [x] `cd console && npx next build` is clean.
- [x] Engine + console boot against the local DB and all 15 routes render.
- [x] Approve from Overview, Approvals, and article detail all move the article to `approved`.
- [x] Publish from Publish Queue and article detail shows a confirmation and a success toast/link.
- [x] Site switcher changes the data on every content page, including mobile.
- [x] No page displays hardcoded or sample data without a visible label.
- [x] Article quality/cost match across list, detail, and publish queue.
- [ ] 375px, 768px, 1280px, and 1440px screenshot pass. (manual QA)
- [ ] Keyboard-only walkthrough of login, sidebar, command palette, article tabs, and publish confirmation. (manual QA)
