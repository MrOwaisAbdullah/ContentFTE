"""§5.16 brief intent templates — deterministic structure per search intent.

Pure (no LLM): the Brief Agent receives its keyword's intent and MUST follow
the matching template so two briefs for similar keywords with different
intents (informational vs transactional) come out structurally distinct.
Templates cover the spec's brief checklist: angle, outline, SERP-gap
expectation, entities, sources, Brand-DNA injection (system-prompt level,
per §5.1), CTA posture.
"""
from __future__ import annotations

TEMPLATES: dict[str, dict] = {
    "informational": {
        "name": "Informational explainer",
        "goal": "Answer the query completely and earn passage citations / AI Overview inclusion.",
        "angle": "Teach-first: direct answer up top, depth below, zero selling.",
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
}

_DEFAULT_INTENT = "informational"


def template_for(intent: str) -> dict:
    """Template dict for an intent; unknown/empty intents fall back to
    informational so a bad ledger value can never break the brief."""
    key = (intent or "").strip().lower()
    if key not in TEMPLATES:
        key = _DEFAULT_INTENT
    tpl = TEMPLATES[key]
    return {"intent": key, **tpl}


def template_text(intent: str) -> str:
    """Rendered one-block form for prompt/tool consumption."""
    t = template_for(intent)
    lines = [
        f"Intent template: {t['name']} ({t['intent']})",
        f"Goal: {t['goal']}",
        f"Angle: {t['angle']}",
        "Required sections:",
    ]
    lines += [f"  - {s}" for s in t["required_sections"]]
    lines += [
        f"H2 pattern: {t['h2_pattern']}",
        f"CTA posture: {t['cta_posture']}",
        f"SERP gaps: {t['serp_gap_rule']}",
    ]
    return "\n".join(lines)
