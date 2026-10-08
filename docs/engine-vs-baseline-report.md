# Engine vs. Baseline — ContentFTE new output vs. old ContentSpark output

Generated: 2026-10-08 16:03 · baseline = last 25 published posts from the Google Sheet · new = 3 article(s) from the ContentFTE engine · judge = Gemini (identical rubric, temp 0)

## Verdict

**Weighted overall: old 70.0 / 100 vs new 74.6 / 100 → NEW wins by 4.6**

| Dimension | Weight | Old (baseline) | New (engine) | Delta | Winner |
|---|---:|---:|---:|---:|---|
| facts | 30% | 79.2 | 66.7 | -12.5 | old |
| style | 20% | 55.2 | 66.7 | +11.5 | new |
| seo | 20% | 77.6 | 80.0 | +2.4 | new |
| tone | 10% | 67.2 | 93.3 | +26.1 | new |
| structure | 10% | 64.8 | 86.0 | +21.2 | new |
| images | 5% | 60.8 | 100.0 | +39.2 | new |
| length | 5% | 68.8 | 46.7 | -22.1 | old |

## Objective metrics (averages)

| Metric | Old avg | New avg | Better |
|---|---:|---:|---|
| words | 910.8 | 522 | old |
| h2 | 5.9 | 6 | new |
| faq_count | 6.0 | 5.3 | old |
| ext_links | 3.7 | 2.3 | old |
| int_links | 0 | 0 | tie |
| images | 4.5 | 2 | old |
| image_alt_pct | 60 | 100 | new |
| ai_hits_per_1k | 0.6 | 2.0 | old |
| passive_per_100 | 1.5 | 3.0 | old |
| flesch | 31.7 | 27.1 | old |
| fkgl | 13.0 | 14.6 | old |
| intro_words | 32.0 | 51 | old |
| para_avg_words | 43.5 | 51.3 | old |
| meta_chars | 146.6 | 145.7 | tie |
| title_chars | 58.3 | 41.7 | tie |
| seo_score | 77.6 | 80 | new |
| structure_score | 64.8 | 86 | new |

## Ops: local time & tokens per post

| New article | Words | Gen attempts | Gen wall (s) | Image (s) | Total (s) | In tokens | Out tokens | Total tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Anthropic Haiku 5.5 vs DeepSeek V4.1 Flash: Which Should Y | 484 | 2 | 42.6 | 46.0 | 91.1 | 12893 | 1042 | 13935 |
| When to Choose Astro Over React or Next.js | 687 | 1 | 9.6 | 60.5 | 72.8 | 12879 | 1626 | 14505 |
| Better Auth vs. Auth.js: Why Developers Are Migrating Thei | 453 | 1 | 8.4 | 54.0 | 64.2 | 12883 | 1060 | 13943 |
| **avg / total** | | | **20.2** | **53.5** | **76.0** | | | **42383** |

Old baseline (from `model_usage_log` / `image_logs`, bucketed by `Created At` windows):

- LLM time per post (sum of call latencies): **avg 2042.7s**, median 1526.0s, range 623.2–5664.4s
- LLM calls per post: **avg 24.9** (bucketed rows incl. retries/errors)
- Tokens: **not logged** — the old pipeline's `model_usage_log` has no token columns (latency only)

Notes:

- New *gen wall* = measured wall clock around `generate_content` (driver t0); *Total* = submit→publish/refresh wall clock from `phaseD_results.json`.
- New token usage = sum over the final generation attempt's model responses (`article.meta.generation.usage`); retries of a failed attempt are not merged into that number.
- The engine's `cost_ledger` currently persists $0.00 totals (cost wiring gap, tracked in TASKS) — tokens above come from the Agents SDK response usage, not the ledger.
- Old-side LLM time is a latency-sum approximation: rows are bucketed into Created-At windows, so tool/network gaps between calls are excluded and idle time between posts can be misattributed.
- Image staging: run 1 produced all 6 AI images but the driver dropped them on a local-path bug; run 2 hit Cloudflare's daily neuron quota. The run-1 files were re-attached via `scripts/recover_compare_images.py` (clustered by mtime, VLM-ranked winners), so the posts carry AI-generated featured + inpost images.
- Old-side per-post image time is not attributed: `image_logs` subjects are topic fragments, not article titles, so they cannot be mapped to baseline posts.

