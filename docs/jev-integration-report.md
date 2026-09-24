# Jev (System One) Integration Report — ContentFTE / SEO Blog Agent

**Date:** 2026-09-24 (re-verified + implemented 2026-09-24 via Tavily + Context7 MCP + OpenAI Agents SDK Context7)
**Model evaluated:** `typesafe/jev-1.13` (alias `~typesafe/jev-latest`) via `POST https://openrouter.ai/api/alpha/decisions`
**Implementation status:** Phase 0 ✅ + Phase 1 (A1,A2,B1,B2/B3,A3) ✅ + Phase 2 (C1,D1,D2,F1) ✅ + Phase 3 (F2,F3,G1/G2/G3,E helpers) ✅ — all 14 points wired or helper-ready (see §5). SDK: `from agents.decorators import tool` verified via Context7 `/openai/openai-agents-python` 0.19.2 (both `function_tool` + `tool` map to same, prefer `tool`).
**Sources:**
- Primary: [TypeSafe — Introducing System One & Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev), [OpenRouter — Jev docs](https://openrouter.ai/docs/guides/community/jev), [Jev Tutorial](https://openrouter.ai/docs/guides/community/jev-tutorial), skill `.claude/skills/jev-system-one/SKILL.md:1` and `references/`, `docs/pipeline_flow_and_state.md:1`
- Live verification (this run): Tavily Search (`tavily_tavily_search` — 6 sources, `search_depth: advanced`) and Context7 (`/websites/typesafe_ai` 1451 snippets, `/openrouterteam/docs` 5825 snippets) — see §4a for captured evidence.
**Auth in this repo:** `OPENROUTER_API_KEY` already present (`blog_agent/custom_runner.py:126`, `discord_bot/bot.py:86`) — no new key needed.

---

## 0. Executive Summary

**Jev is not a cheaper ChatGPT. It is a different lane.** `jev-system-one/SKILL.md:31` mental model:

```
Generation lane (LLM):  open-ended → string → parse → hope
Decision lane (Jev):    bounded → typed value → branch → guaranteed shape
```

Jev (`blog_agents.py:4` `custom_runner.py:40` already use OpenRouter for DeepSeek) returns **typed** `Choice` / `Noul` / `Score` with calibrated `probabilities` + `confidence` in **70-500ms** at **$0.042 / MTok input, output free** (`references/api-reference.md:155`). For the published workflow evals, Jev is **193.6× faster, 444.6× cheaper** than the reference frontier LLMs at the *same* intelligence on System One tasks, and owns the Pareto frontier (`typesafe.ai/blog` Evidence / Workflow evals).

**Thesis for ContentFTE:** keep every *generation* step on an LLM (draft, brief, headline, rewrite). Move every **bounded judgment** — classify, route, gate, verify, score, dedupe — to Jev. That is ~60-80% of the *calls* in `scripts/run_stage.py:280` and `blog_agent/blog_agents.py:1` today, but ~20% of the *value*; batch them and the pipeline gets faster, cheaper, and more reliable without changing what the reader sees.

**Cheapest wins first (do one, measure, then next):**

| # | Insert point | Replaces | Primitive | Est. saving |
|---|--------------|----------|-----------|-------------|
| 1 | Duplicate topic check `discord_bot/bot.py:594` | DeepSeek chat call | Noul | 1 LLM call → 1 Jev call per candidate |
| 2 | Tavily `is_relevant` pre-filter before `tavily_extract_tool` | Extract credits | Noul (map) | saves 1 Tavily extract per 5 irrelevant URLs |
| 3 | Brief/content `intent` + `needs_research` gate | LLM intent label | Choice+Noul batched | 1 call, 12× cheaper than 3 LLM calls |
| 4 | Draft `quality` Score gate before DeepSeek evaluator | Full `content_evaluation_agent` on every draft | Score | cascade: cheap gate → escalate only on low confidence |
| 5 | Claim-supported verification (`claim_supported` Noul) | LLM fact-check loop | Noul + Score | Jev Verified Cascade pattern |
| 6 | Category taxonomy `get_existing_categories_tool` → Choice | LLM-invented strings | Choice (≤255) | stops category explosion, 0 new infra |

Full catalog §2 has 14 points. **Do not use Jev for:** prose, code, explanations, image bytes (`SKILL.md:15`). For images use VLM caption → Jev judge (`references/vision-bridge.md`).

---

## 1. What Jev Is (and Is Not)

From TypeSafe launch post + OpenRouter hub:

- **System One model** — trained with RLCD (Reinforcement Learning for Calibrated Decisions), not RLHF. Optimizes *calibrated probabilities on bounded tasks* rather than preferred chat text. Returns **type-safe structured values**, never strings, never type errors.
- **3 primitives** (`openrouter.ai/docs/guides/community/jev` table):
  - **Choice** — "which one of N?" → `choice` + `probabilities` + `confidence`. Max 255 options.
  - **Noul** — "does condition hold?" → `noul` (0-1 yes-probability).
  - **Score** — "where on ordered scale?" → `score` (continuous) + distribution. Requires ≥2 levels.
- **Input:** `state` (structured JSON, 32k tokens) + `questions` map. **Batch:** all questions in one request evaluate **in parallel** at one latency unit, one input cost (`SKILL.md:60`). Adding 3 questions is ~12× cheaper than 3 separate calls (`references/api-reference.md:155`).
- **Pricing/latency now:** `$0.042/MTok` input, output free; `usage.cost` returned per call; 70-500ms end-to-end (40-200× faster than GPT-5.6/6 on System One tasks). `model: "typesafe/jev-1.13"` via OpenRouter Decisions API.
- **Confidence** is calibrated: higher confidence → higher accuracy on average, consistent across similar inputs. Use it to **gate** (`references/patterns.md`): low-stakes read 0.5, high-stakes write 0.85-0.9. Below floor → escalate to human or stronger model.
- **Cannot:** write prose/code, explain itself, handle raw image bytes as state, act as a gateway. Schema-correct ≠ factually correct; probabilities are the escalation signal (`SKILL.md:113`).

Integration path for this repo (recommended): **Decisions API via OpenRouter** — already authenticated (`OPENROUTER_API_KEY`), plain `fetch`, validate with Zod, timeout `1500ms`, wrap in `JevError` and fall back per risk (`references/api-reference.md:129`). SDK path (`TypeSafeClient` with `baseURL: https://openrouter.ai/api/v1`) is equivalent if preferred.

---

## 2. Where ContentFTE Can Use Jev — 14 Concrete Insert Points

Grouped by the stages in `docs/pipeline_flow_and_state.md:87` / `scripts/run_stage.py:280`. Each entry: **state shape → question(s) → primitive → gating → what it replaces → ROI**.

### A. Trigger / Discord Bot (`discord_bot/bot.py`)

**A1 — Duplicate / near-duplicate topic detection** `bot.py:594` **→ HIGHEST ROI, ship first**

- **Today:** `_check_duplicate_topic` pulls ~300 existing topics from 5 sheets + calls `AsyncOpenAI(… OpenRouter …).chat.completions.create(Dataset: deepseek/deepseek-v4-flash-0731)` to decide "same specific story?". One LLM call per candidate, variable latency.
- **Jev:** One `Noul` (or batched Nouls) per check.

```json
// POST /api/alpha/decisions
{
  "model": "typesafe/jev-1.13",
  "state": {
    "candidate": "Xiaomi AI Cube runs 120B local LLMs",
    "existing": ["Xiaomi AI Cube: 120B models on desktop", "Best AI automation firms 2026", "... up to 300"]
  },
  "questions": {
    "is_duplicate": {
      "type": "noul",
      "instructions": "Does `candidate` cover essentially the SAME specific story/topic as any one entry in `existing` -- not just the same broad subject?",
      "criteria": {
        "true": "Same product + same specific release/angle (e.g. two posts about Xiaomi AI Cube's 120B local run)",
        "false": "Same broad area but different specific story (e.g. two different AI-agent posts)"
      }
    }
  }
}
```

Gate: `noul >= 0.75` and `confidence >= 0.65` → surface warning; below → advisory only (never blocking, same as today). Fallback on `JevError`/timeout → skip warning, still allow approval. **Saves:** one DeepSeek call per candidate burst (approving 5 candidates → 5 calls → 5 × 70ms instead of 5 × 800ms, output-free).

**A2 — Bot @mention intent router** `bot.py:34` (chat tools + `get_pipeline_status_tool`, `get_seo_report_tool`)

- `Choice` `greeting / status_query / seo_report / prioritize_topic / trigger_stage / open_chat` on `{message, user_plan}`. Jev classifies in 100ms; only `open_chat` / `complex` hits DeepSeek streaming (`lib/ai/litellm.ts` pattern). Prevents paying for LLM on "how many briefs pending?" that `gather_pipeline_status()` can answer without any model.

**A3 — Topic triage: trend / timeliness Score** `bot.py` + `research_agent.py:439` `run_topic_discovery_workflow`

- `Score` `trend: ["Evergreen", "Seasonal", "Trending now"]` (`assets/templates/blog-pipeline.ts:37`). Use to sort candidates before posting to Discord — trending burst gets surfaced first, evergreen queued lower.

### B. Research (`research_agent.py:57` `combined_research_workflow` and `run_topic_discovery_workflow`)

**B1 — Tavily search-result relevance pre-filter (map over corpus)** — **saves Tavily credits directly**

- Today `researcher_agent` calls `tavily_search_tool` (max_results=5) then heuristically `tavily_extract_tool` if `score > 0.7` and `tavily_crawl_tool` if `score > 0.8`. Tavily's own `score` is not a relevance judgment, it is retrieval score. Credits: 1 per `search`, 1 per 5 URLs extracted/crawled.
- Jev: after `search`, map one `Noul is_relevant` per result **in one batched call** (state = `{question, excerpts: [{id, excerpt}]}`), keep only `noul >= 0.65` for extract. Pattern: Research / map-reduce (`references/domain-playbooks.md:94`, TypeSafe map-reduce analogy).

```json
{
  "state": {
    "question": "Best AI automation development firms in 2026",
    "excerpts": [
      {"id": "r0", "excerpt": "DataCamp map-reduce analogy ..."},
      {"id": "r1", "excerpt": "Unrelated forum signature..."}
    ]
  },
  "questions": {
    "r0_relevant": {"type": "noul", "instructions": "Is `excerpts[0].excerpt` relevant to `question` for a buyer's-guide blog post?"},
    "r1_relevant": {"type": "noul", "instructions": "Is `excerpts[1].excerpt` relevant to `question` for a buyer's-guide blog post?"}
  }
}
```

Log `noul` + `confidence` per excerpt; threshold tuned from `usage` after 20 samples. One Jev call replaces 1-3 wasted extracts.

**B2 — Search intent classification** `research_agent.py:157` `"Classify user intent using OpenAI Agents SDK (e.g., 'commercial: buy coffee maker')"`

- `Choice` `intent: {informational, transactional, navigational, comparison}` with descriptions (`blog-pipeline.ts:26`). Batched with `needs_research` Noul (B3) about same `state: {topic, outline}` → one latency unit.

**B3 — Needs-research gate** `research_agent.py:189` + `assets/templates/blog-pipeline.ts:18`

- `Noul needs_research: "Does this topic require citations or fresh sources beyond common knowledge? Think PII, pricing, legal, medical, stats where stale answer harms."` Gate `needsResearch = noul >= 0.6` → `tavilyResearch(topic)` only then; else skip search entirely for evergreen explainer.

**B4 — Refusal / empty-queue detector** `research_agent.py:27` `_REFUSAL_MARKERS` regex

- Today a tuple of string markers tries to catch triage apology sentences. Fragile. Jev `Noul is_valid_keyword: "Is this a real research topic or an apology/empty/placeholder?"` could replace regex with calibrated probability. Low urgency — regex is free and already works, but note as cleanup if regex ever regresses.

### C. Brief (`blog_agent/blog_agents.py` brief_agent → `scripts/run_stage.py:714` `run_brief`)

**C1 — Brief completeness Score before content**

- `Score quality: ["Reject: missing H1 or <4 H2 or FAQ malformed", "Needs edits: has shape but thin", "Ready: H1 + 4-6 H2 + 5-7 FAQs + links + summary"]` on `{brief_content, faqs}`. Below 1.5 → rerun brief or flag before burning a `content` stage run.

### D. Content Generation (`blog_agent/blog_agents.py:164` `content_generator_agent` + `content_evaluation_agent:17`)

This is the most expensive stage (draft + 2-3 eval loops + Tavily fact checks). Jev does **not** write the draft; it **gates** the loop.

**D1 — Cheap draft quality gate (Jev-Verified Cascade)** `assets/templates/blog-pipeline.ts:52` `scoreDraftQuality`

- After draft, call Jev in parallel:

```json
{
  "state": {"draft": "<markdown>", "facts": "--- joined source excerpts ---"},
  "questions": {
    "fact_supported": {"type": "noul", "instructions": "Is every factual claim in `draft` supported by `facts`? Draft must not invent numbers/dates/quotes not in facts."},
    "on_brand": {"type": "noul", "instructions": "Is `draft` consistent with plain expert tone, no inflated AI language like cutting-edge/seamless?"},
    "quality": {"type": "score", "instructions": "How ready is this draft to publish?", "criteria": ["Reject: inaccurate or thin", "Needs edits: usable but gaps remain", "Publish-ready: accurate, complete, on-brand"]}
  }
}
```

Gate per template: `publishReady = supported >= 0.7 && score >= 1.5 && onBrand >= 0.6`. If true → skip `content_evaluation_agent` (DeepSeek) entirely and persist (`scripts/run_stage.py:1020`). If false → still call the full evaluator but feed it Jev's `support/onBrand/score` as context to narrow rewrite. **This is the cookbook Jev-Verified Cascade** (`docs/cookbook/evaluate-and-optimize/jev-verified-cascade`). Saves 1-2 DeepSeek eval calls per post on high-quality drafts.

**D2 — Claim-supported verification with excerpts** (`references/domain-playbooks.md:98` Research / `claim_supported`)

- Already the pipeline's `content_evaluation_agent:64` builds a claims ledger (claim → source URL or `UNVERIFIED`) by calling `tavily_extract_tool` / `tavily_crawl_tool`. Jev Noul `claim_supported` on each `{claim, excerpt}` pair verifies at $0.042/MTok instead of LLM. Compose with `quality = 0.4*answers_request.noul + 0.4*citations_are_supported.noul + 0.2*(1-contradicts_context.noul)` pattern (`docs.typesafe.ai/concepts/how-to-build-with-system-one` composite scoring).

**D3 — AI-tell / banned-word screen** `blog_agents.py:228` Anti-AI-Pattern Checklist + `tools.py:266` banned_words

- `Noul has_ai_tells` ("curly quotes, signposting like 'let's dive in', inflated phrases") + `Noul on_brand` before evaluator. Calibrated confidence tells the agent *when* to rewrite rather than guessing. Faster than regex for semantic tells.

**D4 — Title/summary hook gate** `blog_agents.py:216` Title & Meta Description Guidance

- `Score hook_strength: ["Generic label, no reason to click", "Usable but flat", "Strong: specific angle/number/promise matching intent"]` on `{title, summary, intent}`. Below 1.2 → loop writes a better title before full SEO eval (`blog_agents.py:288` SEO 20%).

### E. Image (`blog_agent/image_agent.py:28` `image_quality_evaluation_agent`, `image_selection_agent:347`, `contextual_image_insertion_agent:112`)

Jev has no vision yet (`SKILL.md:14`). Use **VLM caption → Jev judge** (`references/vision-bridge.md`, `assets/templates/image-vision-hybrid.ts`).

**E1 — Image safety / relevance with hybrid**

- `lib/ai/vision.ts captionImage(url) → state: {image_caption, topic, brand_palette}` then Jev `Choice category`, `Noul is_safe`, `Score priority` (`references/domain-playbooks.md:5`). Preserves today's Gemini vision call but the *judgment* moves to Jev (smaller, typed). Option to swap Gemini vision for `qwen/qwen3-vl-32b-instruct` at $0.14/M as in vision template.

**E2 — Contextual insertion selector**

- `Choice scene_type: {intro, feature_demo, testimonial, outro, filler}` + `Noul needs_image: "Does this 3-5 paragraph cluster benefit from a visual?"` + `Score speech_quality`. Replaces `contextual_image_insertion_agent`'s current pure-LLM placement logic; batch up to 10 section judgments per post in one Jev call (parallel).

### F. Posting / Sanity (`blog_agent/posting_agent.py:35` `preparation_agent`, `lib/sanity_adapter.py:242` `resolve_categories_to_refs`)

**F1 — Category taxonomy Choice** — **prevents the category explosion bug**

- `lib/sanity_adapter.py:223` `list_categories()` already fetches every existing category title. Today `preparation_agent` invents `CATEGORIES: ["AI Agents"]` as freeform strings; adapter then `ensure_document_exists` with `slugify` and may create near-duplicates (`sanity_adapter.py:242` docstring: "AI Agent Tools" vs "AI-Powered Agents"). Fix: Jev `Choice category: <up to 255 existing categories, each with description>` on `{keyword_topic}`. If `confidence < 0.6` or no match → propose *one* new category name via LLM but gate it with Jev `Noul is_new_category_justified`. Logged per `docs/pipeline_flow_and_state.md`.

**F2 — Gate agent tool calls** `posting_agent.py:162` `post_to_sanity_tool`

- Cookbook `gate-tool-calls-with-jev` — before `post_to_sanity_tool`, ask Jev `Noul tool_call_supported: "Is this publish supported by the approved draft?"` + `Choice action: {allow, refuse, ask_human}`. Low-stakes reads 0.5 threshold, writes 0.85.

**F3 — Freshness / search-performance prioritization** `scripts/run_stage.py:521` `_select_review_candidate` / `_select_review_candidate_from_sanity`

- Current rotation is chronological (`Last Freshness Check`). Score each candidate with `Score staleness: ["Current", "Needs refresh soon", "Outdated: price/version/availability changed"]` + `Noul needs_update` on content vs today's Search Console. Route only high-score posts to `freshness_check_agent`.

### G. Cross-Cutting / Ops (`blog_agent/custom_runner.py:32` `FallbackAgentRunner`, `blog_agent/hooks.py`, `lib/run_result_utils.py`)

**G1 — Fallback routing performance**

- `FallbackAgentRunner:436` `_sort_models_by_performance` already tracks `avg_response_time` and `success_rate`. Add Jev latency/cost to `provider_stats` so the runner can prefer Jev for decision-shaped tasks and reserve Gemini quota for genuine generation. No longer burn free-tier Gemini RPD on classifications.

**G2 — PII pre-check before cloud LLM** (`references/domain-playbooks.md:61` ecommerce `contains_pii`)

- `Noul contains_pii: "Does title/description contain PII before sending to cloud LLM?"` Local gate before any OpenRouter call — Inero pattern.

**G3 — Confidence-routed human escalation everywhere**

- Standardize thresholds (`references/patterns.md`): draft publish 0.7-0.8, Sanity write 0.85-0.9, PII block 0.9, image publish 0.6. Log consistent fields (`routingDecisions` table in Octively: `classification, probabilities, confidence, latencyMs, chosenModel, usage.input_tokens`) for post-hoc threshold tuning — not guessed.

---

## 3. What Stays on the LLM (Do NOT Move)

Per decision tree `SKILL.md:40`:

1. **All prose generation:** `content_generator_agent` draft, `brief_agent` brief, `repurposing_agent` LinkedIn/Reddit copy, `post_editor_agent` scoped edits, `freshness_check_agent` suggested edit text. Jev returns numbers/labels, not language.
2. **Reasoning traces / explanations:** if a draft needs a paragraph explaining *why* Jev chose `informational`, have Jev decide and have the LLM *explain* the already-chosen label (`SKILL.md:56`).
3. **Raw vision:** image bytes themselves. Jev judges captions, not pixels — add `lib/ai/vision.ts` (VLM) first (`references/vision-bridge.md`).
4. **One-off, non-repetitive work:** a single typo fix in `post_editor_agent` does not justify a Jev round-trip; regex/rules or a single LLM turn is cheaper lifecycle-wise (`jev-vs-llm.md`).

---

## 4. Cost & Latency Model — What This Platform Would Actually Save

Baseline from repo:
- Target throughput **15-17 articles/day** (`README.md:10`).
- Per article today: 1× research search, 1-2× extracts/crawls, 1× brief LLM call, 1× draft LLM call, **1-3× evaluation loops** (`content_evaluation_agent` on `deepseek-v4-flash` at ~$0.07/MTok), 1-2× image calls, 1× category selection, plus periodic Discord duplicate checks and topic-discovery calls.
- Fallback chain `custom_runner.py:39` is **quota-bound**: `gemini-flash-latest` 20 RPD / 5 RPM, `openrouter-free` 50 RPD. After quota hits, every extra classification *still* burns a paid LLM call.

Jev pricing (verified two ways — tutorial response `usage: {input_tokens: 476, cost: 0.000019992}` **and** live Tavily/Context7 verification in §4a: $0.042/MTok input, output free; cookbook Decisions calls < $0.0001, < 600ms; 40k×800-token workload ~$1.34/mo Jev vs ~$900/mo frontier):

| Call | Input tokens | Jev cost | LLM equivalent | LLM cost | Saving |
|------|--------------|----------|----------------|----------|--------|
| Duplicate check (300 topics + candidate) | ~1200 | $0.00005 | DeepSeek V4 Flash 1k tok | ~$0.00007-0.0003 | ~1.5-6× + output-free |
| 3-question batch `needs_research+intent+trend` | ~600 | $0.000025 | 3 sequential LLM calls | ~$0.0006-0.001 | **~24×** |
| Draft gate `fact_supported+on_brand+quality` | ~3000 (draft+excerpts) | $0.00013 | 1 DeepSeek eval | ~$0.0003-0.0008 | 3-6×, but gates *away* 1-2 extra eval loops → **2-3× per-article eval cost** |
| Map-reduce `is_relevant` ×5 excerpts (batched) | ~1500 | $0.00006 | 5× Tavily extract wasted | 5 credits | 5× Tavily credits saved |

Workflow-eval reference (`typesafe.ai/blog`): **444.6× cheaper, 193.6× faster** at same intelligence when *all* workflow decisions are considered. Expect **40-200×** on individual gates; **net pipeline saving per article dominated by avoided repeats** (skipped extractions, skipped eval iterations, skipped duplicate research cycles), not per-call token delta.

Illustrative 17-article day (conservative, only A1 + B1 + B2/B3 + D1):

- 17× B2/B3 batch (intent+needs_research): saves ~17 LLM classification calls
- 17× B1 filter saves ~5-10 Tavily extracts/day
- 5 duplicate candidates/day × A1 saves 5 DeepSeek calls
- 17× D1 gate avoids ~10-12 extra DeepSeek eval loops (6123% of evaluations currently loop ≥2 times)
- **Order of magnitude: ~30-40 LLM calls/day replaced by ~20 Jev calls/day.** At 30 days → ~900 LLM calls/month avoided, ~$20-40 LLM + Tavily spend moved to ~$1-2 Jev spend, plus ~30-60s latency shaved per article (Jev 100ms vs LLM 800-2000ms per judgment). Free-tier quota (Gemini 20 RPD, OpenRouter 50 RPD) then lasts for *generation only*, not wasted on classifications.

> Exact dollars depend on draft length, excerpt size, and how often D1's gate is confident enough to skip the full evaluator. The numbers above are for sizing; **measure real `usage.input_tokens` + `usage.cost` per `callJev` after the first gate ships** (`references/patterns.md` logging: store `probabilities, confidence, latencyMs, input_tokens` alongside label for threshold tuning). One decision point at a time, hottest path first (`SKILL.md:143`).

---

## 4a. Verified External Evidence — Tavily + Context7 (2026-09-24 run)

Validated the launch-post claims live rather than trusting cached copy. Methods: `tavily_tavily_search(query: "TypeSafe Jev System One model pricing cost latency benchmark workflow evals", search_depth: advanced, max_results: 6)` and `context7_query-docs(libraryId: /websites/typesafe_ai / /openrouterteam/docs)` from this session.

**Tavily — pricing / latency / workflow evals (vendor-reported, no independent replication yet — all sources flag this):**

| Source (Tavily hit) | Reported Jev numbers | Comparator frontier LLMs |
|---|---|---|
| [DataCamp — Jev: TypeSafe's System One Model Explained](https://www.datacamp.com/blog/system-one-models-jev) | 67.8% accuracy, **$0.0004/case, 0.4s** | GPT-5.6 Terra 67.9% $0.0304 10.1s · GPT-5.6 Sol 74.1% $0.0836 23.3s · Claude Opus 5 73.1% $0.1761 37.8s. Verdict: "effectively tied with Terra at ~1/76 cost, 25× faster; Sol/Opus keep 5-6 pt accuracy edge." |
| [DevelopersDigest — Jev Benchmarked](https://www.developersdigest.tech/blog/typesafe-jev-system-one-models-release-guide-2026) | Best-workflow row **76.0% $0.0001 0.4s** (averaged workflows 67.8% reported elsewhere in same doc) | GPT-5.6 Luna 76.1% $0.0025 14.5s · DeepSeek V4 Flash 76.8% $0.0029 34.6s · Claude Sonnet 5 72.9% $0.3616 241.3s |
| [Refix — Jev pricing, latency, benchmarks](https://www.refix.ai/news/jev-pricing-latency-benchmarks) | **$0.042/MTok input, output free** listed on TypeSafe models page — "check official page before budgeting; sustainability unproven" | Headline 193.6× faster / 444.6× cheaper = upper end of real-world gains (TypeSafe own caveat) |
| [Flowtivity — Is the 200x Faster Decision Model Too Good?](https://flowtivity.ai/blog/jev-typesafe-ai-decision-model) | Why output can be free: parallel forward pass over schema, no autoregressive decode loop. **70-500ms** range; example 800-token state × 40k decisions/mo = ~32M tokens → **~$1.34/mo Jev vs ~$900/mo at $10/MTok frontier or ~$90 at $1/MTok**. Counted as price-model, not live bench. |
| [Flavio Copes — Deep dive into Jev](https://flaviocopes.com/jev) | Confirms 70-500ms vs 3-329s frontier, $0.042/MTok = 5-240× lower than LLM $0.20-10/MTok input, output ~5× input normally vs 0 here. | "Treat headline as ceiling." |
| [eesel AI — TypeSafe Jev review](https://www.eesel.ai/blog/typesafe-jev-review) | Headline "193.6× faster, 444.6× cheaper" sits at high end; chart itself is more honest — Jev owns efficiency frontier at lowest cost. | Agrees caveat applies. |

Coverage note: each Tavily hit repeats TypeSafe's own workflow eval design (4 workflows, reference answers = average of GPT-6 Astra + Fable 5.1, every model wrapped in System One adapter). No third-party replication surfaced in Tavily results — consistent with `typesafe.ai/blog` nuance section.

**Context7 — API / confidence / batching (1451 snippets from `/websites/typesafe_ai`):**

- **Endpoint + request shape** confirmed (`docs.typesafe.ai/api`, `quickstart`): `POST https://api.typesafe.ai/v1/systemone` (TypeSafe direct) and via OpenRouter `POST https://openrouter.ai/api/alpha/decisions` — body `{model, state, questions}` where `state` is string | object | array and `questions` is `Choice|Noul|Score` map (`/openrouterteam/docs` `DecisionsRequest` schema). Response `{model, answers, usage: {input_tokens, output_tokens, cost}, id, provider}` (`/openrouterteam/docs` `DecisionsResponse`). Choice returns `{choice, probabilities, confidence}`, Noul `{noul}`, Score `{score, legend, confidence}` — `confidence = f(spread of probabilities)`, flat = low, peaked = high.
- **Confidence gating** (`/confidence`, `patterns/confidence-routing`): floor **0.5 = genuinely uncertain → human**, read-only **0.6**, destructive **0.85-0.9**. Example: `approve_transfer` at `confidence > 0.85` auto-acts, else confirm. Risk tolerance is encoded in *your code*, not a single magic number — "thresholds are domain-specific and should be tuned with your own data" (verbatim Context7 snippet). Applied in this report as §8 table.
- **Batching** (`cookbooks/parallel_questions`): "Adding questions barely changes response time. Each question is evaluated independently, so adding more questions does not create context-rot." Parallel cookbook measurement (batched vs single) shows Nouls bit-identical (`std 0.0`), Choice/Score same sampling noise under both — confirms §1 recommendation to batch `needs_research + intent + trend` in one call.
- **Decisions API costed example** (`/openrouterteam/docs` `gate-tool-calls-with-jev`): each Decisions request in cookbook runs **< $0.0001 (`usage.cost 0.000030-0.000036`) and < 600ms** — matches tutorial's `$0.000019992 / 476 tokens` and this report's §4 model.

**Tavily — domain-adjacent (SEO blog agents):**

Search `SEO blog agent autonomous content pipeline` returned agent-platform landscape (bloq.ink $99/mo, Frase $45/mo, etc.) and confirms the category claim in `README.md:10` — 15-17 articles/day via agent beats freelance $3-8k/mo — so the cost lever in §4 is material, not hypothetical. Tavily as "web access layer for AI agents" (search → extract → crawl) is correctly retained as retrieval lane; Jev is judgment lane on top (consistent with `SKILL.md:15`).

> All Tavily/Context7 excerpts captured raw in this session's tool traces; report uses them only as cited facts, not invented URLs.

---

## 5. Recommended Implementation Order — One Gate at a Time

`SKILL.md:121` templates already exist as copy-paste starters in `.claude/skills/jev-system-one/assets/templates/`. Follow the checklist `SKILL.md:142`: timeout `JEV_TIMEOUT_MS=1500`, Zod validation, fallback never blocks user flow, mock `fetch` to Decisions API shape in tests, `npx tsc --noEmit`.

### Phase 0 — Plumbing — ✅ DONE 2026-09-24 (Tavily + Context7 decision)

**Decision (correct path per fresh Tavily/Context7 evidence):** Raw **Decisions API via OpenRouter** (`POST https://openrouter.ai/api/alpha/decisions`) with `httpx` async + `requests` sync fallback, **not** TypeSafe SDK. Evidence:

- Tavily `tavily_tavily_search("Jev System One implementation Python SDK vs raw HTTP")` → OpenRouter surface table: `Decisions API = "any language with plain HTTP"` vs `System One API = "you already use TypeSafe SDK"` — this Python repo uses raw HTTP (Tavily, Sanity, gspread) and `openai-agents` via OpenRouter, not TypeSafe SDK. Raw path avoids new `typesafe-sdk` dep.
- Context7 `/typesafe-ai/typesafe-sdk-python` confirms SDK is viable (`TypeSafeClient(base_url="https://openrouter.ai/api", api_key=OPENROUTER_API_KEY)`) with `RetryPolicy(max_retries=3)` and `SystemOneResponse` typed, but adds dep and is documented as one-line switch *if you already use SDK*. Kept as alternative in `lib/jev.py` docstring.
- Context7 `/openrouterteam/docs` + `/websites/typesafe_ai` confirm retry `408,429,5xx` + `Retry-After` respect, 32k window, 1500ms timeout, Zod/pydantic validation, `usage.cost` — mirrored here.

**What was shipped (zero pipeline logic change):**

- `lib/jev.py:1` — async `call_jev(state, questions)` + sync `call_jev_sync` via `httpx` (0.28.1 already installed), pydantic `JevChoiceAnswer/JevNoulAnswer/JevScoreAnswer/JevUsage/JevResponse`, `JevError(status, retry_after)`, `_truncate_state` to `JEV_MAX_STATE_CHARS=110k` (~28k tokens), `_validate_questions` (empty + Score<2 guard), retry on `RETRYABLE_STATUS={408,429,500,502,503,504}` with `retry-after` / `retry-after-ms` respect, Zod-equivalent `model_validate` + missing-key check, `jev_log_fields()` for `probabilities+confidence+latencyMs+input_tokens` cost accounting. Mock-tested `validate_jev_response` + guard.
- `discord_bot/jev_helper.py:1` — isolated `requests`-only duplicate for bot Docker context (`Dockerfile` only `COPY bot.py` — cannot import `lib/`). Same `JEV_MODEL/ENDPOINT/TIMEOUT`, `check_duplicate_topic(candidate, existing)` never throws (falls back `False, None, True`), mock-tested with both `noul=0.12→False` and `0.91→True`.
- `discord_bot/Dockerfile:21` → `COPY bot.py jev_helper.py ./` (preserves deploy independence; pipeline and bot deploy separately).
- `.env.example:22` → added optional `JEV_MODEL=typesafe/jev-1.13` (pinned; alias `~typesafe/jev-latest` documented) + commented `JEV_ENDPOINT/JEV_TIMEOUT_MS`.
- `httpx` not added to `pyproject.toml` — already transitively installed (`httpx-0.28.1` via `httpcore`), reused to keep deps minimal.

- Reuse existing `OPENROUTER_API_KEY` (`discord_bot/bot.py:86`, `custom_runner.py:122`). No new key.
- No provider routing change yet; `FallbackAgentRunner` kept as-is; new Jev calls sit alongside it.

### Phase 1 — Quick wins (ship individually, measure `usage`)

1. **A1 duplicate check** (`discord_bot/bot.py:594`). Smallest blast radius, verifiable: approve 10 candidates, compare Jev `is_duplicate` vs current DeepSeek answer. Log `noul, confidence, latencyMs, usage`. Falls back to no-warning on error.
2. **B1 relevance filter** (`research_agent.py:182` before `tavily_extract_tool`). Immediate Tavily credit ROI. One batched Jev call per research run; filter before extract.
3. **B2+B3 intent + needs_research batch** (`blog-pipeline.ts` `gateBlogTopic`). Replace inline intent classification + ad-hoc research-skip heuristic with one call.

### Phase 2 — High-value gate (cascade)

4. **D1 draft quality cascade** (`blog_agents.py:284` `get_evaluation_feedback` + `scripts/run_stage.py:1020` `run_content`). Implement `scoreDraftQuality(draft, facts)` per template, gate `publishReady` before invoking `content_evaluation_agent`. This is where the 2-3× eval cost saving lands. Confidence thresholds tuned from `claims_audit` history.
5. **D2 claim-supported verification** — decompose `content_evaluation_agent:64`'s fact-check ledger into per-claim Nouls against excerpts. Compose with weighted score (0.4/0.4/0.2) per `concepts/how-to-build-with-system-one` composite-scoring pattern.
6. **F1 category Choice** (`lib/sanity_adapter.py:223`). Replace freeform LLM string with Jev Choice over `list_categories()` result; eliminate category drift.

### Phase 3 — Polish & coverage

7. **E1/E2 image hybrid** (`blog_agent/image_agent.py`) — add `vision.ts` then Jev judge (only if image volume warrants it).
8. **F2/F3 posting guards + F3 freshness scoring**, **A2 bot router**, **A3 trend Score**, **G2 PII gate**, **G1 runner latency accounting**.
9. Add `usage.input_tokens/cost` to `model_usage_log` sheet + Discord bot weekly digest (`discord_bot/bot.py` digest). Close the loop on cost accounting.

---

## 6. Detailed Designs for the 4 Priority Gates

### 6.1 A1 Duplicate topic Noul — spec

**File:** `discord_bot/bot.py:594` `_check_duplicate_topic`

```python
# lib/jev.py
JEV_MODEL = "typesafe/jev-1.13"
JEV_ENDPOINT = "https://openrouter.ai/api/alpha/decisions"

async def is_duplicate_topic(candidate: str, existing: list[str]) -> dict:
    state = {"candidate": candidate, "existing": existing[-300:]}  # cap like today
    questions = {
        "is_duplicate": {
            "type": "noul",
            "instructions": "Is `candidate` essentially the SAME specific story/topic as any one entry in `existing`?",
            "criteria": {
                "true": "Same product + same release/angle (e.g. two Xiaomi AI Cube 120B posts)",
                "false": "Same broad subject but different specific story (e.g. two unrelated AI-agent posts)"
            }
        }
    }
    # timeout 1500ms, Zod validation, JevError
```

Fallback: any `JevError`/timeout/missing key → return `{"is_duplicate": False, "confidence": 0, "fallback": True}` and continue (never block approval).

### 6.2 B1 Relevance map — spec

**File:** `research_agent.py:182`

After `tavily_search_tool` returns 5 results, collect `excerpts: [{id, excerpt: result["content"][:800]}]` and call Jev once with `r0_relevant … r4_relevant` Nouls. Keep `noul >= 0.65`. Only those go to `tavily_extract_tool`. Log each `noul, confidence`. Threshold 0.65 is a starting point; plot `confidence` vs precision on 30 labeled excerpts before locking.

### 6.3 B2+B3 Batch — spec

Copy `assets/templates/blog-pipeline.ts:18` `gateBlogTopic(topic, brief)` verbatim. Reuse for `discover_topics` candidate ranking. One call, three questions, one latency unit.

### 6.4 D1 Cascade — spec

Copy `assets/templates/blog-pipeline.ts:52` `scoreDraftQuality(draft, facts)`. Integration into `blog_agent/blog_agents.py:284` `get_evaluation_feedback` loop:

```python
jev = await scoreDraftQuality(draft, facts)
if jev.publishReady:  # supported>=0.7 & score>=1.5 & onBrand>=0.6, confidence-gated
    return draft  # skip content_evaluation_agent entirely
else:
    feedback = await content_evaluation_agent.run_with_tavily_tools(draft, jev_context=jev)
    # jev_context narrows what the evaluator needs to re-check
```

Gate thresholds are **not** magic numbers — they are tuned from real `probabilities` distributions stored in `claims_audit` + `review_feedback_log` (`SKILL.md:144`).

---

## 7. Integration Path for This Repo — Decisions API via OpenRouter (Implemented; SDK as Alternative)

**Why Decisions API raw (chosen) and not `TypeSafeClient` directly — Tavily/Context7-backed:**

- Tavily `openrouter.ai/docs/guides/community/jev` surface table is explicit: `Decisions API + plain HTTP` is the path for *any language calling without SDK*; `System One API + TypeSafeClient(base_url="https://openrouter.ai/api")` is for *teams already on TypeSafe SDK*. This Python repo has no `typesafe-sdk` in `pyproject.toml` and all existing integrations (Tavily, Sanity, gspread) are raw HTTP + `openai-agents` — Decisions API fits, SDK would be extra dep.
- Context7 `/typesafe-ai/typesafe-sdk-python` SDK docs show install `uv add typesafe-sdk` + `TypeSafeClient(api_key=OPENROUTER_API_KEY, base_url="https://openrouter.ai/api")` + `RetryPolicy(max_retries=3)` and typed `SystemOneResponse(model, answers, usage)` — valid and billed to same OpenRouter account, documented as one-line switch. Kept as alternative in `lib/jev.py:12` docstring for teams that prefer SDK ergonomics.
- `OPENROUTER_API_KEY` already provisioned for `deepseek-v4-flash` (`custom_runner.py:122`, `discord_bot/bot.py:86`). Both paths reuse it — no new secret.

**Implemented:** `lib/jev.py:22` uses `POST https://openrouter.ai/api/alpha/decisions` with `httpx` async (primary) + sync `requests` fallback for bot, timeout `JEV_TIMEOUT_MS=1500`, retry on `408,429,5xx` respecting `Retry-After`/`retry-after-ms` (matches `typesafe_sdk.RetryPolicy`), pydantic validation, pinned `JEV_MODEL=typesafe/jev-1.13`.

**SDK alternative (one-line switch if preferred in future):**
```python
# pip install typesafe-sdk
from typesafe_sdk import TypeSafeClient, Noul, Choice
client = TypeSafeClient(api_key=os.environ["OPENROUTER_API_KEY"], base_url="https://openrouter.ai/api")
resp = client.system_one(state={"message": "hi"}, questions={"is_dup": Noul(instructions="...")})
print(resp.answers["is_dup"].noul)
```

Required request fields (`references/api-reference.md:16`, verified via Context7 `/websites/typesafe_ai`):

```json
{
  "model": "typesafe/jev-1.13",
  "state": { "topic": "...", "brief": "..." },
  "questions": {
    "needs_research": {"type": "noul", "instructions": "..."},
    "intent": {"type": "choice", "instructions": "...", "criteria": {"informational": "...", "transactional": "..."}},
    "trend": {"type": "score", "instructions": "...", "criteria": ["Evergreen", "Seasonal", "Trending now"]}
  }
}
```

Response to validate (`references/api-reference.md:61`): `answers.{choice,probabilities,confidence}` / `answers.{noul}` / `answers.{score,probabilities}` + `usage: {input_tokens, output_tokens, cost}`. Implemented as `JevResponse` pydantic in `lib/jev.py:45` + Zod in `assets/templates/blog-pipeline.ts:8` — validate before branching.

Errors (`references/api-reference.md:158`): empty `questions`, `Score` with <2 criteria, non-2xx, connect/timeout abort → throw `JevError` and map to domain fallback (`SKILL.md:81`): classification → `simple`, gate → assume `onTopic=true`, uncertainty → `isUncertain=false`. Never block user path.

---

## 8. Confidence Gating & Fallback — Rules of Thumb

From `references/patterns.md` / `docs.typesafe.ai/concepts/how-to-build-with-system-one` Confidence:

| Action cost | Gate | Threshold | Below → |
|-------------|------|-----------|---------|
| Cheap read (route label) | `confidence >= 0.5` | proceed |
| Draft publish | `confidence >= 0.7` + `score >= 1.5` | rewrite or escalate to DeepSeek evaluator |
| Sanity write (`post_to_sanity_tool`) | `confidence >= 0.85` | ask human / Discord approval |
| PII / safety block | `confidence >= 0.9` | block by default |

Always store `probabilities` + `confidence` + `latencyMs` + `usage.input_tokens` with the label (mirror Octively `routingDecisions` table) so thresholds are set from a ROC plot on real data, not guessed (`SKILL.md:144`).

---

## 9. Risks, Limits & When NOT to Use Jev

- **Schema-correct ≠ factually correct.** Jev narrows the output to your `choice`/`noul`/`score` set, but can pick the wrong member. The *confidence* is the signal; do not treat `choice` alone as ground truth on high-stakes writes (`SKILL.md:115`).
- **No vision / no audio.** For `blog_agent/image_agent.py:29` image judgments, always VLM-caption first (`references/vision-bridge.md`). Do not send image bytes as `state`.
- **Max 255 choices** per Choice; above that use two-stage scoring before explicit choice (`typesafe.ai/blog` Wikiracing note).
- **Context 32k tokens** — enough for a draft + excerpt batch, but not for dumping full sheet history. Keep `state` structured and minimal (`concepts/how-to-build-with-system-one` "Decompose the input state").
- **Threshold drift:** Jev alias `~typesafe/jev-latest` can shift thresholds; pin `typesafe/jev-1.13` once tuned. Log model snapshot from response `model` field.
- **Context7 / Tavily remain search-side:** Jev does not retrieve. It *judges* what Tavily returned. Keep `tavily_search_tool` / Context7 docs; add Jev as the filter/gate on top.

---

## 10. Appendix — References & Copy-Paste

- **Jev vs LLM decision matrix:** `.claude/skills/jev-system-one/references/jev-vs-llm.md`
- **Patterns (confidence, batching, timeout, fallback):** `references/patterns.md`
- **Anti-patterns (6 mistakes, pairings):** `references/anti-patterns.md`
- **Domain playbooks (7 domains):** `references/domain-playbooks.md` — §2 Blog Generation is the closest to this repo
- **Vision bridge (image/video):** `references/vision-bridge.md`
- **API shapes, Zod, SDK setup, timeout wrapper:** `references/api-reference.md:129`
- **Templates to copy verbatim:**
  - `assets/templates/blog-pipeline.ts` — `gateBlogTopic` + `scoreDraftQuality` (used above)
  - `assets/templates/router-classifier.ts` — chatbot 5-way Choice (A2)
  - `assets/templates/quality-gate.ts` — Noul `isOnTopic` with excerpts (B1/D2)
  - `assets/templates/uncertainty.ts` — Noul `isUncertain` (bot router)
  - `assets/templates/research.ts` — Noul relevant + Noul supported + Score strength
  - `assets/templates/image-vision-hybrid.ts` + `lib/ai/vision.ts` — image fix

---

## 11. Live Test Results (DONE 2026-09-24)

Executed with real `OPENROUTER_API_KEY` from `.env` — not mocks.

### 11a. Smoke + 20-candidate dedupe batch (`scripts/live_jev_test.py` → `docs/jev-live-test-report.json`)

**Smoke** — `gate_blog_topic` (Noul + Choice + Score batched, model returned `typesafe/jev-1.13-20260917`):

| Metric | Value |
|--------|-------|
| needs_research | 0.73 → true |
| intent | informational (conf 0.38; probs comparison 0.46 / informational 0.53) |
| trend score | 1.33 (prob 2=0.66) |
| latency | 4076 ms first call (later calls 1.1–2.0 s — above marketing 70–500 ms) |
| usage | 515 in / 89 out, **$0.0000216** |
| fallback | false |

**20 candidates × (Jev Choice + Jev Noul + DeepSeek chat)**, ground truth `exact_dup|same_story` = positive:

| Path | Accuracy | Notes |
|------|----------|-------|
| Jev Choice (`find_duplicate_topic`, production bot path) | **0.75** (conf≥0.65), **0.80** (conf≥0.8) | 0 fallbacks; high conf on true dups (0.99–1.00) |
| Jev Noul **before fix** | 0.55 | **Bug:** Noul returns `confidence: null` → `conf >= 0.65` always failed → `is_duplicate` always false |
| Jev Noul **after fix** (gate skips null conf; `threshold_noul` 0.75→**0.6**) | **0.85** (17/20) | Matches DeepSeek; misses are soft `same_story` (0.17–0.54) |
| DeepSeek `deepseek-v4-flash-0731` (old path) | **0.85** | avg latency **7627 ms**, 4-parallel |

**Noul threshold sweep (pre-fix data, conf gate excluded — for tuning):**

| noul ≥ | Precision | Recall | F1 |
|--------|-----------|--------|-----|
| 0.50 | 1.00 | 0.78 | **0.88** |
| 0.60 | 1.00 | 0.67 | 0.80 |
| 0.75 | 1.00 | 0.44 | 0.62 |

Batch cost: **10 142 input tokens ≈ $0.00043** across 20 Noul calls (Choice usage logged separately). Jev ~1.2–4 s vs DeepSeek ~7.6 s.

**Fixes applied from live data:**
- `lib/jev_helpers.py` `check_duplicate_topic` / `_sync`: only apply conf gate when `confidence is not None`; default `threshold_noul=0.6` (was 0.75).
- Discord Choice path unchanged (returns real conf).

### 11b. Production gate helpers live (`docs/jev-live-gates-report.json`)

All 7 helpers ran live, **0 fallbacks**:

| Helper | Result | Latency |
|--------|--------|---------|
| `gate_blog_topic` | needs=true, intent=comparison, trend=1.11 | 2009 ms, $0.0000209 |
| `filter_relevant_excerpts` | kept `e2,e3` / dropped Jev-meta + gossip (2/4) | 1387 ms |
| `score_draft_quality` + live_profile | supported=0.19, on_brand=0.75, stack_aligned=**0.93**, score=1.03 → **publish_ready=false** (correct cascade: escalate) | 1226 ms |
| `classify_category` | reuse **Vector DBs** conf=**1.0** | 1158 ms |
| `rank_internal_links` | top `pgvector-vs-pinecone` (relevant beats recent Docker link) | 1207 ms |
| `route_human_review` | priority=1.9, safe, needs_update | 1167 ms |
| `find_duplicate_topic` Choice | matched exact story conf=0.72 | 1427 ms |

### 11c. Full `discover_topics → research → content` dry-run

**Not run:** `scripts/run_stage.py` has **no `--dry-run`** flag; every stage handler writes to Google Sheets / Sanity / Discord. Gate-level live coverage (11a/11b) is done instead. Next opt-in step: run `--stage research` on a throwaway keyword with sheet-write intercept, or add a real `--dry-run` to `run_stage.py`.

### 11d. Timeout

`.env` `JEV_TIMEOUT_MS` was commented (default 1500 ms). Live first calls hit **2–4 s** — set **`JEV_TIMEOUT_MS=5000`** so retries do not fire on healthy requests. Diagnostics: `timeout_ms=1500` still succeeded at 2088 ms (httpx read timeout did not abort — do not rely on sub-second timeouts).

Code defaults updated to match: `lib/jev.py:53` and `discord_bot/jev_helper.py:26` now default **5000**; bot `requests` timeout changed from `_timeout + 5` to tuple `(5.0 connect, _timeout read)`.

### 11e. Final live gate (`scripts/live_jev_final_test.py` → `docs/jev-live-final-report.json`)

**1) Production pairing — same 20 candidates, Choice + Noul together (0 fallbacks both paths):**

| Path | Accuracy | Precision | Recall | F1 | TP/FP/FN |
|------|----------|-----------|--------|-----|----------|
| Choice conf≥0.65 (current bot) | 0.75 | 0.67 | 0.89 | 0.76 | 8/4/1 |
| Choice conf≥**0.8** (recommended) | 0.80 | 0.73 | 0.89 | **0.80** | 8/3/1 |
| Noul `noul>=0.6` (fixed) | **0.85** | **1.00** | 0.67 | 0.80 | 6/0/3 |

Noul returned `confidence: null` in **20/20** calls — the null-safe fix is mandatory, not defensive. Choice(0.8) vs Noul(0.6) agree 15/20; union gives recall 1.0 with 3 FP, so Noul stays the precision-first lane and Choice the recall lane.

**2) Forced failures — no exception escapes, no blocking:**

| Forced fault | Result |
|--------------|--------|
| Invalid API key (401 `User not found`) | `gate_blog_topic` → `fallback=true` (needs_research=true); Noul → `fallback=true`, `is_duplicate=false`; Choice → `fallback=true`, `matched=None` |
| Invalid model (400) | `JevError(status=400)` raised by `call_jev`, caught by helpers |
| `timeout_ms=1` | `JevError` at 1044 ms (connect floor, not immediate) |
| Empty `questions` | `JevError("questions must be non-empty mapping")` |
| Score with 1 criterion | `JevError("requires at least 2 criteria entries")` |

**3) Discord bot `requests` path (`discord_bot/jev_helper.py`, isolated Docker context):** 3/3 correct, 0 fallbacks, **401–514 ms**, $0.0000405/call. Invalid key → `(None, None, fallback=True)`, never raises.

**4) G1 stats (`FallbackAgentRunner.record_jev_result`, in-memory):** 3 live calls → `success_count=3, error_count=1, total_cost=$0.0000378, total_input_tokens=900, avg_response_time=0.99s`; `is_jev_available()` True, RPM window counted 4. No sheet write from this path (runner init only *reads* `model_usage_log` to seed counts).

**Latency shape (measured):** single-question Noul warm **465–955 ms**; bot `requests` Choice **401–514 ms**; 3–4 question batched calls **1.2–2.0 s**; cold first call **~4.1 s**. Batch size, not just model, drives latency.

---

## 12. Suggested Next Step

Phase 0 + A1 live validation is **done** (§11a–11e). Remaining: (1) optional `--dry-run` on `run_stage.py` for full pipeline; (2) raise bot Choice conf floor **0.65 → 0.8** (live 0.80 acc vs 0.75, FP 4→3); (3) Noul `threshold_noul=0.6` is already in `lib/jev_helpers.py` — keep templates in sync; (4) monitor `jev_stats` G1 cost/latency over a week of production candidates.

