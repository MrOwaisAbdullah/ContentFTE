"""§5.3 Fact grounding — discrete gate BEFORE the frontier eval.

Order: Draft → fact-check → revise → eval (never draft → eval).
Claims without a source go back to revision: find a source or
soften/remove the claim. No LLM calls here — regex claim extraction +
source matching + HTTP 200 checks (reuses lib.link_validator).

Matching rules (plan SEO-02 / PIPE-01 — the first version accepted almost
anything):
  * numbers match as WHOLE numbers ("5%" is not grounded by a stray "5" inside
    "45" or "2025"), thousands separators are normalised ("1,200" == "1200");
  * a number only counts as grounded when it appears in the research NEAR a
    meaningful word from the claim's own sentence — a bare coincidence of digits
    anywhere in the corpus is not evidence;
  * "according to X" only counts when X's distinctive name appears in the
    research (not a generic word such as "report" or "study"), and the attribution
    verbs match on word boundaries ("per" no longer fires inside "experience").
"""
from __future__ import annotations

import re

from lib.link_validator import validate_links

NUMERIC_RE = re.compile(
    r"(?P<claim>(?:\$|€|£)?\d[\d,]*(?:\.\d+)?\s*(?:%|percent|users|customers|clients|posts|articles|dollars|x|times)?"
    r"|(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,4}"
    r"|\b20\d{2}\b)",
    re.IGNORECASE,
)

# Verb on a word boundary; the named source must start with a capital letter or digit
# (`(?-i:...)` switches case-insensitivity off for that one character).
ATTRIBUTION_RE = re.compile(
    r"\b(according to|per|as reported by|data from|study by)\b\s+((?-i:[A-Z0-9])[^.,;]{1,79})",
    re.IGNORECASE,
)

_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_WORD_RE = re.compile(r"[a-z][a-z0-9'-]{3,}")
# Words that carry no evidential weight as "the source's name" or as claim context.
_GENERIC = frozenset({
    "report", "reports", "study", "studies", "survey", "research", "data", "analysis",
    "analyst", "analysts", "from", "that", "this", "with", "have", "will", "your",
    "their", "about", "which", "while", "after", "before", "been", "more", "than",
    "also", "into", "over", "such", "some", "most", "many", "year", "years", "percent",
    "users", "customers", "clients", "posts", "articles", "dollars", "times",
})
_PROXIMITY = 160  # characters either side of a matching number in the research


def extract_claims(markdown: str) -> list[dict]:
    """Pull checkable claims (stats, dates, prices, named entities)."""
    claims: list[dict] = []
    for i, line in enumerate((markdown or "").splitlines()):
        for m in NUMERIC_RE.finditer(line):
            text = m.group("claim").strip()
            if len(text) < 2:
                continue
            attr = ATTRIBUTION_RE.search(line)
            claims.append({
                "line": i + 1,
                "claim": text,
                "context": line.strip()[:300],
                "attribution": attr.group(0) if attr else "",
            })
    return claims


def _normalise_numbers(text: str) -> str:
    """Drop thousands separators so '1,200' and '1200' compare equal."""
    return re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text)


def _number_tokens(claim: str) -> list[str]:
    return [_normalise_numbers(t).rstrip(",.") for t in _NUMBER_RE.findall(claim or "")]


def _context_words(context: str, claim: str) -> set[str]:
    """Meaningful words from the claim's sentence, minus the number itself."""
    stripped = (context or "").lower().replace((claim or "").lower(), " ")
    return {w for w in _WORD_RE.findall(stripped) if w not in _GENERIC}


def _number_grounded(claim: dict, corpus: str) -> bool:
    """True when each number in the claim appears as a whole number in the research
    near at least one meaningful word from the claim's own sentence."""
    tokens = _number_tokens(claim.get("claim", ""))
    if not tokens:
        return False
    words = _context_words(claim.get("context", ""), claim.get("claim", ""))
    for tok in tokens:
        pat = re.compile(r"(?<![\d.])" + re.escape(tok) + r"(?!\d|\.\d)")
        found = False
        for m in pat.finditer(corpus):
            if not words:  # nothing but the number to go on: a whole-number hit is all we can ask
                found = True
                break
            window = corpus[max(0, m.start() - _PROXIMITY): m.end() + _PROXIMITY]
            if any(w in window for w in words):
                found = True
                break
        if not found:
            return False
    return True


def _attribution_grounded(attribution: str, corpus: str) -> bool:
    """The named source (not the verb, not generic words) must appear in the research."""
    m = ATTRIBUTION_RE.search(attribution or "")
    name = m.group(2) if m else ""
    distinctive = [w for w in _WORD_RE.findall(name.lower()) if w not in _GENERIC]
    return bool(distinctive) and any(w in corpus for w in distinctive)


def verify_claims(claims: list[dict], source_excerpts: list[str], check_links: bool = False,
                  markdown: str = "") -> dict:
    """Match each claim to ≥1 research excerpt. UNVERIFIED → revise.

    `source_excerpts`: raw text snippets from the research step.
    Returns {verified: [...], unverified: [...], sources_present: bool}.
    """
    corpus = _normalise_numbers("\n".join(source_excerpts or []).lower())
    verified, unverified = [], []
    for c in claims:
        needle = " ".join(re.findall(r"[a-z0-9]+", _normalise_numbers(c["claim"]).lower()))
        # The phrase match is for claims that carry words ("March 2024", "1,200 users"). A bare
        # number has no phrase to match — it must pass the context-aware number check below,
        # otherwise this branch would be exactly as lenient as the digit-substring bug.
        phrase_hit = bool(needle) and bool(re.search(r"[a-z]", needle)) and bool(re.search(
            r"(?<![a-z0-9])" + re.escape(needle).replace(r"\ ", r"[\s\W]+") + r"(?![a-z0-9])",
            corpus))
        hit = phrase_hit or _number_grounded(c, corpus)
        # A named source counts as grounded even if the numeric string isn't
        # verbatim in the excerpt — but only if that source's NAME is in the research.
        if not hit and c.get("attribution"):
            hit = _attribution_grounded(c["attribution"], corpus)
        (verified if hit else unverified).append({**c, "verified": hit})
    link_report = validate_links(markdown or "") if check_links and markdown else None
    return {
        "verified": verified,
        "unverified": unverified,
        "all_grounded": not unverified,
        "link_report": link_report,
    }


def gate_factcheck(markdown: str, source_excerpts: list[str]) -> dict:
    """Discrete gate result. `pass` False → revise, never send to eval."""
    claims = extract_claims(markdown)
    result = verify_claims(claims, source_excerpts)
    return {
        "pass": result["all_grounded"],
        "claim_count": len(claims),
        "unverified_count": len(result["unverified"]),
        "unverified": result["unverified"],
    }