## Judge scores (1–5, harsh rubric)

| Dimension | Old avg | New avg |
|---|---:|---:|
| facts | 3.96 | 3.33 |
| tone | 3.36 | 4.67 |
| style | 2.76 | 3.33 |

## Published-page checks (supplementary, not weighted)

| Article | URL status | Title len | Meta desc | JSON-LD types | OG | H1s |
|---|---|---:|---|---|---|---:|
| old | iable-ai-agents-in-production-without-state-loss | 77 | yes (165) | BlogPosting, BreadcrumbList, FAQPage, WebPage | y | 1 |
| old | uild-autonomous-ai-employees-in-python-using-mcp | 66 | yes (151) | BlogPosting, BreadcrumbList, FAQPage, WebPage | y | 1 |
| old | cal-autonomous-ai-employees-using-mcp-and-python | 77 | yes (158) | BlogPosting, BreadcrumbList, FAQPage, WebPage | y | 1 |
| old | aomi-ai-cube-run-120b-local-llms-on-your-desktop | 68 | yes (139) | BlogPosting, BreadcrumbList, FAQPage, WebPage | y | 1 |
| old | log/best-ai-automation-development-firms-in-2026 | 101 | yes (152) | BlogPosting, BreadcrumbList, FAQPage, WebPage | y | 1 |
| old | log/deepseek-v4-1-flash-architecture-and-pricing | 61 | yes (143) | BlogPosting, BreadcrumbList, FAQPage, WebPage | y | 1 |
| old | evelo-vs-independent-devs-which-hiring-path-wins | 76 | yes (148) | BlogPosting, BreadcrumbList, FAQPage, WebPage | y | 1 |
| old | 00ms-structured-decisions-for-browser-automation | 82 | yes (142) | BlogPosting, BreadcrumbList, FAQPage, WebPage | y | 1 |
| old | nt-the-4-phase-workflow-that-stops-ai-code-drift | 36 | yes (43) | - | y | 1 |
| old | i-agent-overengineering-and-use-simple-workflows | 71 | yes (150) | BlogPosting, BreadcrumbList, FAQPage, WebPage | y | 1 |
| old | em-one-model-cut-ai-classifier-latency-and-costs | 74 | yes (160) | BlogPosting, BreadcrumbList, FAQPage, WebPage | y | 1 |
| old | ering-simple-workflows-vs-30-agent-architectures | 86 | yes (160) | BlogPosting, BreadcrumbList, FAQPage, WebPage | y | 1 |
| old | text-memory-systems-for-multi-agent-ai-workflows | 103 | yes (129) | BlogPosting, BreadcrumbList, FAQPage, WebPage | y | 1 |
| old | i-automation-project-without-framework-paralysis | 36 | yes (43) | - | y | 1 |
| old | penclaw-debate-is-changing-ai-agent-architecture | 86 | yes (153) | BlogPosting, BreadcrumbList, FAQPage, WebPage | y | 1 |
| new | local/better-auth-vs-auth-js-for-next-js-in-2025 | 42 | yes (144) | Article, BreadcrumbList, FAQPage, WebPage | y | 1 |
| new | .local/when-to-choose-astro-over-react-or-nextjs | 41 | yes (139) | Article, BreadcrumbList, FAQPage, WebPage | y | 1 |
| new | local/anthropic-haiku-5-5-vs-deepseek-v4-1-flash | 42 | yes (154) | Article, BreadcrumbList, FAQPage, WebPage | y | 1 |

## New engine articles (detail)

### Better Auth vs Auth.js for Next.js in 2025

- id 4 · status `published` · cost $0.0000 · engine scores `{"overall": 95.0}`
- words 444 · H2 6 · FAQ 5 · links ext/int 2/0 · images 2 (100% alt)
- readability Flesch 23.1 / grade 15.1 · AI-isms/1k 2.25 · passive/100 4.55
- seo 80 · structure 86 · length score 40 · judge f/t/s 5/5/4
- judge issues — facts: None; accurately reflects both libraries' features, architecture, and ecosystem state. · tone: None; direct, technical, objective expert-to-peer tone with zero hype or fluff. · style: Slightly formulaic heading structure (all question-based), but prose is concise and clean.
- url: http://speedline.local/better-auth-vs-auth-js-for-next-js-in-2025

