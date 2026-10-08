"""§5.16 brief intent templates — deterministic structure per search intent.

Pure (no LLM): the Brief Agent receives its keyword's intent and MUST follow
the matching template so two briefs for similar keywords with different
intents (informational vs transactional) come out structurally distinct.
Templates cover the spec's brief checklist: angle, outline, SERP-gap
expectation, entities, sources, Brand-DNA injection (system-prompt level,
per §5.1), CTA posture — plus a per-intent word floor/target (pack
onpage-aeo "length matches intent": compact buyer-intent pages are
400-500 words and must NOT be rejected by a flagship-post word gate).
"""
from __future__ import annotations

import os

TEMPLATES: dict[str, dict] = {
    "informational": {
        "name": "Informational explainer",
        "goal": "Answer the query completely and earn passage citations / AI Overview inclusion.",
        "angle": "Teach-first: direct answer up top, depth below, zero selling.",
        "word_floor": 900,
        "word_target": "1500-2500",
        "required_sections": [
            "TL;DR (40-60 words) giving the direct answer before any background",
            "4-6 H2s phrased as the sub-questions searchers actually ask (question form where natural)",
            "Body sections that resolve each sub-question in 80-150 words with a concrete example",
            "FAQ block: 5-7 People-Also-Ask questions, answers under 50 words",
            "Sources box (title + publisher + link)",
            "Entities block: 5-8 entities to name naturally (people, brands, standards, places)",
        ],
        "h2_pattern": "What / Why / How / When / Can — plain language, no colons, no clickbait",
        "cta_posture": "Soft: one contextual next step related to the topic; no hard sell",
        "serp_gap_rule": "List exactly 3 subtopics the top-10 results cover that the brief does not yet.",
    },
    "commercial": {
        "name": "Commercial investigation / comparison",
        "goal": "Help the reader choose — surface trade-offs, criteria, and who each option suits.",
        "angle": "Fair evaluation: criteria table first, recommendation grounded in stated use-cases.",
        "word_floor": 900,
        "word_target": "1500-2500",
        "required_sections": [
            "TL;DR (40-60 words) naming the best fit per reader type",
            "Selection criteria H2 (what actually matters, 4-6 criteria)",
            "Option-by-option H2s (each option: strengths, weaknesses, best-for)",
            "Head-to-head comparison table (Markdown) on the key criteria",
            "FAQ block: 5-7 purchase-stage questions, answers under 50 words",
            "Sources box (title + publisher + link)",
            "Entities block: 5-8 entities (products, vendors, standards)",
        ],
        "h2_pattern": "Criteria and comparisons — 'X vs Y', 'Best X for Y', no colons",
        "cta_posture": "One clear next step (try/demo/compare); disclose affiliations",
        "serp_gap_rule": "List exactly 3 comparison angles or options the top-10 results cover that the brief does not.",
    },
    "transactional": {
        "name": "Transactional / action page",
        "goal": "Remove friction for a ready-to-act reader; answer objections before the click.",
        "angle": "Action-first: what it is, what it costs, how to start, what could go wrong.",
        # Compact Keyword landing page (spec §5.10-5, pack keyword-strategy
        # §1 / onpage-aeo "buyer-intent short 400-500") — deliberately below
        # the flagship floor so a compact page passes the quality gate.
        "word_floor": 400,
        "word_target": "400-700",
        "required_sections": [
            "TL;DR (40-60 words): what the reader gets and the first step",
            "How it works H2 (3-5 numbered steps)",
            "Pricing / effort H2 (ranges or 'from' framing; no invented numbers)",
            "Objection-handling H2 (top 3 doubts answered plainly)",
            "FAQ block: 5-7 last-mile questions, answers under 50 words",
            "Sources box (title + publisher + link)",
            "Entities block: 5-8 entities (brands, payment/tech names, locations)",
        ],
        "h2_pattern": "Verbs and outcomes — 'Get started', 'What it costs', no colons",
        "cta_posture": "One primary CTA repeated at most twice; never two competing CTAs",
        "serp_gap_rule": "List exactly 3 reassurance/detail elements the top-10 results include that the brief does not.",
    },
    "local": {
        "name": "Local service / 'near me'",
        "goal": "Match local intent: place, service area, trust signals, NAP-consistent entities.",
        "angle": "Local relevance first — neighborhood/landmark mentions, service radius, reviews.",
        "word_floor": 700,
        "word_target": "900-1500",
        "required_sections": [
            "TL;DR (40-60 words) with the city/area named explicitly",
            "Service H2s scoped to the locality (what + where)",
            "Trust H2: credentials, response time, guarantee (facts only, sourced)",
            "Coverage/areas H2 (neighborhoods or radius)",
            "FAQ block: 5-7 local questions (parking, hours, areas served), answers under 50 words",
            "Sources box (title + publisher + link)",
            "Entities block: city, neighborhoods, landmarks, accreditations",
        ],
        "h2_pattern": "Place + service phrasing, plain language, no colons",
        "cta_posture": "One location-anchored CTA (call / book / get a quote)",
        "serp_gap_rule": "List exactly 3 local details the top-10 results cover that the brief does not.",
    },
    "navigational": {
        "name": "Navigational / brand-adjacent",
        "goal": "Confirm the reader is in the right place fast; disambiguate brand vs category.",
        "angle": "Precision: state what this is, who it's for, point to the canonical action.",
        "word_floor": 500,
        "word_target": "600-900",
        "required_sections": [
            "TL;DR (40-60 words) confirming what the reader was looking for",
            "What it is H2 (definition + differentiator from near-name alternatives)",
            "Who it's for H2 (fit and non-fit)",
            "Primary action H2 (the canonical next step)",
            "FAQ block: 5-7 disambiguation questions, answers under 50 words",
            "Sources box (title + publisher + link)",
            "Entities block: brand, product, parent company, standards",
        ],
        "h2_pattern": "Direct labels — 'What is X', 'Who is X for', no colons",
        "cta_posture": "Single canonical action; no upsell",
        "serp_gap_rule": "List exactly 3 clarifying subtopics the top-10 results cover that the brief does not.",
    },
    "announcement": {
        "name": "Win / milestone announcement",
        "goal": "Announce a verifiable win (award, milestone, funding, launch) — factual, dated, sourced.",
        "angle": "Newsroom-truthful: what happened, the numbers, why it matters to the reader — zero hype adjectives.",
        "word_floor": 600,
        "word_target": "700-1200",
        "required_sections": [
            "TL;DR (40-60 words): the announcement in one sentence with the date/number",
            "What happened H2 (the facts first: who, what, when, the metric)",
            "Why it matters H2 (impact on readers/customers — not on the company's ego)",
            "Proof / context H2 (sourced numbers, third-party validation; mark anything unverified as [VERIFY])",
            "What's next H2 (timeline or next milestone, only if public)",
            "FAQ block: 4-6 questions journalists/readers would ask, answers under 50 words",
            "Sources box (title + publisher + link)",
        ],
        "h2_pattern": "Plain newsroom labels — 'What happened', 'Why it matters', no colons",
        "cta_posture": "One soft next step (read the announcement / contact); no hard sell",
        "serp_gap_rule": "List exactly 3 context angles the top-10 coverage gives that this brief does not.",
    },
    "press-release": {
        "name": "Press release",
        "goal": "A pickup-ready release: inverted pyramid, attributed quotes, boilerplate — facts only.",
        "angle": "AP-style: dateline lede with the 5Ws in the first sentence, quotes clearly attributed.",
        "word_floor": 400,
        "word_target": "400-700",
        "required_sections": [
            "Headline + subhead (active verb, no hype superlatives)",
            "Dateline lede: CITY, Date — one sentence with who/what/when/where/why",
            "Body: 2-3 inverted-pyramid paragraphs (newest/most newsworthy first)",
            "Quote block: 1-2 attributed quotes — use [SPOKESPERSON NAME, TITLE] placeholders; NEVER invent a quote from a real person",
            "Facts & figures section (sourced; numbers link to their source)",
            "Boilerplate 'About X' paragraph + media contact line (placeholder if unknown)",
            "Sources box (title + publisher + link)",
        ],
        "h2_pattern": "None required beyond the headline/subhead — press releases are undivided prose (use ## only for 'About X' / 'Media contact')",
        "cta_posture": "Media contact / press kit link only",
        "serp_gap_rule": "List exactly 3 facts the top-10 coverage includes that this release does not.",
    },
}

