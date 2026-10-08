# Dogfood report — Next.js integration (TASKS 90)

**What was run:** an independent agent created a **fresh Next.js app** in
`test-sites/next-dogfood/` (gitignored), installed the **published** SDK
`@owais-abdullah/contentfte@0.2.0`, pointed it at the local engine, generated a
real article (847 words, score 94), published it, and rendered it end-to-end —
following **only** `skills/contentfte/SKILL.md`. This is the acceptance test for
both the SDK and the public skill.

**Result:** all acceptance checks pass (~25 min scaffold → rendered page).
Page 200 with `<h1>` + body + FAQ + Article/FAQPage JSON-LD; `/blog/<slug>.md`
serves the markdown alternate; `/llms.txt` lists the post; site key stays
server-side. **No engine code was read; the skill alone was sufficient.**

## Findings + resolutions

| # | Finding | Type | Severity | Resolution |
| :-- | :--- | :--- | :--- | :--- |
| 1 | `client.llmsTxt()` returns `{site,count,llms_txt}` JSON, but the skill implied serving it directly → raw JSON at `/llms.txt` | skill/doc + DX | high | Skill + `api.md` now say **serve `.llms_txt`** (with the exact Route Handler); client method typed `LlmsTxtResult` |
| 2 | FAQ: the React renderer emitted a **static** `<h3>/<p>` section, while the skill says "FAQ accordion" (WordPress context) — inconsistent with the engine's "FAQ is always an accordion" rule | code + doc | high | `ContentFTEFaq` now emits a native **`<details>` accordion** (shared `name="contentfte-faq"`); **`payload.faq_html`** added to the delivery payload for non-React sites; CSS + docs updated |
| 3 | Next snippet used the pre-15 **sync `params`**; Next 16 `params` are Promises (page + route handler) | doc | high | `references/stacks.md` now `await params` / `await context.params`; skill pitfall added |
| 4 | No guidance on resolving a URL **slug → article id** for `/blog/[slug]` | doc | medium | Skill + stacks show `listArticles(site,"published")` (returns `slug`) to map slug→id, or store the id at publish |
| 5 | `getContent`/`listArticles`/`llmsTxt`/`wpPost` returned `Promise<any>` — no types | DX | medium | Added exported interfaces (`ArticleSummary`, `ArticleListResult`, `LlmsTxtResult`, `WpPostResult`, `DeliveryPayload`) + method return types |
| 6 | Article title stayed the raw lowercase keyword ("best espresso machine under 500") | engine behavior | low | **Non-issue** — the engine uses the submitted keyword as the title; pass a proper `brief.title` for polished titles |
| 7 | `slug` empty on the status response (`GET /articles/{id}`) but present in `/content` | code (consistency) | medium | `service.get_article` now returns the **resolved** slug (`_resolve_slug`) on both paths |
| 8 | `create-next-app` Tailwind preflight can fight `contentfte-prose.css` | doc | low | Skill pitfall added (scope prose to `cfte-prose` / drop scaffold CSS) |
| 9 | App Router can't nest a literal `/blog/[slug].md` folder | doc | low | Stacks now show the `/blog/[slug]/md` route + `next.config.ts` rewrite |

Fixed in code: #2 (renderer + `faq_html`), #5 (types), #7 (slug). Fixed in
docs/skill: #1, #3, #4, #8, #9. Non-issue: #6.

## Follow-ups
- Re-verify on a fresh project after the fixes (the skill is now precise on
  llms.txt, FAQ accordion, Next params, slug→id, `.md` routing).
- Consider a shared `types` module so the client and renderer `DeliveryPayload`
  don't drift.
- A `.md`/`llms.txt` **convenience** helper could remove the manual extraction
  entirely (e.g. `client.llmsTxtText()`).

See also: `docs/site-onboarding-flow.md`, `skills/contentfte/`, `docs/dev-log.md`.