### When to Choose Astro Over React or Nextjs

- id 3 · status `published` · cost $0.0000 · engine scores `{"overall": 95.0}`
- words 647 · H2 6 · FAQ 6 · links ext/int 3/0 · images 2 (100% alt)
- readability Flesch 40.9 / grade 12.6 · AI-isms/1k 1.55 · passive/100 0.0
- seo 80 · structure 86 · length score 60 · judge f/t/s 4/5/4
- judge issues — facts: Diff artifact syntax error (`==map==`) inside the Astro code snippet. · tone: None. · style: Slightly formulaic structure and mild cliché ('best of both worlds').
- url: http://speedline.local/when-to-choose-astro-over-react-or-nextjs

### Anthropic Haiku 5.5 vs Deepseek V4.1 Flash

- id 2 · status `published` · cost $0.0000 · engine scores `{"overall": 92.0}`
- words 475 · H2 6 · FAQ 5 · links ext/int 2/0 · images 2 (100% alt)
- readability Flesch 17.2 / grade 16.0 · AI-isms/1k 2.11 · passive/100 4.35
- seo 80 · structure 86 · length score 40 · judge f/t/s 1/4/2
- judge issues — facts: Fabricated model names (Haiku 5.5 and DeepSeek V4.1 Flash do not exist) and total lack of specific, verifiable pricing or benchmark data. · tone: Professional and objective voice, but speaks in abstract generalizations. · style: Formulaic AI heading structures, repetitive generic phrasing, and zero concrete code or benchmark examples.
- url: http://speedline.local/anthropic-haiku-5-5-vs-deepseek-v4-1-flash

## Old baseline articles (appendix)