# JEV/brief-agent vocab that maps onto a template (unknown intents still
# fall back to informational — a bad ledger value can never break a brief).
_ALIASES = {
    "comparison": "commercial",
    "versus": "commercial",
    "commercial investigation": "commercial",
    "buyer": "transactional",
    "press": "press-release",
    "pr": "press-release",
    "news": "announcement",
    "milestone": "announcement",
}

_DEFAULT_INTENT = "informational"
_DEFAULT_FLOOR = 900


def template_for(intent: str) -> dict:
    """Template dict for an intent; unknown/empty intents fall back to
    informational so a bad ledger value can never break the brief."""
    key = (intent or "").strip().lower()
    key = _ALIASES.get(key, key)
    if key not in TEMPLATES:
        key = _DEFAULT_INTENT
    tpl = TEMPLATES[key]
    return {"intent": key, **tpl}


def word_floor_for(intent: str) -> int:
    """Deterministic word floor for a brief (pack onpage-aeo "length matches
    intent"): the intent template's `word_floor`, overridable by an explicit
    `GEN_MIN_WORDS` env (operator hard override, e.g. flagship-only sites).
    """
    env = (os.environ.get("GEN_MIN_WORDS") or "").strip()
    if env:
        try:
            return int(env)
        except ValueError:
            pass
    return int(template_for(intent).get("word_floor", _DEFAULT_FLOOR))


def template_text(intent: str) -> str:
    """Rendered one-block form for prompt/tool consumption."""
    t = template_for(intent)
    lines = [
        f"Intent template: {t['name']} ({t['intent']})",
        f"Goal: {t['goal']}",
        f"Angle: {t['angle']}",
        f"Length: at least {t['word_floor']} words (target {t['word_target']} "
        "for this intent — length matches intent, do not pad short intents "
        "or clip long ones)",
        "Required sections:",
    ]
    lines += [f"  - {s}" for s in t["required_sections"]]
    lines += [
        f"H2 pattern: {t['h2_pattern']}",
        f"CTA posture: {t['cta_posture']}",
        f"SERP gaps: {t['serp_gap_rule']}",
    ]
    return "\n".join(lines)
