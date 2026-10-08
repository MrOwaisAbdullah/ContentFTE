"""§5.3 Fact grounding — discrete gate BEFORE the frontier eval.

Order: Draft → fact-check → revise → eval (never draft → eval).
Claims without a source go back to revision: find a source or
soften/remove the claim. No LLM calls here — regex claim extraction +
source matching + HTTP 200 checks (reuses lib.link_validator).
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

ATTRIBUTION_RE = re.compile(
    r"(according to|per|as reported by|data from|study by)\s+([^.,;]{2,80})", re.IGNORECASE
)


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


def verify_claims(claims: list[dict], source_excerpts: list[str], check_links: bool = False,
                  markdown: str = "") -> dict:
    """Match each claim to ≥1 research excerpt. UNVERIFIED → revise.

    `source_excerpts`: raw text snippets from the research step.
    Returns {verified: [...], unverified: [...], sources_present: bool}.
    """
    corpus = "\n".join(source_excerpts or []).lower()
    verified, unverified = [], []
    for c in claims:
        needle = " ".join(re.findall(r"[a-z0-9]+", c["claim"].lower()))
        digits = "".join(re.findall(r"\d", c["claim"]))
        hit = bool(needle and needle in corpus) or bool(digits and digits in corpus)
        # Attribution to a named source counts as grounded even if the
        # numeric string isn't verbatim in the excerpt.
        if not hit and c.get("attribution"):
            src = c["attribution"].lower()
            hit = any(tok in corpus for tok in re.findall(r"[a-z0-9]+", src) if len(tok) > 3)
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
