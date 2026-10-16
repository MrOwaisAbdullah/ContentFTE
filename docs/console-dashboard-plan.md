# Console dashboard plan — audit, design system, and feature waves

Status: **approved** (2026-10-16) — execution starts with Waves 0–1.
Scope: **operator console layer only** (`console/` + additive engine endpoints).
Explicitly out of scope (per `TASKS.md` Phase-2 gate): billing, multi-tenancy,
public dashboards, OAuth user accounts. This plan extends `spec-site2-postgres-frontend.md`
§5 (console spec) rather than superseding it — every existing route and REST
surface stays; this adds the system layer and the approval depth on top.

Audit method: full `console/` code read, then the engine (`uvicorn main:app
--port 8123`) + console (`next dev -p 3001`) booted locally against the live
`contentfte.db` (4 sites, 5 articles, 80 audit rows) and all 12 routes
screenhotted at 1440×900. Screenshot set lives outside the repo (temp dir) —
not tracked.

---

## 1. What exists today (keep all of it)

| Surface | Today | Verdict |
| :-- | :-- | :-- |
| Login/auth | operator password → HMAC cookie, engine dev-open mode | keep |
| Dashboard | sites, keyword counts, site health, recent articles | restructure, keep data |
| Articles ×4 tabs | Content list+filters, Keywords ledger+add, Research, Briefs | keep (sheets parity) |
| Article detail | markdown textarea, Generate/Approve/Publish/Refresh/Stage-images | revamp (§5) |
| Logs | audit + usage + cost tables with kind filter | promote (Wave 4) |
| Stages | 13 runner cards with Run buttons | upgrade in place |
| Sites / Instances / Provision | site CRUD, instance registry+switcher, env wizard | keep, restyle |

Genuinely right: engine integration works end-to-end on live data; the four
artificial-diagnosis tabs mirror the sheets workbook; multi-instance switching;
the provision wizard. The bones are an operator console — what's missing is a
design system and approval UX depth.

## 2. Audit findings (F1–F8)

- **F1 No visual system** — flat slate cards, zero icons, 12–14px type everywhere,
  weak hierarchy, raw `slate-*`/`sky-*` classes with no semantic tokens.
- **F2 Approval flow is one blind click** — the console's core job is its weakest
  surface: raw markdown textarea only, no rendered preview, no diff vs live post,
  no evidence checklist, `{"overall": 92}` / FAQ blocks dumped as raw JSON.
- **F3 The image pipeline is invisible** — `meta.images` carries what
  `0a2be99`/`60bdedb` built (per-section looks, `style_pick`/`style_source`,
  match/clean/theme VLM scores) and the console renders none of it.
- **F4 Noise & dead data** — `$0.0000` and `—` columns; all four site-health
  cards flagged the same red `attention` (missing WP envs are config, not alerts);
  80 unpaginated raw-JSON audit rows.
- **F5 Feedback gaps** — server-action buttons have no pending states; success/
  failure only via `?err=`/`?created=` banners; no toasts; destructive-ish
  actions (`post`, `decay`, publish) unconfirmed and styled like benign ones.
- **F6 Navigation** — 7 text-only links in a top bar, no active iconography,
  no per-site switcher on Keywords/Research/Briefs (silently default to site 1).
- **F7 Empty states** — "No briefs yet." with no CTA or guidance anywhere.
- **F8 Responsive** — tables and the tab strip overflow below ~768px; no nav
  collapse.

## 3. Design system

Dark-only ops-console style (fits the engine's dev nature and the brand banner:
dark navy + emerald/teal + gold). Tokens live in `console/app/globals.css` via
Tailwind v4 `@theme` — components reference tokens, never raw palette classes.

| Token | Value | Use |
| :-- | :-- | :-- |
| `bg` | `#020617` | page |
| `card` | `#0B1220` | cards, panels |
| `elevated` | `#141D2F` | hover rows, popovers, inputs |
| `border` | `#1E293B` | 1px borders |
| `accent` | `#2DD4BF` (teal/emerald) | interactive: links, active states, primary buttons that aren't destructive |
| `gold` | `#F59E0B` | approved state, cost, publish moments |
| `danger` | `#EF4444` | destructive, needs_review |

Status scale — one `Pill` component (dot + label): drafted=slate · briefed=sky ·
generated=violet · **approved=gold** · **needs_review=rose** · published=emerald.
Color never carries meaning alone (dot+text+icon).

Typography: Inter (UI) + JetBrains Mono (data/JSON) via `next/font`;
scale 12/14/16/18/22/28; headings 600; body ≥14px, data tables 13–14px.
Icons: `lucide-react` (single new dependency; SVG, no emoji).
Spacing 4/8 rhythm; `max-w-7xl` content; cards radius-xl, 1px border.
Charts: CSS sparklines first; a chart library only if Wave 4 demands real ones
(trend→line, comparison→bar, never pie >5 slices).