| # | Title | Words | H2 | FAQ | Links ext | Images | SEO | Struct | Flesch | AI/1k | Judge f/t/s |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | Building Reliable AI Agents in Production Without State Lo | 1977 | 6 | 5 | 5 | 8 | 80 | 57 | 47.3 | 0.0 | 5/4/4 |
| 2 | Build Autonomous AI Employees in Python Using MCP | 412 | 5 | 6 | 3 | 8 | 80 | 57 | 30.2 | 0.0 | 4/3/3 |
| 3 | Build Practical Autonomous AI Employees Using MCP and Pyth | 692 | 6 | 6 | 0 | 8 | 70 | 71 | 42.5 | 1.45 | 4/3/2 |
| 4 | Xiaomi AI Cube: Run 120B Local LLMs on Your Desktop | 799 | 5 | 6 | 7 | 9 | 80 | 57 | 29.3 | 1.25 | 2/3/2 |
| 5 | Best AI Automation Development Firms in 2026 | 614 | 6 | 6 | 6 | 9 | 80 | 57 | 16.2 | 3.26 | 3/3/3 |
| 6 | Top AI Automation Development Firms in 2026: Compare 9 Bui | 789 | 7 | 6 | 2 | 0 | 80 | 71 | 45.2 | 0.0 | 2/2/2 |
| 7 | DeepSeek V4.1 Flash Architecture And Pricing | 670 | 5 | 6 | 5 | 9 | 80 | 57 | 26.4 | 1.49 | 1/2/1 |
| 8 | 5 Custom AI Agent Automations That Run Your Business 24/7 | 922 | 5 | 6 | 5 | 0 | 80 | 71 | 26.9 | 0.0 | 3/3/2 |
| 9 | 5 Toptal Alternatives That Match You in 24 Hours | 805 | 5 | 6 | 3 | 0 | 70 | 57 | 27.8 | 1.24 | 3/3/2 |
| 10 | Gun.io vs Revelo vs Independent Devs Which Hiring Path Win | 1578 | 7 | 6 | 6 | 9 | 80 | 71 | 30.4 | 0.0 | 4/3/3 |
| 11 | What Is a Digital FTE? How Local AI Employees Run Your Bus | 731 | 6 | 6 | 0 | 0 | 70 | 71 | 27.6 | 1.37 | 5/4/3 |
| 12 | OpenAI Agents SDK vs Claude Code: Which Framework Fits You | 677 | 6 | 6 | 5 | 0 | 70 | 71 | 34.9 | 0.0 | 5/3/2 |
| 13 | Jev System One: 100ms Structured Decisions for Browser Aut | 615 | 5 | 6 | 5 | 8 | 80 | 57 | 23.3 | 1.63 | 5/4/4 |
| 14 | How I Built an AI Chatbot SaaS with Next.js and RAG | 752 | 6 | 6 | 4 | 0 | 80 | 71 | 34.4 | 0.0 | 3/3/2 |
| 15 | Next.js 15 Sanity CMS Setup Guide With GROQ & Vercel | 787 | 6 | 6 | 2 | 0 | 80 | 71 | 26.3 | 0.0 | 4/3/2 |
| 16 | Spec-Driven Development: The 4-Phase Workflow That Stops A | 729 | 5 | 6 | 2 | 3 | 80 | 71 | 17.2 | 0.0 | 3/4/3 |
| 17 | AI Workflow Automation for Small Businesses: The 4-Step Im | 779 | 6 | 6 | 5 | 0 | 70 | 57 | 49.1 | 0.0 | 5/3/3 |
| 18 | Spec-Driven Development for Clean Next.js SaaS Apps | 1563 | 11 | 6 | 4 | 0 | 80 | 57 | 35.9 | 0.0 | 5/5/4 |
| 19 | Stop AI Agent Overengineering and Use Simple Workflows | 922 | 6 | 6 | 3 | 8 | 80 | 71 | 31.9 | 0.0 | 4/3/3 |
| 20 | Jev System One Model: Cut AI Classifier Latency and Costs | 772 | 5 | 7 | 3 | 8 | 70 | 71 | 21.2 | 1.3 | 5/4/3 |
| 21 | AI Agent Over-Engineering: Simple Workflows vs 30-Agent Ar | 808 | 6 | 6 | 3 | 8 | 80 | 71 | 33.8 | 0.0 | 5/4/3 |
| 22 | Context Memory Systems for Multi Agent AI Workflows | 1768 | 6 | 6 | 4 | 7 | 80 | 57 | 20.8 | 0.0 | 5/4/4 |
| 23 | Pick Your First AI Automation Project Without Framework Pa | 944 | 6 | 6 | 4 | 3 | 80 | 57 | 53.2 | 0.0 | 4/3/2 |
| 24 | Why Framework Choice Doesn't Matter in AI Agent Developmen | 925 | 5 | 6 | 3 | 0 | 80 | 71 | 27.4 | 0.0 | 5/4/4 |
| 25 | MCP vs CLI: Why the OpenClaw Debate Is Changing AI Agent A | 741 | 6 | 5 | 3 | 8 | 80 | 71 | 34.2 | 1.35 | 5/4/3 |

## Methodology & limitations

- Baseline = `ContentSpark/generated_posts` rows with `Published=Yes` (last 25 by `Created At`); body = the markdown the old agent produced.
- New = last 3 published/approved articles from the engine (`/sdk/v1` delivery payload).
- Objective metrics computed with the identical parser for both sides (word/heading/link/image counts, Flesch/FKGL, AI-cliché & passive counters, SEO/structure checklists).
- Facts/tone/style = one Gemini judge call per article, same rubric, temperature 0. Facts judged **without live web search** — plausibility/consistency only; the engine's own Tavily fact-check gate runs separately on new articles.
- Judge knowledge cutoff: very recent model releases postdate the judge — it scored the new Haiku-5.5 article f=1 ("models do not exist") and the old DeepSeek-V4.1-Flash article f=1 the same way, so the artifact hits **both** sides but adds noise to the facts dimension.
- Old image provenance = sheet `Image Source` (stock); alt-% from markdown `![](url)` alt text. Published-page checks are supplementary (network-dependent) and not weighted.
- Weights: {"facts": 30, "style": 20, "seo": 20, "tone": 10, "structure": 10, "images": 5, "length": 5}. Judge model(s): gemini-3.5-flash, gemini-3.6-flash, gemini-flash-latest, gemini-3.5-flash-lite.