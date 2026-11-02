"""Near-duplicate detection for scaled-content control (SEO-05).

Google's "scaled content abuse" policy targets many pages produced mainly to rank, with little added value. The
engine can generate a post per keyword at will, so it needs its own tripwire for "this draft is the same article
as one we already have". Pure functions, no network, no model: word-shingle Jaccard similarity.

    near_duplicates(draft_md, [(id, title, md), ...], threshold=0.5) -> [{id, title, similarity}]

Markdown syntax, URLs, code blocks and numbers are stripped first so formatting or a changed date cannot hide a
copy. 5-word shingles are long enough that two different articles on the same topic share few of them (typically
well under 0.15) while a re-skinned copy shares most.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional, Tuple

SHINGLE = 5
DEFAULT_THRESHOLD = 0.5      # block: more than half the draft's phrasing already exists on the site
WARN_THRESHOLD = 0.3         # warn: a lot of shared phrasing

_FENCE = re.compile(r"```.*?```", re.S)
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_URL = re.compile(r"https?://\S+")
_WORD = re.compile(r"[a-z]+")


def normalize(markdown: str) -> List[str]:
    text = _FENCE.sub(" ", markdown or "")
    text = _LINK.sub(r"\1", text)
    text = _URL.sub(" ", text)
    return _WORD.findall(text.lower())


def shingles(words: List[str], k: int = SHINGLE) -> set:
    if len(words) < k:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i:i + k]) for i in range(len(words) - k + 1)}


def similarity(a_md: str, b_md: str) -> float:
    """Jaccard similarity of the two texts' shingle sets, 0..1."""
    a, b = shingles(normalize(a_md)), shingles(normalize(b_md))
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def near_duplicates(draft_md: str, others: Iterable[Tuple[int, str, str]], *,
                    threshold: float = WARN_THRESHOLD, limit: int = 5) -> List[dict]:
    """The `others` (id, title, markdown) at or above `threshold` similarity, most similar first."""
    draft = shingles(normalize(draft_md))
    if not draft:
        return []
    found = []
    for oid, title, md in others:
        other = shingles(normalize(md))
        if not other:
            continue
        sim = len(draft & other) / len(draft | other)
        if sim >= threshold:
            found.append({"id": oid, "title": title, "similarity": round(sim, 3)})
    found.sort(key=lambda r: -r["similarity"])
    return found[:limit]
