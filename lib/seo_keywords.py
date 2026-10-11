"""Operator-supplied keyword targets, and the hard gate on their usage.

The keyword sheet carries a primary keyword and 2-3 secondary keywords. The
prompts always *asked* for secondary keywords ("integrate 2-3 uses each") but
nothing ever supplied them, so the generator invented them or skipped the rule
outright. This module is the deterministic half: it parses the sheet cell,
counts where each keyword actually landed in the draft, and gates on the
result with a report a human can act on.

Pure (no LLM, no network, no DB) so it is testable and reusable by both the
SDK path (``sdk/service._content_checks``) and the sheet path
(``scripts/run_stage`` before it persists a row).
"""
from __future__ import annotations

import re
from typing import Iterable

# Hard cap: 1 primary + N secondaries. Extra secondaries in a sheet row are
# dropped (and reported) rather than gated on -- operator data that exceeds the
# contract must never block a publish.
MAX_SECONDARY = 3
_MAX_KEYWORD_CHARS = 60

# Phrases longer than this many words are topics, not keywords: demanding
# repeated natural use of an eight-word phrase is unwinnable, so they are
# reported and never gated.
_LONG_PHRASE_WORDS = 10
# Phrases between these word counts need only one use (a title-length keyword
# cannot be woven in twice without stuffing).
_SHORT_PHRASE_MAX_WORDS = 6

_MIN_USES = 2
_MIN_USES_LONG = 1
# A keyword is "stuffed" when it is dense AND frequent. A fixed share of body
# words only means something at flagship length: 0.8% of a 2500-word post is
# ~20 uses, but 0.8% of a 130-word compact page is one use. So the effective
# cap is the higher of the share and an absolute floor, which keeps compact
# buyer-intent pages (400-500 words, spec §5.10-5) from being flagged for
# using a keyword twice.
_STUFFING_SHARE = 0.008
_STUFFING_MIN_USES = 8

_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")


def _normalize(text: str) -> str:
    """Compare form: lowercase, punctuation folded to spaces, whitespace
    collapsed -- so "AI-agents" and "ai agents" match the same occurrences."""
    return re.sub(r"\s+", " ",
                  re.sub(r"[^a-z0-9]+", " ", (text or "").lower())).strip()


def parse_keywords(cell: str, *, kind: str = "secondary") -> "tuple[list[str], list[str]]":
    """Split a sheet cell into keywords.

    Accepts comma, semicolon or newline separators. De-duplicates
    case-insensitively and drops empties. Returns ``(keywords, warnings)``;
    a warning is emitted whenever input was discarded so the operator can
    see it instead of wondering why a keyword never showed up.
    """
    warnings: list[str] = []
    raw = str(cell or "").strip()
    if not raw:
        return [], warnings

    parts = [p.strip() for p in re.split(r"[;,\n]", raw) if p.strip()]
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        norm = _normalize(part)
        if not norm:
            continue
        if norm in seen:
            warnings.append(f"duplicate {kind} keyword dropped: '{part}'")
            continue
        seen.add(norm)
        if len(part) > _MAX_KEYWORD_CHARS:
            warnings.append(
                f"{kind} keyword longer than {_MAX_KEYWORD_CHARS} chars dropped: "
                f"'{part[:_MAX_KEYWORD_CHARS]}…'")
            continue
        if kind == "secondary" and len(out) >= MAX_SECONDARY:
            warnings.append(
                f"more than {MAX_SECONDARY} secondary keywords supplied; dropped "
                f"'{part}' (cap is {MAX_SECONDARY})")
            continue
        out.append(part)

    if kind == "primary" and len(out) > 1:
        warnings.append(
            "primary keyword cell held several values; only the first is used")
        out = out[:1]
    return out, warnings


def min_uses(keyword: str) -> int:
    """How many natural uses a keyword of this shape must reach before the
    gate is satisfied."""
    words = len(_normalize(keyword).split())
    if words > _LONG_PHRASE_WORDS:
        return 0          # topic-length: reported, never gated
    if words > _SHORT_PHRASE_MAX_WORDS:
        return _MIN_USES_LONG
    return _MIN_USES


def _word_re(keyword: str) -> re.Pattern:
    """Whole-phrase matcher that tolerates punctuation/hyphenation drift,
    so 'compact coffee maker' matches 'compact coffee-maker'."""
    parts = [_normalize(keyword).split()]
    words = parts[0]
    if not words:
        return re.compile(r"(?!x)x")   # never matches
    joined = r"[\s\-‑–—]+".join(re.escape(w) for w in words)
    return re.compile(rf"\b{joined}\b", re.IGNORECASE)


