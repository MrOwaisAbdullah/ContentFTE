# Brief Research

## Discourse research (API-free)
- **Tactic:** Mine what people are *actually saying* about the topic in the last 30 days — Reddit threads, forums, niche communities, social posts. Compile real questions, complaints, and phrasing into a brief appendix.
- **Why:** This is where PAA questions, fan-out queries, and authentic audience language come from. SERP tools show what ranks; discourse shows what people want.
- **Rule:** Append the top 10–15 verbatim questions/phrases to every brief. Use their wording in H2s where natural.
- **ContentFTE wiring:** New brief-agent step, runs before SERP analysis. Effectively free.

## SERP-gap analysis
- **Tactic:** Pull top-3 ranking pages' headings. Identify 3 subtopics they all miss — that's the unique angle.
- **Why:** "Better than #1" loses; "covers what #1–3 miss" wins.
- **Rule:** Brief must name the 3 missed subtopics explicitly. Draft must cover all 3.
- **ContentFTE wiring:** Brief agent emits the gap list; eval checks coverage.

## PAA capture
- **Tactic:** Harvest every People Also Ask question for the target query and its variants.
- **Why:** PAAs are Google's own list of sub-intents worth satisfying.
- **Rule:** High-value PAAs get dedicated pages (atomization); supporting PAAs get 2–4 sentence on-page answers + FAQ schema.
- **Atomized page spec:** one question → one page, direct answer in the first
  sentence (≤ 50 words), expanded to ~**120 words** with one concrete example;
  published under a `/keyword-faq/` subfolder and internally linked **up to the
  originating BOFU article**. FAQPage schema on the page.
  Builder: `lib/tactics.build_paa_page_spec`.
- **ContentFTE wiring:** Brief includes PAA list with atomize-vs-answer decision per question.

## Query fan-out observation
- **Tactic:** Note which sub-queries LLMs in this niche actually fan out into (test with ChatGPT/Perplexity on the topic; watch Bing AI Performance data where available).
- **Why:** GEO means ranking for the queries the AI asks on the user's behalf, not just the query the user typed.
- **Rule:** Brief lists 5–10 observed fan-out queries; each becomes a candidate page or section.
- **ContentFTE wiring:** Fan-out list feeds the cluster plan (§keyword-strategy).
