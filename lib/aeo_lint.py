"""Deterministic answer-engine / on-page lint for a finished draft (plan SEO-24).

The writer prompts ask for a TL;DR, question-style H2s, a table for comparisons, one
FAQ block, attributed numbers and a real Sources list — but nothing *checked* that
after generation, so the live "94" article had none of it. This is that check.

Every finding is a **warning**, not a blocker: these are quality signals a human should
see before approving, and several are judgment calls (a how-to post has no comparison).
The hard blockers live in `lib/quality_gate.py`. Pure function, no I/O, no LLM.
"""
from __future__ import annotations

import re
from typing import Any, Iterable
from urllib.parse import urlparse

from lib.factcheck import ATTRIBUTION_RE

TLDR_MIN_WORDS, TLDR_MAX_WORDS = 40, 60
QUESTION_H2_MIN_RATIO = 0.4
MIN_ATTRIBUTED_NUMBERS = 2
MIN_SOURCE_DOMAINS = 3
MIN_WORDS_FOR_DEPTH_CHECKS = 600

_QUESTION_WORDS = ("what", "how", "why", "when", "where", "which", "who", "can", "should",
                   "does", "do", "is", "are", "will", "need")
_NON_TOPIC_H2 = ("sources", "faq", "frequently asked", "bottom line", "tl;dr", "tldr",
                 "conclusion", "references", "key takeaways", "summary")
# Domains that are weak evidence for a factual claim (user-generated / social / paywalled).
_WEAK_DOMAINS = ("medium.com", "youtube.com", "youtu.be", "reddit.com", "quora.com",
                 "x.com", "twitter.com", "facebook.com", "linkedin.com", "substack.com")

_H_RE = re.compile(r"^(#{2,3})[ \t]+(.+?)[ \t#]*$", re.M)
_LINK_RE = re.compile(r"\[[^\]]*\]\((https?://[^)\s]+)\)")
_NUM_RE = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?\s*(?:%|x\b|percent|million|billion|k\b)?")


def _finding(fid: str, message: str, **extra: Any) -> dict:
    return {"id": fid, "severity": "warn", "message": message, **extra}


def _sections(md: str) -> list[tuple[str, str]]:
    """[(heading text, body until the next ##/###)] for every H2/H3."""
    heads = list(_H_RE.finditer(md))
    out = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(md)
        out.append((m.group(2).strip(), md[m.end():end]))
    return out


def _is_question(heading: str) -> bool:
    h = heading.strip().lower().strip("*_` ")
    return h.endswith("?") or h.split(" ", 1)[0] in _QUESTION_WORDS


def _norm_q(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", str(text).lower()).strip()


def _tldr_words(md: str) -> int | None:
    m = re.search(r"TL\s*;?\s*DR\s*[:\-–—*_ ]*\s*(.+?)(?:\n\s*\n|\Z)", md[:2500], re.I | re.S)
    if not m:
        return None
    return len(re.findall(r"\b[\w'’-]+\b", re.sub(r"[#*_`>\[\]()]", " ", m.group(1))))


def _faq_questions(faqs: Iterable[Any] | None) -> list[str]:
    out = []
    for f in faqs or []:
        q = f.get("question") if isinstance(f, dict) else str(f)
        if q:
            out.append(_norm_q(q))
    return out


def lint(content_md: str, faqs: Iterable[Any] | None = None) -> list[dict]:
    md = content_md or ""
    findings: list[dict] = []
    words = len(md.split())
    sections = _sections(md)

    # 1. TL;DR length (presence is already a hard check in sdk/service._content_checks)
    n = _tldr_words(md)
    if n is not None and not (TLDR_MIN_WORDS <= n <= TLDR_MAX_WORDS):
        findings.append(_finding(
            "tldr_length",
            f"TL;DR is {n} words; aim for {TLDR_MIN_WORDS}-{TLDR_MAX_WORDS} so it can be lifted as a standalone answer.",
            value=n))

    # 2. Question-form H2s
    h2s = [m.group(2).strip() for m in _H_RE.finditer(md) if m.group(1) == "##"]
    topic_h2 = [h for h in h2s if not any(p in h.lower() for p in _NON_TOPIC_H2)]
    if len(topic_h2) >= 3:
        ratio = sum(_is_question(h) for h in topic_h2) / len(topic_h2)
        if ratio < QUESTION_H2_MIN_RATIO:
            findings.append(_finding(
                "question_headings",
                f"Only {round(ratio * 100)}% of H2s read as questions; question-style headings with a direct "
                f"answer underneath are what answer engines quote.", value=round(ratio, 2)))

    # 3. Comparison sections need a table
    for heading, body in sections:
        if re.search(r"\bcompar|\bvs\.?\b|\bversus\b|\bdifferences?\b", heading, re.I):
            if not re.search(r"^\s*\|.*\|\s*$\n^\s*\|?\s*:?-{3,}", body, re.M):
                findings.append(_finding(
                    "comparison_table",
                    f"'{heading}' compares things but has no table; use a real HTML/markdown table "
                    f"(never an image) so crawlers and AI engines can read it.", heading=heading))

    # 4. FAQ duplicated between the body and the FAQ block
    faq_qs = set(_faq_questions(faqs))
    body_qs = {_norm_q(h) for (h, _) in sections if _is_question(h)}
    dup = sorted(q for q in faq_qs & body_qs if q)
    has_body_faq = any(re.search(r"\bfaq\b|frequently asked", h, re.I) for (h, _) in sections)
    if len(dup) >= 2 or (faq_qs and has_body_faq):
        findings.append(_finding(
            "faq_duplicated",
            "The same FAQ content is emitted twice (in the article body and as the FAQ block/schema). "
            "Publish it once.", duplicates=dup[:5]))

    if words >= MIN_WORDS_FOR_DEPTH_CHECKS:
        # 5. Numbers need attribution
        attributed = 0
        for line in md.splitlines():
            if _NUM_RE.search(line) and (ATTRIBUTION_RE.search(line) or _LINK_RE.search(line)):
                attributed += 1
        if attributed < MIN_ATTRIBUTED_NUMBERS:
            findings.append(_finding(
                "attributed_numbers",
                f"Only {attributed} line(s) pair a figure with a named source or link "
                f"(want {MIN_ATTRIBUTED_NUMBERS}+); unsourced generic prose is what reads as AI filler.",
                value=attributed))

        # 6. Source quality
        m = re.search(r"^##[ \t]+(?:Sources|References)\b(.*?)(?=^##[ \t]|\Z)", md, re.M | re.I | re.S)
        if m:
            domains = [urlparse(u).netloc.lower().removeprefix("www.") for u in _LINK_RE.findall(m.group(1))]
            distinct = sorted(set(d for d in domains if d))
            weak = [d for d in distinct if any(d == w or d.endswith("." + w) for w in _WEAK_DOMAINS)]
            if len(distinct) < MIN_SOURCE_DOMAINS:
                findings.append(_finding(
                    "source_domains",
                    f"Sources cite {len(distinct)} distinct domain(s); aim for {MIN_SOURCE_DOMAINS}+ "
                    f"independent, authoritative ones.", value=len(distinct)))
            elif distinct and len(weak) / len(distinct) > 0.5:
                findings.append(_finding(
                    "weak_sources",
                    f"Most sources are user-generated/social ({', '.join(weak)}); prefer primary docs, "
                    f"papers or vendor pages.", domains=weak))
    return findings