def split_markdown(markdown: str) -> "dict":
    """Slot map for a draft: the H1, every H2/H3 heading, and the body prose.
    Placement is what makes a keyword count -- a keyword used twice in
    headings is a topical signal; used twice in one paragraph it is stuffing.
    """
    text = markdown or ""
    lines = text.splitlines()
    title = ""
    headings: list[str] = []
    body: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# ") and not title:
            title = stripped[2:].strip()
            continue
        if stripped.startswith("## ") or stripped.startswith("### "):
            headings.append(stripped.lstrip("#").strip())
            continue
        body.append(line)
    return {"title": title, "headings": headings, "body": "\n".join(body)}


def keyword_placement(markdown: str, keyword: str) -> dict:
    """Occurrence counts per slot for one keyword."""
    slots = split_markdown(markdown)
    rx = _word_re(keyword)
    in_title = len(rx.findall(slots["title"]))
    in_headings = sum(len(rx.findall(h)) for h in slots["headings"])
    in_body = len(rx.findall(slots["body"]))
    return {
        "keyword": keyword,
        "in_title": in_title,
        "in_headings": in_headings,
        "in_body": in_body,
        "total": in_title + in_headings + in_body,
    }


def _density(markdown: str, keyword: str) -> float:
    body_words = max(1, len(split_markdown(markdown)["body"].split()))
    return keyword_placement(markdown, keyword)["in_body"] / body_words


def _stuffing_cap(markdown: str) -> float:
    """Effective density cap for the draft. Scales with length so a compact
    page is not flagged for one natural repeat while a 2000-word post still
    is: 0.8% of a 2500-word post is ~20 uses, but 0.8% of a 130-word page is
    a single mention."""
    body_words = max(1, len(split_markdown(markdown)["body"].split()))
    return max(_STUFFING_SHARE, _STUFFING_MIN_USES / body_words)


def check_keywords(markdown: str, *, primary: str = "",
                   secondary: Iterable[str] = ()) -> dict:
    """The gate.

    ``pass`` is False when any SUPPLIED keyword falls below its minimum use
    count. When no keywords were supplied (a legacy sheet row) the check
    passes with ``checked: False`` -- an absent column must not become a
    second blocker, which is exactly how the 2026-10-08 featured-image
    incident deadlocked a post.

    ``guidance`` explains every failure in operator terms: which keyword, how
    many uses it got, where they landed, and what to do about it.
    """
    secondary_list = [s for s in (secondary or []) if str(s).strip()]
    primary = (primary or "").strip()
    checked = bool(primary or secondary_list)

    counts: list[dict] = []
    guidance: list[str] = []
    passed = True
    cap = _stuffing_cap(markdown)

    targets = [("primary", primary)] + [("secondary", s) for s in secondary_list]
    for role, keyword in targets:
        if not keyword:
            continue
        placement = keyword_placement(markdown, keyword)
        placement["role"] = role
        placement["min_uses"] = min_uses(keyword)
        placement["gated"] = placement["min_uses"] > 0
        placement["density"] = round(_density(markdown, keyword), 4)
        counts.append(placement)

        if not placement["gated"]:
            continue
        if placement["total"] < placement["min_uses"]:
            passed = False
            where = (f"{placement['in_headings']} in headings, "
                     f"{placement['in_body']} in body")
            guidance.append(
                f"{role} keyword '{keyword}': {placement['total']} use(s), "
                f"needs {placement['min_uses']} ({where}). Give it "
                + ("a slot in the title or one H2 heading."
                   if placement["min_uses"] == 1 else
                   "one H2/H3 heading plus 1-2 natural body sentences."))
        elif placement["density"] > cap:
            guidance.append(
                f"{role} keyword '{keyword}' is at "
                f"{placement['density'] * 100:.1f}% of body words "
                f"({placement['in_body']} uses, cap {cap * 100:.1f}%) -- vary "
                "the anchor text and cut a repetition.")

    return {
        "pass": passed if checked else True,
        "checked": checked,
        "counts": counts,
        "missing": [c["keyword"] for c in counts
                    if c["gated"] and c["total"] < c["min_uses"]],
        "guidance": guidance,
    }