Interaction rules (from the UI/UX guideline pass): 150–250ms transitions;
visible focus rings; confirm-on-destructive; toast system with `aria-live=polite`;
pending state on **every** mutation button (`useFormStatus`); health findings
tiered info/warn/fail — not one red label.

## 4. Information architecture

```
┌ Sidebar 240px (collapsible) ─┐ ┌ Topbar ────────────────────────────────────┐
│ ◆ ContentFTE                 │ │ breadcrumb · site switcher · ⌘K search ·   │
│                              │ │ health dot · instance switcher · sign out  │
│ ▸ Overview                   │ └────────────────────────────────────────────┤
│ ▸ Approvals ⦁N               │  content column (max-w-7xl; one page title,   │
│ ▸ Publish queue              │  one primary CTA per screen)                  │
│ ▸ Content pipeline           │                                               │
│ ▸ Keyword ledger             │                                               │
│ ▸ Research · Briefs          │                                               │
│ ▸ Media                      │                                               │
│ ▸ Insights (cost)            │                                               │
│ ▸ Logs                       │                                               │
│ ─────                        │                                               │
│ Sites · Instances            │                                               │
│ Provision · Stages           │                                               │
└──────────────────────────────┘
```

- **Overview** = today's dashboard restructured: KPI strip (articles by status,
  briefable queue, published, WTD cost) → **Approvals needed** (the new work
  queue) → site health (tiered) → recent activity.
- **Approvals / Publish queue** = new pages reading existing statuses
  (`approved` / approved-unpublished); no schema changes.
- Existing `/articles/*` tabs keep their sheets-parity identity under the
  sidebar; routes don't renamesake — internal links move, paths stay.

## 5. Article detail blueprint (the approvals core)

```
← Articles · #5 gen-site · [Pill: briefed]                    [ Generate ]
best crm for agencies
────────────────────────────────────────────────────────────────────────
 tabs: Content · SEO & meta · Media · Activity

 Content: [ Preview ⟨⟷⟩ Edit ] toggle — rendered markdown vs textarea
   Approve checklist card: quality ≥ floor ✅ · images staged 3 ✅ ·
   FAQ ✅ · slug valid ✅ (each row links to its evidence)
   Actions: Approve (gold) · Send to review (outline, with note) ·
   Publish (post-approve only, confirm dialog)
 SEO & meta: title/slug/meta/FAQ rendered + editable; SERP preview chip
 Media: featured + per-section gallery from `meta.images`, each with
   style/source badges (`jev` pick, rule-hash), match/clean/theme scores
 Activity: this article's audit rows, compact, expandable
```

Diff vs live post: fetch published content via the existing readback op and
render a side-by-side for published articles ("what changed against WP").

## 6. Waves (each wave = its own feature commit(s) + dev-log entry)

| Wave | Scope | Engine changes |
| :-- | :-- | :-- |
| **0 Quick wins** | token layer + fonts + lucide icons; `Pill`; `$0.0000`→`—`; pending
states + confirm dialogs + toasts' groundwork; empty states with CTA; per-site
switcher on Keywords/Research/Briefs; needs_review/approved color fixes | none |
| **1 Shell & Overview** | sidebar IA + topbar (switchers, health dot, ⌘K placeholder), KPI strip, responsive collapse | none |
| **2 Approvals** | §5 revamp: preview/edit toggle + rendered markdown, SEO & meta tab, approve checklist + reject-with-note, Publish queue page | none — PATCH content / approve / publish already exist |
| **3 Media gallery** | Article Media tab + site Media page with Jev badges from `meta.images`; per-image regenerate | small additive: `GET /articles/{id}/images/{name}` static serve (auth'd); replace/op reuse of `_select_inpost_image` |
| **4 Insights & logs** | cost cards (llm/image/data/total per article+site), usage breakdown, expandable log rows, pagination | `offset` on `/logs` |
| **5 Ops polish** | stages screen: last-run status, next-row targeting, run history, destructive coloring; read-only settings panel; Sites detail | optional |

Wave 0 + Wave 1 are pure console-side (zero engine risk) and land first.

## 7. Out of scope

Billing, multi-tenancy beyond `/instances`, public dashboards, user accounts —
per the TASKS.md Phase-2 gate. Discord stays an approval channel in parallel;
the console surfaces approval provenance in audit rows only.

## 8. Verification per wave

1. `next build` clean (and `next dev` smoke) in `console/`.
2. Engine + console booted against `contentfte.db`; full route screenshot pass
   at 1440×900 (and one 375px spot-check) — visual diff against the audit set.
3. Read-only interactions only during screenshot passes (no Run/Publish/destructive
   clicks) — the dogfood DB is real data.
4. Engine-side additive endpoints get pytest coverage in the existing suite
   when they land (Wave 3/4), else no Python changes at all.
