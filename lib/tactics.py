"""§5.15 tactics library — skill-pack wiring + brief-type builders + cluster
planning helpers.

Pure Python, no LLM calls and no network: the brief / draft / eval agents (and
`tools/tactics_tool.py`) call these to stay aligned with the maintained tactics
library instead of hardcoded prompt lore.

Two shapes of the same knowledge (spec §5.15):
- human-readable master: docs/Content FTE Research/ContentFTE-Tactics-Playbook.md
- loadable skill pack:   skills/seo-pack/SKILL.md + 13 references/ files

Gray-area tactics are never named in product/docs/UI — only their white-hat
mechanism is implemented (see references/gray-policy.md).
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Skill pack
# ---------------------------------------------------------------------------
SKILL_PACK_DIR = "skills/seo-pack"
SKILL_PACK_SKILL = "skills/seo-pack/SKILL.md"

# section key -> reference filename (order = SKILL.md "when to use what").
SKILL_REFERENCES: Dict[str, str] = {
    "keyword-strategy": "references/keyword-strategy.md",
    "brief-research": "references/brief-research.md",
    "onpage-aeo": "references/onpage-aeo.md",
    "geo-citability": "references/geo-citability.md",
    "authority-internal": "references/authority-internal.md",
    "refresh-decay": "references/refresh-decay.md",
    "agent-readiness": "references/agent-readiness.md",
    "eval-gates": "references/eval-gates.md",
    "brand-voice": "references/brand-voice.md",
    "local-seo": "references/local-seo.md",
    "coverage-multiplication": "references/coverage-multiplication.md",
    "gray-policy": "references/gray-policy.md",
    "technical-foundations": "references/technical-foundations.md",
}


def reference_path(section: str) -> str:
    """Repo-relative path to one skill-pack reference, or the SKILL.md if the
    section is unknown (callers should never 404 mid-prompt)."""
    rel = SKILL_REFERENCES.get((section or "").strip().lower())
    return f"{SKILL_PACK_DIR}/{rel}" if rel else SKILL_PACK_SKILL


def skill_pack_block() -> str:
    """One-block citation for system prompts: the skill-pack entry point plus
    the reference index, so a prompt can say 'per the skill pack §…' and the
    agent knows where to look."""
    lines = [
        f"Tactics skill pack: {SKILL_PACK_SKILL} (load references/ as needed). "
        "Apply these tactics; do not invent prompt tricks outside them.",
    ]
    lines += [f"  - {key}: {SKILL_PACK_DIR}/{rel}" for key, rel in SKILL_REFERENCES.items()]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Brief-type detection (§5.10-5 + §21)
# ---------------------------------------------------------------------------
_COMPARISON_MARKERS = (" vs ", " vs. ", " versus ", " compared to", " alternatives")
_LISTICLE_MARKERS = ("best ", "top ", "cheapest ", "alternatives", " for ")


def classify_keyword(keyword: str) -> str:
    """Deterministic page-type classification for a keyword.

    Returns "comparison" (X vs Y / alternatives), "listicle" (best X for Y /
    cheapest X), or "article" (default). Feeds the brief agent's choice of
    intent template + dedicated page builders."""
    k = f" {(keyword or '').strip().lower()} "
    if any(m in k for m in _COMPARISON_MARKERS):
        return "comparison"
    if any(m in k for m in _LISTICLE_MARKERS):
        return "listicle"
    return "article"


# ---------------------------------------------------------------------------
# PAA atomization pages (§3)
# ---------------------------------------------------------------------------
PAA_ANSWER_TARGET_WORDS = 120


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def build_paa_page_spec(question: str, keyword: str, link_to: str = "") -> Dict:
    """Spec for a dedicated page answering ONE PAA question (§3 atomization:
    one page per question, not an accordion).

    The page serves crawlers/LLM fan-out; the on-page FAQ block still serves
    readers. `link_to` is the originating (BOFU) article the page links up to.
    """
    q = (question or "").strip()
    return {
        "page_type": "paa",
        "h1": q,
        "keyword": keyword,
        "target_words": PAA_ANSWER_TARGET_WORDS,
        "url_path": f"/{_slug(keyword)}/faq/{_slug(q)}/",
        "required": [
            "Direct answer in the FIRST sentence (<= 50 words) — above the fold",
            f"Expand to ~{PAA_ANSWER_TARGET_WORDS} words with one concrete example or sourced fact",
            "One internal link up to the originating article",
            "FAQPage schema on the page",
        ],
        "internal_link_to": link_to,
        "faq_schema": True,
        "reference": reference_path("brief-research"),
    }


# ---------------------------------------------------------------------------
# Comparison pages (§21)
# ---------------------------------------------------------------------------
COMPARISON_REQUIRED_SECTIONS = [
    "H1: '[Client] vs [Competitor]' — exact match, client first",
    "TL;DR (40-60 words): who each option actually suits",
    "Selection criteria (4-6 criteria that matter to the buyer)",
    "Per-option H2s: strengths, weaknesses, best-for (neutral tone)",
    "Head-to-head Markdown pipe table on the key criteria",
    "FAQ block: 5-7 comparison-stage questions, answers < 50 words",
    "Sources box (title + publisher + link)",
]

COMPARISON_RULES = [
    "Neutral tone: state the competitor's real strengths; never strawman",
    "Link out to the competitor's own site — no cloaking, no hidden nofollow games",
    "Client-first ordering, but every competitor claim is sourced",
    "Fact-check gate REQUIRED before publish (spec §5.3)",
    "No invented prices/specs — mark unknown values as 'not published'",
    "Disclose the relationship to the client on the page",
]


def build_comparison_page_spec(
    client: str, competitor: str, keyword: str, benefits: Optional[List[str]] = None
) -> Dict:
    """Spec for a "[Client] vs [Competitor]" comparison page (§21 / §1 X-vs-Y).

    Neutral, fact-checked, self-first but competitor-linked. `benefits` is an
    optional list of the client's differentiators to make sure get covered.
    """
    c = (client or "").strip()
    comp = (competitor or "").strip()
    return {
        "page_type": "comparison",
        "h1": f"{c} vs {comp}",
        "keyword": keyword or f"{c} vs {comp}",
        "url_path": f"/{_slug(keyword or f'{c} vs {comp}')}/",
        "client": c,
        "competitor": comp,
        "self_first": True,
        "competitor_linked": True,
        "factcheck_required": True,
        "neutral_tone": True,
        "required_sections": list(COMPARISON_REQUIRED_SECTIONS),
        "rules": list(COMPARISON_RULES),
        "client_differentiators": [b for b in (benefits or []) if b],
        "reference": reference_path("coverage-multiplication"),
    }


# ---------------------------------------------------------------------------
# Cluster planning (§22 / §5.16 cluster mapping)
# ---------------------------------------------------------------------------
_STOPWORDS = {
    "the", "and", "for", "with", "your", "you", "are", "how", "what", "why",
    "when", "best", "top", "vs", "versus", "a", "an", "to", "of", "in", "on",
    "is", "it", "or", "that", "this", "from", "guide", "tips",
}


def _tokens(text: str) -> set:
    return {
        t for t in re.findall(r"[a-z0-9]+", (text or "").lower())
        if t not in _STOPWORDS and len(t) > 2
    }


def plan_cluster(seed: str, keywords: List[str], min_shared: int = 1) -> Dict:
    """Hub-and-spoke cluster plan (§22): assign each keyword to a hub (the seed
    keyword) by shared topical terms; unassigned keywords are reported as gaps.

    `coverage_pct` here is planning-time assignment coverage (keywords that
    attach to the hub ÷ total), distinct from the ledger's published coverage
    (spec §5.16), which is computed from article status at runtime.
    """
    hub_tokens = _tokens(seed)
    spokes: List[Dict] = []
    uncovered: List[str] = []
    for kw in keywords or []:
        shared = sorted(hub_tokens & _tokens(kw))
        if len(shared) >= max(1, min_shared):
            spokes.append({"keyword": kw, "shared_terms": shared})
        else:
            uncovered.append(kw)
    total = len(keywords or [])
    assigned_pct = round(100 * len(spokes) / total) if total else 0
    return {
        "hub": seed,
        "hub_terms": sorted(hub_tokens),
        "spokes": spokes,
        "uncovered": uncovered,
        "assigned_pct": assigned_pct,
        "holes": len(uncovered),
        "reference": reference_path("keyword-strategy"),
    }
