---
name: seo-pack
description: SEO/AEO/GEO tactic library for content agents — keyword strategy, brief research, on-page, citability, authority, refresh, agent-readiness, eval gates, brand voice, local, coverage multiplication, gray-policy, technical foundations.
---

# SEO Skill Pack

Tactics library for ContentFTE's brief, draft, and eval agents — and for any human or Claude Code user writing or auditing SEO content. The tricks live here so they don't have to be hardcoded into prompts.

## When to use what

| Reference | Use when… |
|---|---|
| `references/keyword-strategy.md` | Picking keywords, brief outlines, planning clusters/programmatic pages, avoiding cannibalization |
| `references/brief-research.md` | Building a brief: gathering real questions, SERP gaps, discourse, fan-out queries |
| `references/onpage-aeo.md` | Drafting or reviewing an article's on-page structure (titles, TL;DR, H2s, FAQs) |
| `references/geo-citability.md` | Optimizing for AI Overviews / ChatGPT / Perplexity citations |
| `references/authority-internal.md` | Internal linking, topical authority planning, backlink strategy |
| `references/refresh-decay.md` | Refreshing old content, detecting traffic decay |
| `references/agent-readiness.md` | Making a site/page consumable by crawlers, LLMs, and agents |
| `references/eval-gates.md` | Evaluating a draft — scores, gates, fact-check ordering |
| `references/brand-voice.md` | Defining or applying a brand's voice |
| `references/local-seo.md` | Local business sites (GBP, reviews, entity consistency) |
| `references/coverage-multiplication.md` | Turning one keyword into a page + video + social bundle |
| `references/gray-policy.md` | Before using any tactic that smells gray-hat — read first |
| `references/technical-foundations.md` | Site audits, pre-content health checks, publishing mechanics |

## Sources

Distilled from two practitioner systems — **Edward Sturm** (@buildinpublic,
edwardsturm.com/articles) and **Daniel Agrici** (@AgriciDaniel; `claude-seo`
18.2k★ / `claude-blog` 2.3k★, MIT) — plus general SEO practice where background
knowledge was assumed (technical foundations, on-page basics). Human-readable
master with per-tactic wiring tables and source dates:
`docs/Content FTE Research/ContentFTE-Tactics-Playbook.md`.

## Merge notes
This pack is the source of truth for the ContentFTE brief / draft / eval
agents, which cite it by path (`skills/seo-pack/SKILL.md`). Concrete builders
live in `lib/tactics.py` (`build_paa_page_spec`, `build_comparison_page_spec`,
`plan_cluster`) and are exposed to the Brief Agent via `tools/tactics_tool.py`.

## Maintenance

Recheck both creators' material **monthly**. Append new tactics with source + date. **Never silently remove a tactic** — mark it superseded and explain why.
